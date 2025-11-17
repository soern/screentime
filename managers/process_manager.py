"""
Process management and enforcement.

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
import os
import signal
import time
import logging
from typing import Dict

from utils.notifications import Notifier

logger = logging.getLogger(__name__)


def _can_kill_process(pid: int) -> bool:
    """
    Check if we can kill the process (i.e., it exists and we own it).
    
    Args:
        pid: Process ID to check
        
    Returns:
        True if we can kill the process, False otherwise
    """
    if pid <= 0:
        return False
    
    try:
        # Check if process exists and we can signal it (signal 0 doesn't actually send a signal)
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        # Process doesn't exist
        return False
    except PermissionError:
        # Process exists but we don't have permission (not owned by us)
        return False
    except Exception:
        # Other error
        return False


def _is_process_running(pid: int) -> bool:
    """
    Check if a process is still running.
    
    Args:
        pid: Process ID to check
        
    Returns:
        True if process is running, False otherwise
    """
    try:
        # Signal 0 doesn't actually send a signal, just checks if process exists
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        # Process doesn't exist
        return False
    except PermissionError:
        # Process exists but we don't have permission
        # Assume it's still running (we'll try to kill it anyway)
        return True
    except Exception:
        # Other error - assume not running to be safe
        return False


class ProcessManager:
    """Manages process termination and enforcement."""
    
    def __init__(self, notifier: Notifier, kill_cooldown: int = 5):
        """
        Initialize process manager.
        
        Args:
            notifier: Notifier instance for user notifications
            kill_cooldown: Minimum seconds between kill attempts for same PID
        """
        self.notifier = notifier
        self.kill_cooldown = kill_cooldown
        self.last_kill_attempt: Dict[int, float] = {}  # Track last kill attempt per PID
    
    def kill_process(self, pid: int, app_name: str, reason: str = "") -> bool:
        """
        Kill a process by PID and notify the user.
        
        First sends SIGTERM for graceful shutdown, then waits up to 15 seconds.
        If the process is still running after 15 seconds, sends SIGKILL.
        
        Args:
            pid: Process ID to kill
            app_name: Application name (for logging and notification)
            reason: Reason for killing (e.g., "rest time", "daily limit exceeded")
            
        Returns:
            True if kill was attempted, False if skipped (cooldown)
        """
        if not pid or pid <= 0:
            return False
        
        current_time = time.time()
        
        # Check cooldown to avoid killing too frequently
        if pid in self.last_kill_attempt:
            if (current_time - self.last_kill_attempt[pid]) < self.kill_cooldown:
                return False
        
        # Check if we can actually kill this process
        if not _can_kill_process(pid):
            logger.warning(f"Cannot kill {app_name} (PID: {pid}): Process not found or permission denied")
            # Still notify user about the attempt
            self.notifier.notify(
                title=f"Cannot Close {app_name}",
                message="Permission denied. Application could not be closed.",
                urgency="normal",
                timeout=8000  # 8 seconds
            )
            return False
        
        try:
            # Try graceful termination first (SIGTERM)
            os.kill(pid, signal.SIGTERM)
            self.last_kill_attempt[pid] = current_time
            logger.warning(f"Sent SIGTERM to {app_name} (PID: {pid}) - Reason: {reason}")
            
            # Wait up to 15 seconds for the process to terminate gracefully
            wait_timeout = 15.0
            check_interval = 0.5  # Check every 500ms
            elapsed = 0.0
            
            while elapsed < wait_timeout:
                time.sleep(check_interval)
                elapsed += check_interval
                
                if not _is_process_running(pid):
                    # Process terminated gracefully
                    logger.info(f"Process {app_name} (PID: {pid}) terminated gracefully after {elapsed:.1f}s")
                    break
            else:
                # Process is still running after timeout, force kill with SIGKILL
                if _is_process_running(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                        logger.warning(f"Sent SIGKILL to {app_name} (PID: {pid}) - Process did not respond to SIGTERM")
                        # Wait a bit to see if SIGKILL worked
                        time.sleep(0.5)
                        if not _is_process_running(pid):
                            logger.info(f"Process {app_name} (PID: {pid}) terminated with SIGKILL")
                        else:
                            logger.warning(f"Process {app_name} (PID: {pid}) may still be running after SIGKILL")
                    except ProcessLookupError:
                        # Process already dead (race condition)
                        logger.debug(f"Process {app_name} (PID: {pid}) already terminated")
                    except PermissionError:
                        logger.warning(f"Cannot send SIGKILL to {app_name} (PID: {pid}): Permission denied")
                    except Exception as e:
                        logger.error(f"Error sending SIGKILL to {app_name} (PID: {pid}): {e}")
            
            # Send notification to user
            reason_text = reason.replace("_", " ").title() if reason else "Screen time limit"
            self.notifier.notify(
                title=f"{app_name} Closed",
                message=f"Application was closed due to: {reason_text}",
                urgency="normal",
                timeout=8000  # 8 seconds
            )
            
            return True
        except ProcessLookupError:
            # Process already dead
            logger.debug(f"Process {app_name} (PID: {pid}) already terminated")
            return False
        except PermissionError:
            # Don't have permission to kill this process
            logger.warning(f"Cannot kill {app_name} (PID: {pid}): Permission denied")
            # Still notify user about the attempt
            self.notifier.notify(
                title=f"Cannot Close {app_name}",
                message="Permission denied. Application could not be closed.",
                urgency="normal",
                timeout=8000  # 8 seconds
            )
            return False
        except Exception as e:
            logger.error(f"Error killing process {app_name} (PID: {pid}): {e}")
            return False

