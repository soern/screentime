"""
System utility functions.

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
import sys
import pwd
import grp
import logging

logger = logging.getLogger(__name__)


def _get_user_info(username: str):
    """Fetch passwd entry for given user."""
    try:
        return pwd.getpwnam(username)
    except KeyError as exc:
        raise ValueError(f"User '{username}' not found") from exc


def configure_user_environment(username: str, user_info=None, change_directory: bool = False):
    """
    Configure process environment variables for the target user.
    
    Args:
        username: Target username
        user_info: Optional pwd struct for the user
        change_directory: Whether to chdir into the user's home
        
    Returns:
        pwd.struct_passwd for the target user
    """
    if user_info is None:
        user_info = _get_user_info(username)
    
    os.environ['HOME'] = user_info.pw_dir
    os.environ['USER'] = username
    os.environ['LOGNAME'] = username
    
    # Set XDG_RUNTIME_DIR if not already set and runtime directory exists
    if 'XDG_RUNTIME_DIR' not in os.environ:
        runtime_dir = f"/run/user/{user_info.pw_uid}"
        if os.path.exists(runtime_dir):
            os.environ['XDG_RUNTIME_DIR'] = runtime_dir
    
    # Set DBUS_SESSION_BUS_ADDRESS for the target user
    # Always update it to ensure we use the correct user's bus (not root's)
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR', f"/run/user/{user_info.pw_uid}")
    bus_socket = f"{runtime_dir}/bus"
    if os.path.exists(bus_socket):
        os.environ['DBUS_SESSION_BUS_ADDRESS'] = f"unix:path={bus_socket}"
    elif 'DBUS_SESSION_BUS_ADDRESS' in os.environ:
        # If the bus socket doesn't exist but DBUS_SESSION_BUS_ADDRESS is set to root's bus,
        # clear it to force re-detection
        current_bus = os.environ.get('DBUS_SESSION_BUS_ADDRESS', '')
        if '/run/user/0/bus' in current_bus and user_info.pw_uid != 0:
            del os.environ['DBUS_SESSION_BUS_ADDRESS']
    
    if change_directory:
        try:
            os.chdir(user_info.pw_dir)
        except OSError:
            os.chdir('/')
    
    return user_info


def drop_privileges(username: str):
    """
    Drop privileges to the specified user.
    
    Args:
        username: Username to switch to
        
    Raises:
        ValueError: If user doesn't exist or insufficient privileges
        PermissionError: If unable to change user/group
    """
    try:
        # Get user info and prime environment variables
        user_info = configure_user_environment(username)
        user_uid = user_info.pw_uid
        user_gid = user_info.pw_gid
        
        # Get current user
        current_uid = os.getuid()
        
        # Check if we have privileges to change user (root or same user)
        if current_uid != 0 and current_uid != user_uid:
            raise PermissionError(f"Must be root to change to user '{username}'")
        
        # If already running as the target user, just ensure environment is correct
        if current_uid == user_uid:
            configure_user_environment(username, user_info=user_info, change_directory=True)
            print(f"Already running as user '{username}'", file=sys.stderr)
            return
        
        # Get user's primary group
        group_info = grp.getgrgid(user_gid)
        
        # Set group ID first (must be done before setuid if not root)
        try:
            os.setgid(user_gid)
        except OSError as e:
            raise PermissionError(f"Failed to set group ID to {user_gid} ({group_info.gr_name}): {e}")
        
        # Set user ID
        try:
            os.setuid(user_uid)
        except OSError as e:
            raise PermissionError(f"Failed to set user ID to {user_uid} ({username}): {e}")
        
        # Refresh environment after privilege drop
        configure_user_environment(username, user_info=user_info, change_directory=True)
        
        print(f"Dropped privileges to user '{username}' (UID: {user_uid}, GID: {user_gid})", file=sys.stderr)
        
    except Exception as e:
        if isinstance(e, (PermissionError, ValueError)):
            raise
        raise ValueError(f"Error dropping privileges to user '{username}': {e}") from e

