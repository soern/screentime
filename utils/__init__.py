"""
Utility functions for screen time tracker.

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
from utils.strings import sanitize_string
from utils.system import drop_privileges, configure_user_environment
from utils.ipc import (
    SocketServer,
    get_socket_path,
    send_socket_command,
    query_socket_logs,
)

__all__ = [
    'sanitize_string',
    'drop_privileges',
    'configure_user_environment',
    'SocketServer',
    'get_socket_path',
    'send_socket_command',
    'query_socket_logs',
]

