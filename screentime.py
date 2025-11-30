#!/usr/bin/env python3
"""
Screen Time Tracker - Main application entry point.

Copyright (C) 2025  Sören Heisrath <screentime at projects dot heisrath dot org>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import sys
import os
import signal
import time
import logging
import threading
import importlib.util
from collections import deque
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path for direct execution
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from policy.config_manager import ConfigManager
from core.tracker import TimeTracker
from core.monitor import X11Monitor
from utils.notifications import Notifier
from utils.system import drop_privileges, configure_user_environment
from managers.process_manager import ProcessManager
from managers.warning_manager import RestTimeWarningManager, LimitWarningManager
from daemon import daemonize, check_daemon_running, get_pid_file_path
from utils.ipc import SocketServer, get_socket_path
from logging_setup import setup_logging

# Import screentime-cli module (handles hyphen in filename)
_cli_module_path = Path(__file__).parent / "screentime-cli.py"
if _cli_module_path.exists():
    spec = importlib.util.spec_from_file_location("screentime_cli", _cli_module_path)
    screentime_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(screentime_cli)
    parse_arguments = screentime_cli.parse_arguments
    show_stats = screentime_cli.show_stats
    show_logs = screentime_cli.show_logs
    handle_reload_command = screentime_cli.handle_reload_command
    handle_terminate_command = screentime_cli.handle_terminate_command
    handle_modify_rest_time_command = screentime_cli.handle_modify_rest_time_command
    handle_set_temporary_usage_command = screentime_cli.handle_set_temporary_usage_command
else:
    raise ImportError(f"Could not find screentime-cli.py at {_cli_module_path}")

logger = logging.getLogger(__name__)


class ScreenTimeTracker:
    """Main application class."""
    
    def __init__(self, config_path: str = None):
        """Initialize the tracker."""
        self.running = False
        self.config_manager = ConfigManager(config_path)
        self.monitor = None  # Lazily connect to X
        self.monitor_retry_interval = 10  # seconds
        self.data_dir = self.config_manager.get_data_directory()
        self.tracker = TimeTracker(self.data_dir, self.config_manager)
        self.last_history_save = time.time()
        self.history_save_interval = 120  # 2 minutes
        
        # Initialize managers
        self.notifier = Notifier()
        self.process_manager = ProcessManager(self.notifier)
        self.rest_time_warning = RestTimeWarningManager(self.notifier, self.config_manager)
        self.limit_warning = LimitWarningManager(self.notifier)
        
        # Reload flag for IPC
        self.reload_flag = threading.Event()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _is_permission_error(self, error: Exception) -> bool:
        """Return True if the error looks like a permission/authentication issue."""
        if isinstance(error, PermissionError):
            return True
        errno = getattr(error, "errno", None)
        if errno == 13:  # EACCES
            return True
        message = str(error).lower()
        keywords = ("auth", "authoriz", "permission", "access", "denied")
        return any(keyword in message for keyword in keywords)
    
    def initialize_monitor(self) -> bool:
        """
        Attempt to connect to the X server.
        
        Returns:
            True if connection succeeded, False if X is unavailable.
        
        Raises:
            PermissionError: When the failure appears to be due to permissions/auth.
        """
        try:
            self.monitor = X11Monitor()
            logger.info("Connected to X server (DISPLAY=%s)", os.environ.get("DISPLAY"))
            return True
        except Exception as exc:
            self.monitor = None
            if self._is_permission_error(exc):
                raise PermissionError(f"Cannot connect to X server: {exc}") from exc
            logger.warning("Unable to connect to X server (%s)", exc)
            return False
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        if self.running:
            logger.info("Received shutdown signal, stopping...")
            self.running = False
        else:
            # Force exit if we're already shutting down
            logger.warning("Force shutdown requested")
            sys.exit(1)
    
    def run(self, daemon: bool = False, socket_server: SocketServer = None):
        """Run the tracker."""
        self.running = True
        interval = self.config_manager.get_tracking_interval()
        
        logger.info("Starting screen time tracker...")
        logger.info(f"Tracking interval: {interval} seconds")
        logger.info(f"Daily limit: {self.config_manager.get_daily_limit()} seconds")
        logger.info(f"Allowlisted apps: {self.config_manager.config.get('allowlist', [])}")
        logger.info(f"Denylisted apps: {self.config_manager.config.get('denylist', [])}")
        
        last_window = None
        last_suspend_check = time.time()
        suspend_check_interval = 10  # Check for suspend every 10 seconds
        
        try:
            while self.running:
                # Check for config reload request
                if self.reload_flag.is_set():
                    logger.info("Reloading configuration...")
                    try:
                        # Reload config
                        self.config_manager.reload_config()
                        # Update tracker with new config
                        self.tracker.config = self.config_manager
                        # Update interval
                        interval = self.config_manager.get_tracking_interval()
                        logger.info("Configuration reloaded successfully")
                        logger.info(f"New tracking interval: {interval} seconds")
                        logger.info(f"New daily limit: {self.config_manager.get_daily_limit()} seconds")
                        logger.info(f"New allowlisted apps: {self.config_manager.config.get('allowlist', [])}")
                        logger.info(f"New denylisted apps: {self.config_manager.config.get('denylist', [])}")
                    except Exception as e:
                        logger.error(f"Error reloading configuration: {e}", exc_info=True)
                    finally:
                        self.reload_flag.clear()
                
                # Ensure monitor connection exists
                if self.monitor is None:
                    try:
                        monitor_ready = self.initialize_monitor()
                    except PermissionError as e:
                        logger.error("Permission error connecting to X server: %s", e)
                        self.running = False
                        break
                    
                    if not monitor_ready:
                        if daemon:
                            logger.info(
                                "X server not available. Retrying in %s seconds...",
                                self.monitor_retry_interval
                            )
                            time.sleep(self.monitor_retry_interval)
                            continue
                        else:
                            logger.error("X server is not available. Exiting.")
                            self.running = False
                            break
                
                # Check if we're shutting down before doing any work
                if not self.running:
                    break
                
                # Check for suspend every 10 seconds
                current_time = time.time()
                if current_time - last_suspend_check >= suspend_check_interval:
                    self.tracker.check_suspend()
                    last_suspend_check = current_time
                
                window_info = self.monitor.get_active_window()
                
                # Check again after potentially blocking call
                if not self.running:
                    break
                
                if window_info:
                    app_name, window_title, win_id = window_info
                    
                    # Only update if window changed
                    if app_name != last_window:
                        logger.debug(f"Active window: {app_name} - {window_title}")
                        last_window = app_name
                    
                    # Update tracker
                    self.tracker.update(app_name, window_title)
                    
                    # Check limit and rest time status
                    stats = self.tracker.get_detailed_stats()
                    should_kill = False
                    reason = ""
                    
                    check_name = f"{app_name} {window_title}"
                    # Check if we should kill denylisted apps
                    if self.config_manager.is_denylisted(check_name) and not self.config_manager.is_allowlisted(check_name):
                        if stats["in_rest_time"]:
                            should_kill = True
                            reason = "rest time"
                        elif stats["limit_exceeded"]:
                            should_kill = True
                            reason = "daily limit exceeded"
                    
                    if should_kill:
                        pid = self.monitor.get_window_pid(win_id, app_name)
                        if pid:
                            logger.debug(f"Killing {app_name} (PID: {pid}, window: \"{window_title}\") because {reason}")
                            self.process_manager.kill_process(pid, app_name, reason)
                        else:
                            logger.warning(f"Could not determine PID for {app_name} (window: \"{window_title}\"), skipping kill request ({reason})")
                    
                    # Log limit exceeded status
                    if stats["limit_exceeded"] and not self.config_manager.is_allowlisted(app_name):
                        if not stats["in_rest_time"]:
                            logger.warning(
                                f"Daily limit exceeded! "
                                f"Used: {stats['denylisted_usage']}s / "
                                f"Limit: {stats['daily_limit']}s"
                            )
                    
                    # Check warnings
                    self.rest_time_warning.check_and_notify(stats)
                    self.limit_warning.check_and_notify(stats)
                else:
                    logger.debug("Could not determine active window")
                
                # Save history every 2 minutes (only if not shutting down)
                if self.running:
                    current_time = time.time()
                    if current_time - self.last_history_save >= self.history_save_interval:
                        self.tracker.save_history()
                        self.last_history_save = current_time
                        logger.debug("History saved (periodic)")
                
                # Sleep in small chunks to allow quick shutdown
                if self.running:
                    sleep_chunk = min(interval, 0.1)  # Check every 100ms max
                    elapsed = 0
                    while elapsed < interval and self.running:
                        time.sleep(sleep_chunk)
                        elapsed += sleep_chunk
                
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            self.running = False
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            self.running = False
        finally:
            logger.info("Shutting down, saving data...")
            try:
                self.tracker.stop()
                logger.info("Screen time tracker stopped")
            except Exception as e:
                logger.error(f"Error during shutdown: {e}", exc_info=True)
            finally:
                # Stop socket server
                if socket_server:
                    socket_server.stop()
                
                # Clean up PID file
                pid_file_path = get_pid_file_path(self.data_dir)
                if pid_file_path.exists():
                    try:
                        pid_file_path.unlink()
                        logger.debug("PID file removed")
                    except Exception as e:
                        logger.debug(f"Error removing PID file: {e}")
                
                # Close X11 connection
                try:
                    if self.monitor:
                        self.monitor.close()
                except Exception as e:
                    logger.debug(f"Error closing X11 connection: {e}")


def main():
    """Main entry point."""
    # Set DISPLAY environment variable if not set
    if 'DISPLAY' not in os.environ:
        os.environ['DISPLAY'] = ':0.0'
    
    args = parse_arguments()
    
    is_logs_command = args.logs is not None
    is_reload_command = bool(args.reload)
    is_terminate_command = bool(args.terminate)
    is_stats_command = bool(args.stats)
    is_modify_rest_time_command = args.morning_end is not None or args.evening_start is not None
    is_set_temporary_usage_command = args.bonus_time is not None
    requires_priv_drop = not (is_logs_command or is_reload_command or is_terminate_command or is_stats_command or is_modify_rest_time_command or is_set_temporary_usage_command)
    
    # Configure environment or drop privileges based on requested user
    if args.user:
        try:
            if requires_priv_drop:
                drop_privileges(args.user)
            else:
                configure_user_environment(args.user, change_directory=False)
        except (ValueError, PermissionError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Setup logging
    daemon_mode = not args.no_daemon and not args.stats and args.logs is None and not args.reload and not args.terminate
    log_buffer = setup_logging(daemon_mode=daemon_mode, verbose=args.verbose)
    
    if 'DISPLAY' not in os.environ:
        logger.info(f"DISPLAY not set, using default: :0.0")
    
    # Handle commands that need to connect to daemon
    if is_reload_command:
        handle_reload_command(args.config)
        return
    
    if is_terminate_command:
        handle_terminate_command(args.config)
        return
    
    # Handle modify rest time command
    if is_modify_rest_time_command:
        handle_modify_rest_time_command(
            config_path=args.config,
            morning_end=args.morning_end,
            evening_start=args.evening_start
        )
        return
    
    # Handle set bonus time command
    if is_set_temporary_usage_command:
        handle_set_temporary_usage_command(
            config_path=args.config,
            minutes=args.bonus_time
        )
        return
    
    # Handle logs command
    if is_logs_command:
        show_logs(args.config, args.logs if args.logs > 0 else 100, log_buffer)
        return
    
    # Handle stats command
    if is_stats_command:
        show_stats(args.config)
        return
    
    # Create tracker instance
    tracker = ScreenTimeTracker(args.config)
    
    # Attempt initial X connection (to surface permission issues before daemonizing)
    try:
        monitor_ready = tracker.initialize_monitor()
    except PermissionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    if not monitor_ready:
        if daemon_mode:
            logger.warning(
                "X server not available. Daemon will retry connection every 10 seconds."
            )
        else:
            print(
                "Error: Cannot connect to X server. Ensure DISPLAY is set and X is running.",
                file=sys.stderr
            )
            sys.exit(1)
    
    # Daemonize if needed
    socket_server = None
    if daemon_mode:
        # Check if daemon is already running
        is_running, existing_pid = check_daemon_running(tracker.data_dir)
        if is_running:
            pid_msg = f" (PID: {existing_pid})" if existing_pid else ""
            print(f"Error: screentime daemon is already running{pid_msg}", file=sys.stderr)
            print(f"Use 'screentime --terminate' to stop it, or 'screentime --logs' to view logs.", file=sys.stderr)
            sys.exit(1)
        
        # Clean up any stale PID file
        pid_file_path = get_pid_file_path(tracker.data_dir)
        if pid_file_path.exists():
            try:
                pid_file_path.unlink()
            except Exception:
                pass
        
        daemonize(pid_file_path)
        logger.info("Running in daemon mode")
        
        # Start socket server for log queries
        socket_server = SocketServer(
            tracker.data_dir,
            log_buffer,
            tracker_instance=tracker,
            reload_flag=tracker.reload_flag
        )
        socket_server.start()
        logger.info("Socket server started for log queries")
    
    # Run the tracker
    tracker.run(daemon=daemon_mode, socket_server=socket_server)


if __name__ == "__main__":
    main()

