"""
X11 Window Monitor - Tracks active window titles in X11 environment using Xlib.

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
import re
import os
import time
import logging
import subprocess
from contextlib import contextmanager
from typing import Optional, Tuple, Union
from utils.strings import sanitize_string
logger = logging.getLogger(__name__)

try:
    from Xlib import X
    from Xlib.display import Display
    from Xlib.error import XError
    from Xlib.xobject.drawable import Window
    XLIB_AVAILABLE = True
except ImportError:
    XLIB_AVAILABLE = False
    logger.warning("python-xlib not available. Install with: pip install python-xlib")


class X11Monitor:
    """Monitors active window in X11 environment using Xlib."""
    
    def __init__(self):
        self._last_window = None
        self._last_title = None
        self._last_win_id = None
        self._pid_cache: dict[str, tuple[int, float]] = {}  # app_name -> (pid, timestamp)
        self._pid_cache_ttl = 30  # Cache PIDs for 30 seconds
        
        if not XLIB_AVAILABLE:
            raise ImportError("python-xlib is required. Install with: pip install python-xlib")
        
        try:
            # Connect to the X server and get the root window
            self.disp = Display()
            self.root = self.disp.screen().root
            
            # Prepare the property names we use
            self.NET_ACTIVE_WINDOW = self.disp.intern_atom('_NET_ACTIVE_WINDOW')
            self.NET_WM_NAME = self.disp.intern_atom('_NET_WM_NAME')  # UTF-8
            self.WM_NAME = self.disp.intern_atom('WM_NAME')           # Legacy encoding
            self.WM_CLASS = self.disp.intern_atom('WM_CLASS')
            self.NET_WM_PID = self.disp.intern_atom('_NET_WM_PID')    # Process ID
            
            logger.debug("X11Monitor initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize X11 connection: {e}")
            raise
    
    @contextmanager
    def _window_obj(self, win_id: Optional[int]):
        """Simplify dealing with BadWindow (make it either valid or None)"""
        window_obj = None
        if win_id:
            try:
                window_obj = self.disp.create_resource_object('window', win_id)
            except XError:
                pass
        yield window_obj
    
    def _get_active_window_id(self) -> Optional[int]:
        """Get the ID of the currently active window."""
        try:
            response = self.root.get_full_property(
                self.NET_ACTIVE_WINDOW,
                X.AnyPropertyType
            )
            if not response or not response.value:
                return None
            return response.value[0]
        except (XError, AttributeError) as e:
            logger.debug(f"Error getting active window ID: {e}")
            return None
    
    def _get_window_name(self, win_id: Optional[int]) -> Optional[str]:
        """Get the window name/title for a given X11 window ID."""
        if not win_id:
            return None
        
        with self._window_obj(win_id) as wobj:
            if not wobj:
                return None
            
            # Try _NET_WM_NAME first (UTF-8), then WM_NAME (legacy)
            for atom in (self.NET_WM_NAME, self.WM_NAME):
                try:
                    window_name = wobj.get_full_property(atom, 0)
                except (XError, UnicodeDecodeError) as e:
                    logger.debug(f"Error getting window name property: {e}")
                    continue
                
                if window_name and window_name.value:
                    win_name = window_name.value
                    if isinstance(win_name, bytes):
                        # Handle different encodings
                        try:
                            # Try UTF-8 first
                            win_name = win_name.decode('utf-8', 'replace')
                        except (UnicodeDecodeError, AttributeError):
                            # Fallback to latin1 (like xprop does)
                            win_name = win_name.decode('latin1', 'replace')
                    return win_name
            
            return None
    
    def _get_window_class(self, win_id: Optional[int]) -> Optional[str]:
        """Get the WM_CLASS for a window (application name)."""
        if not win_id:
            return None
        
        with self._window_obj(win_id) as wobj:
            if not wobj:
                return None
            
            try:
                window_class = wobj.get_full_property(self.WM_CLASS, 0)
                if window_class and window_class.value:
                    # WM_CLASS is typically "instance_name\0class_name"
                    class_str = window_class.value
                    if isinstance(class_str, bytes):
                        class_str = class_str.decode('utf-8', 'replace')
                    # Split by null byte and take the class name (second part)
                    parts = class_str.split('\x00')
                    if len(parts) > 1:
                        return parts[1].lower()  # Class name
                    elif len(parts) == 1:
                        return parts[0].lower()  # Fallback to instance name
            except (XError, AttributeError, UnicodeDecodeError) as e:
                logger.debug(f"Error getting window class: {e}")
            
            return None
    
    def _get_window_pid(self, win_id: Optional[int]) -> Optional[int]:
        """Get the process ID (PID) for a window using _NET_WM_PID."""
        if not win_id:
            return None
        
        with self._window_obj(win_id) as wobj:
            if not wobj:
                return None
            
            try:
                pid_prop = wobj.get_full_property(self.NET_WM_PID, X.AnyPropertyType)
                if pid_prop and pid_prop.value:
                    # _NET_WM_PID is a CARDINAL (32-bit unsigned integer)
                    pid = pid_prop.value[0]
                    # Validate PID: must be positive and reasonable (not a system PID)
                    # System PIDs are typically 1-10, but we'll be conservative and allow > 1
                    # Also check if the process actually exists
                    if pid > 1:
                        try:
                            import os
                            # Check if process exists (signal 0 doesn't actually send a signal)
                            os.kill(pid, 0)
                            return pid
                        except (OSError, ProcessLookupError, PermissionError):
                            # Process doesn't exist or we can't access it
                            logger.debug(f"PID {pid} from window is invalid or inaccessible")
                            return None
                    else:
                        logger.debug(f"PID {pid} from window is likely a system process, ignoring")
                        return None
            except (XError, AttributeError, IndexError) as e:
                logger.debug(f"Error getting window PID: {e}")
            
            return None
    
    def _find_pid_by_name(self, app_name: str) -> Optional[int]:
        """
        Try to find the process ID by matching the application name.
        
        This is a fallback when _NET_WM_PID is invalid or unavailable.
        
        Args:
            app_name: Application name to search for
            
        Returns:
            Process ID if found, None otherwise
        """
        if not app_name:
            return None
        
        # Check cache first
        current_time = time.time()
        if app_name in self._pid_cache:
            cached_pid, cache_time = self._pid_cache[app_name]
            if (current_time - cache_time) < self._pid_cache_ttl:
                # Verify cached PID is still valid
                try:
                    os.kill(cached_pid, 0)
                    return cached_pid
                except (OSError, ProcessLookupError, PermissionError):
                    # Cached PID is no longer valid, remove from cache
                    del self._pid_cache[app_name]
        
        # Clean up app name for matching
        # Remove common suffixes and sanitize
        search_name = app_name.lower().replace('_', '').replace('-', '')
        
        # Extract potential executable names from reverse domain names
        # e.g., "org.vinegarhq.sober" -> "sober"
        search_terms = [app_name]
        if '.' in app_name:
            # Try the last component (usually the executable name)
            last_component = app_name.split('.')[-1]
            search_terms.append(last_component)
            # Also try without dots
            search_terms.append(app_name.replace('.', ''))
        
        # Try using pgrep first (faster and more reliable)
        for search_term in search_terms:
            try:
                result = subprocess.run(
                    ['pgrep', '-f', search_term],
                    capture_output=True,
                    timeout=1,
                    text=True
                )
                if result.returncode == 0 and result.stdout.strip():
                    pids = [int(pid) for pid in result.stdout.strip().split('\n') if pid.strip()]
                    # Return the first valid PID we can access
                    for pid in pids:
                        if pid > 1:
                            try:
                                os.kill(pid, 0)
                                # Cache the result
                                self._pid_cache[app_name] = (pid, current_time)
                                return pid
                            except (OSError, ProcessLookupError, PermissionError):
                                continue
            except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
                continue
        
        # Fallback: try searching /proc (slower but doesn't require pgrep)
        # Only do this if pgrep failed and we haven't found a PID
        try:
            for pid_str in os.listdir('/proc'):
                try:
                    pid = int(pid_str)
                    if pid <= 1:
                        continue
                    
                    # Check if we can access this process
                    try:
                        os.kill(pid, 0)
                    except (OSError, ProcessLookupError, PermissionError):
                        continue
                    
                    # Read process command line
                    try:
                        with open(f'/proc/{pid}/cmdline', 'r') as f:
                            cmdline = f.read().replace('\x00', ' ').lower()
                            # Check if app name matches
                            if search_name in cmdline or app_name.lower() in cmdline:
                                # Cache the result
                                self._pid_cache[app_name] = (pid, current_time)
                                return pid
                    except (IOError, OSError):
                        continue
                except (ValueError, OSError):
                    continue
        except (OSError, PermissionError):
            # Can't read /proc
            pass
        
        return None
    
    def get_active_window(self) -> Optional[Tuple[str, str, Optional[int]]]:
        """
        Get the currently active window information including process ID.
        
        Returns:
            Tuple of (application_name, window_title, pid) or None if unable to determine.
            pid may be None if the window doesn't have _NET_WM_PID set.
        """
        try:
            # Get active window ID
            win_id = self._get_active_window_id()
            if not win_id:
                return None
            
            # Get window title
            window_title = sanitize_string(self._get_window_name(win_id))
            if not window_title:
                return None
            
            # Try to get application class first (more reliable)
            app_name = sanitize_string(self._get_window_class(win_id))
            
            # If we couldn't get class, extract from title
            if not app_name:
                app_name = self._extract_app_name(window_title)
            
            # Get process ID
            pid = self._get_window_pid(win_id)
            
            # If PID is invalid or None, try fallback method
            if not pid and app_name:
                pid = self._find_pid_by_name(app_name)
                if pid:
                    logger.debug(f"Found PID {pid} for {app_name} using fallback method")
            
            # Cache the result
            self._last_win_id = win_id
            self._last_title = window_title
            self._last_window = app_name
            
            return (app_name, window_title, pid)
            
        except Exception as e:
            logger.debug(f"Error getting active window: {e}")
            return None
    
    def _extract_app_name(self, window_title: str) -> str:
        """
        Extract application name from window title.
        
        Args:
            window_title: Full window title
            
        Returns:
            Simplified application name
        """
        # Try to extract app name from common patterns
        title_lower = window_title.lower()
        
        # Common patterns: "App Name - Title" or "Title - App Name"
        if ' - ' in window_title:
            parts = window_title.split(' - ')
            # Usually the app name is shorter or first
            if len(parts) > 0:
                candidate = parts[0].lower().strip()
                # Remove file paths, URLs, etc.
                if not ('/' in candidate or 'http' in candidate or 'www.' in candidate):
                    return candidate
        
        # Try to get from window title by removing common patterns
        # Remove file extensions
        app_name = re.sub(r'\.[a-z]{2,4}$', '', title_lower)
        # Remove common words
        app_name = re.sub(r'\s+(file|document|window|tab)$', '', app_name)
        
        # If title is very long, take first few words
        words = app_name.split()
        if len(words) > 5:
            app_name = ' '.join(words[:3])
        
        return app_name.strip() if app_name.strip() else title_lower[:20]
    
    def close(self):
        """Close the X11 display connection."""
        if hasattr(self, 'disp'):
            try:
                self.disp.close()
            except:
                pass
