"""
Desktop Notifier - Sends desktop notifications to the user.

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
import subprocess
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _get_dbus_session_bus_address() -> Optional[str]:
    """
    Get the DBus session bus address for the current user.
    
    Returns:
        DBus session bus address, or None if not available
    """
    uid = os.getuid()
    
    # Check environment variable, but validate it matches current user
    bus_address = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
    if bus_address:
        # If it's set to root's bus but we're not root, ignore it
        if '/run/user/0/bus' in bus_address and uid != 0:
            logger.debug(f"DBUS_SESSION_BUS_ADDRESS points to root's bus but we're UID {uid}, ignoring")
            bus_address = None
        elif bus_address:
            return bus_address
    
    # Try to get from user's runtime directory
    runtime_dir = f"/run/user/{uid}"
    bus_socket = f"{runtime_dir}/bus"
    
    # Check if the socket exists (it's a socket file, not a regular file)
    if os.path.exists(bus_socket):
        # The DBus session bus address format is: unix:path=/run/user/UID/bus
        return f"unix:path={bus_socket}"
    
    # Fallback: try to get from XDG_RUNTIME_DIR
    xdg_runtime_dir = os.environ.get('XDG_RUNTIME_DIR')
    if xdg_runtime_dir:
        # Validate XDG_RUNTIME_DIR matches current user
        if f"/run/user/{uid}" in xdg_runtime_dir or uid == 0:
            bus_socket = f"{xdg_runtime_dir}/bus"
            if os.path.exists(bus_socket):
                return f"unix:path={bus_socket}"
    
    return None


class Notifier:
    """Sends desktop notifications using available methods."""
    
    def __init__(self):
        """Initialize the notifier and detect available notification method."""
        self.method = self._detect_method()
        self._cached_bus_address = None
        logger.debug(f"Notification method: {self.method}")
    
    def _detect_method(self) -> str:
        """Detect which notification method is available."""
        # Try notify-send first (most common on Linux)
        try:
            result = subprocess.run(
                ['which', 'notify-send'],
                capture_output=True,
                timeout=1
            )
            if result.returncode == 0:
                return 'notify-send'
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Try dbus-python as fallback
        try:
            import dbus
            return 'dbus'
        except ImportError:
            pass
        
        logger.warning("No notification method available. Notifications will be disabled.")
        return 'none'
    
    def notify(
        self,
        title: str,
        message: str,
        urgency: str = "normal",
        timeout: int = 5000,
        icon: Optional[str] = None
    ) -> bool:
        """
        Send a desktop notification.
        
        Args:
            title: Notification title
            message: Notification message/body
            urgency: Urgency level - "low", "normal", or "critical"
            timeout: Timeout in milliseconds (0 = never expire)
            icon: Optional icon path or name
            
        Returns:
            True if notification was sent successfully, False otherwise
        """
        if self.method == 'none':
            logger.debug(f"Notification disabled: {title} - {message}")
            return False
        
        try:
            if self.method == 'notify-send':
                return self._notify_send(title, message, urgency, timeout, icon)
            elif self.method == 'dbus':
                return self._notify_dbus(title, message, urgency, timeout, icon)
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False
        
        return False
    
    def _notify_send(
        self,
        title: str,
        message: str,
        urgency: str,
        timeout: int,
        icon: Optional[str]
    ) -> bool:
        """Send notification using notify-send command."""
        cmd = ['notify-send']
        
        # Add urgency
        if urgency in ['low', 'normal', 'critical']:
            cmd.extend(['--urgency', urgency])
        
        # Add timeout (convert milliseconds to seconds for notify-send)
        if timeout > 0:
            timeout_sec = timeout // 1000
            cmd.extend(['--expire-time', str(timeout_sec)])
        else:
            cmd.append('--expire-time=0')  # Never expire
        
        # Add icon if provided
        if icon:
            cmd.extend(['--icon', icon])
        
        # Add title and message
        cmd.append(title)
        cmd.append(message)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=2,
                check=False
            )
            if result.returncode == 0:
                logger.debug(f"Notification sent: {title}")
                return True
            else:
                logger.warning(f"notify-send failed: {result.stderr.decode('utf-8', errors='ignore')}")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"Error running notify-send: {e}")
            return False
    
    def _notify_dbus(
        self,
        title: str,
        message: str,
        urgency: str,
        timeout: int,
        icon: Optional[str]
    ) -> bool:
        """Send notification using dbus-python."""
        try:
            import dbus
            
            # Map urgency strings to dbus byte values
            urgency_map = {
                'low': 0,
                'normal': 1,
                'critical': 2
            }
            urgency_byte = urgency_map.get(urgency, 1)
            
            # Get the correct DBus session bus address for current user
            # Re-detect each time in case privileges were dropped after initialization
            bus_address = _get_dbus_session_bus_address()
            if bus_address:
                # Only update if different from cached or environment
                if bus_address != self._cached_bus_address:
                    os.environ['DBUS_SESSION_BUS_ADDRESS'] = bus_address
                    self._cached_bus_address = bus_address
                    logger.debug(f"Using DBus session bus: {bus_address}")
            elif 'DBUS_SESSION_BUS_ADDRESS' not in os.environ:
                # If we can't detect it and it's not set, log a warning
                logger.warning("Could not determine DBus session bus address")
                return False
            
            # Connect to session bus
            bus = dbus.SessionBus()
            notify_obj = bus.get_object(
                'org.freedesktop.Notifications',
                '/org/freedesktop/Notifications'
            )
            notify_iface = dbus.Interface(
                notify_obj,
                'org.freedesktop.Notifications'
            )
            
            # Prepare hints
            hints = {
                'urgency': dbus.Byte(urgency_byte)
            }
            if icon:
                hints['image-path'] = icon
            
            # Send notification
            notify_iface.Notify(
                'Screen Time Tracker',  # app_name
                0,  # replaces_id (0 = new notification)
                icon or '',  # app_icon
                title,  # summary
                message,  # body
                [],  # actions
                hints,  # hints
                timeout  # expire_timeout (milliseconds)
            )
            
            logger.debug(f"Notification sent via dbus: {title}")
            return True
            
        except ImportError:
            logger.error("dbus-python not available")
            return False
        except Exception as e:
            logger.error(f"Error sending dbus notification: {e}")
            return False
    
    def notify_limit_exceeded(self, used_seconds: int, limit_seconds: int):
        """Send notification when daily limit is exceeded."""
        used_hours = used_seconds // 3600
        used_mins = (used_seconds % 3600) // 60
        limit_hours = limit_seconds // 3600
        limit_mins = (limit_seconds % 3600) // 60
        
        self.notify(
            title="Daily Limit Exceeded",
            message=f"Used {used_hours:02d}:{used_mins:02d} / Limit {limit_hours:02d}:{limit_mins:02d}",
            urgency="critical",
            timeout=10000  # 10 seconds
        )
    
    def notify_rest_time(self, app_name: str):
        """Send notification when app is killed during rest time."""
        self.notify(
            title="Rest Time Active",
            message=f"{app_name} was closed during rest time",
            urgency="normal",
            timeout=5000  # 5 seconds
        )
    
    def notify_limit_warning(self, remaining_seconds: int, threshold_percent: int = 10):
        """Send notification when approaching daily limit."""
        remaining_hours = remaining_seconds // 3600
        remaining_mins = (remaining_seconds % 3600) // 60
        
        self.notify(
            title="Daily Limit Warning",
            message=f"Only {remaining_hours:02d}:{remaining_mins:02d} remaining today",
            urgency="normal",
            timeout=5000  # 5 seconds
        )

