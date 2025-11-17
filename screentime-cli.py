"""
Command-line interface for screentime.

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
import argparse
import logging
from pathlib import Path

from policy.config_manager import ConfigManager
from core.tracker import TimeTracker
from utils.ipc import get_socket_path, send_socket_command, query_socket_logs
from daemon import check_daemon_running

logger = logging.getLogger(__name__)


def show_stats(config_path: str = None):
    """Display current statistics."""
    config_manager = ConfigManager(config_path)
    data_dir = config_manager.get_data_directory()
    tracker = TimeTracker(data_dir, config_manager)
    stats = tracker.get_detailed_stats()
    
    def format_time(seconds: int) -> str:
        """Format seconds as HH:MM:SS."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    print("\n" + "=" * 60)
    print("SCREEN TIME STATISTICS")
    print("=" * 60)
    print(f"Date: {stats['date']}")
    print(f"\nDenylisted Apps Usage:")
    print(f"  Total: {format_time(stats['denylisted_usage'])}")
    print(f"  Limit: {format_time(stats['daily_limit'])}")
    print(f"  Remaining: {format_time(stats['remaining'])}")
    print(f"  Status: {'LIMIT EXCEEDED' if stats['limit_exceeded'] else 'OK'}")
    
    if stats['denylisted_apps']:
        print(f"\n  Per Application:")
        for app, seconds in sorted(stats['denylisted_apps'].items(), 
                                 key=lambda x: x[1], reverse=True):
            print(f"    {app}: {format_time(int(seconds))}")
    
    print(f"\nAllowlisted Apps Usage:")
    print(f"  Total: {format_time(stats['allowlisted_usage'])}")
    
    if stats['allowlisted_apps']:
        print(f"\n  Per Application:")
        for app, seconds in sorted(stats['allowlisted_apps'].items(), 
                                 key=lambda x: x[1], reverse=True):
            print(f"    {app}: {format_time(int(seconds))}")
    
    print(f"\nRest Time: {'Active' if stats['in_rest_time'] else 'Inactive'}")
    if stats['holiday_mode']:
        print(f"Holiday Mode: Active (extended limits)")
    
    print(f"\nTotal Sessions: {stats['total_sessions']}")
    print("=" * 60 + "\n")


def show_logs(config_path: str = None, lines: int = 100, log_buffer=None):
    """Display recent log entries from buffer."""
    logs = []
    socket_error = None
    
    # Always try to get logs from socket first (daemon might be running)
    try:
        config_manager = ConfigManager(config_path)
        data_dir = config_manager.get_data_directory()
        socket_path = get_socket_path(data_dir)
        
        # Check if socket exists
        if not socket_path.exists():
            socket_error = f"Socket not found at {socket_path}. Is daemon running?"
        else:
            # Query logs via socket
            response = send_socket_command(socket_path, "logs", lines=lines)
            if response.get("status") == "ok":
                logs = response.get("logs", [])
            else:
                socket_error = response.get("message", "Unknown error from daemon")
    except Exception as e:
        # If socket query fails, note the error
        socket_error = str(e)
        logger.debug(f"Could not query socket: {e}")
    
    # Fallback to local buffer if socket query failed or returned no logs
    if not logs and log_buffer:
        logs = list(log_buffer)[-lines:]
    
    if not logs:
        if socket_error:
            print(f"Error querying daemon: {socket_error}")
        print("No log entries available (not running in daemon mode or buffer is empty)")
        return
    
    print("\n" + "=" * 60)
    print(f"RECENT LOG ENTRIES (showing last {len(logs)} entries)")
    print("=" * 60)
    
    for log_line in logs:
        print(log_line)
    
    print("=" * 60 + "\n")


def handle_reload_command(config_path: str = None):
    """Handle reload command."""
    config_manager = ConfigManager(config_path)
    data_dir = config_manager.get_data_directory()
    socket_path = get_socket_path(data_dir)
    
    response = send_socket_command(socket_path, "reload")
    if response.get("status") == "ok":
        print("Configuration reload requested successfully")
    else:
        print(f"Error: {response.get('message', 'Unknown error')}")
        sys.exit(1)


def handle_terminate_command(config_path: str = None):
    """Handle terminate command."""
    config_manager = ConfigManager(config_path)
    data_dir = config_manager.get_data_directory()
    socket_path = get_socket_path(data_dir)
    
    response = send_socket_command(socket_path, "terminate")
    if response.get("status") == "ok":
        print("Shutdown requested successfully")
    else:
        print(f"Error: {response.get('message', 'Unknown error')}")
        sys.exit(1)


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Screen Time Tracker for X11 environment"
    )
    parser.add_argument(
        '-c', '--config',
        type=str,
        help='Path to configuration file'
    )
    parser.add_argument(
        '-s', '--stats',
        action='store_true',
        help='Show statistics and exit'
    )
    parser.add_argument(
        '--no-daemon',
        action='store_true',
        help='Run in foreground (default is daemon mode)'
    )
    parser.add_argument(
        '-l', '--logs',
        type=int,
        metavar='N',
        default=None,
        help='Show last N log entries from buffer and exit' 
    )
    parser.add_argument(
        '-r', '--reload',
        action='store_true',
        help='Reload configuration from daemon and exit'
    )
    parser.add_argument(
        '-t', '--terminate',
        action='store_true',
        help='Terminate the daemon and exit'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '-u', '--user',
        type=str,
        metavar='USERNAME',
        help='Drop privileges to specified user (requires root privileges)'
    )
    
    return parser.parse_args()

