"""
Inter-Process Communication (IPC) via Unix sockets.

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
import socket
import threading
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from collections import deque

logger = logging.getLogger(__name__)


def get_socket_path(data_directory: Path) -> Path:
    """Get path to Unix socket file."""
    return data_directory / "screentime.sock"


class SocketServer:
    """Unix socket server for IPC."""
    
    def __init__(self, data_directory: Path, log_buffer: deque, tracker_instance=None, reload_flag=None):
        """
        Initialize socket server.
        
        Args:
            data_directory: Directory for socket file
            log_buffer: Log buffer to query
            tracker_instance: Optional tracker instance for commands
            reload_flag: Optional reload flag event
        """
        self.data_directory = data_directory
        self.socket_path = get_socket_path(data_directory)
        self.log_buffer = log_buffer
        self.tracker_instance = tracker_instance
        self.reload_flag = reload_flag
        self.server = None
        self.thread = None
        self.running = False
    
    def _handle_connection(self, sock: socket.socket, addr):
        """Handle client connection to socket server."""
        try:
            # Receive command from client
            data = sock.recv(1024).decode('utf-8')
            if not data:
                return
            
            try:
                command = json.loads(data)
            except json.JSONDecodeError:
                # Try plain text command
                command = {"cmd": data.strip()}
            
            cmd = command.get("cmd", "").lower()
            response = self._process_command(cmd, command)
            
            # Send response
            response_json = json.dumps(response)
            sock.sendall(response_json.encode('utf-8'))
            
        except Exception as e:
            logger.error(f"Error handling socket connection: {e}")
            try:
                error_response = json.dumps({
                    "status": "error",
                    "message": str(e)
                })
                sock.sendall(error_response.encode('utf-8'))
            except:
                pass
        finally:
            sock.close()
    
    def _process_command(self, cmd: str, command: Dict[str, Any]) -> Dict[str, Any]:
        """Process a command and return response."""
        if cmd == "logs" or cmd == "get_logs":
            # Get number of lines requested
            lines = command.get("lines", 100)
            if lines <= 0:
                lines = len(self.log_buffer)
            
            # Get log entries
            recent_logs = list(self.log_buffer)[-lines:]
            return {
                "status": "ok",
                "lines": len(recent_logs),
                "total": len(self.log_buffer),
                "logs": recent_logs
            }
        elif cmd == "stats" or cmd == "get_stats":
            # This would require access to tracker instance
            # For now, return buffer stats
            return {
                "status": "ok",
                "buffer_size": len(self.log_buffer),
                "buffer_max": self.log_buffer.maxlen
            }
        elif cmd == "reload" or cmd == "reload_config":
            # Trigger config reload
            if self.tracker_instance and self.reload_flag:
                self.reload_flag.set()
                return {
                    "status": "ok",
                    "message": "Configuration reload requested"
                }
            else:
                return {
                    "status": "error",
                    "message": "Tracker instance not available"
                }
        elif cmd == "terminate" or cmd == "stop" or cmd == "shutdown":
            # Trigger shutdown
            if self.tracker_instance:
                self.tracker_instance.running = False
                return {
                    "status": "ok",
                    "message": "Shutdown requested"
                }
            else:
                return {
                    "status": "error",
                    "message": "Tracker instance not available"
                }
        else:
            return {
                "status": "error",
                "message": f"Unknown command: {cmd}"
            }
    
    def start(self):
        """Start the socket server."""
        # Remove existing socket file if it exists
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except Exception as e:
                logger.warning(f"Could not remove existing socket: {e}")
        
        try:
            # Create Unix socket
            self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server.bind(str(self.socket_path))
            self.server.listen(5)
            
            # Set socket permissions (readable/writable by user)
            os.chmod(self.socket_path, 0o600)
            
            logger.info(f"Socket server started at {self.socket_path}")
            self.running = True
            
            def server_loop():
                """Server loop to accept connections."""
                while self.running and self.server:
                    try:
                        # Set timeout to allow periodic checking if socket is still valid
                        self.server.settimeout(1.0)
                        conn, addr = self.server.accept()
                        # Handle each connection
                        self._handle_connection(conn, addr)
                    except socket.timeout:
                        # Timeout is expected, continue loop
                        continue
                    except OSError:
                        # Socket closed
                        break
                    except Exception as e:
                        logger.error(f"Error in socket server: {e}")
            
            self.thread = threading.Thread(target=server_loop, daemon=True)
            self.thread.start()
            
        except Exception as e:
            logger.error(f"Failed to start socket server: {e}")
            self.server = None
    
    def stop(self):
        """Stop the socket server."""
        self.running = False
        
        if self.server:
            try:
                self.server.close()
                # Clean up socket file
                if self.socket_path.exists():
                    try:
                        self.socket_path.unlink()
                    except:
                        pass
                self.server = None
            except Exception as e:
                logger.error(f"Error closing socket server: {e}")
        
        self.thread = None
    
    def update_tracker_instance(self, tracker_instance):
        """Update the tracker instance reference."""
        self.tracker_instance = tracker_instance
    
    def update_reload_flag(self, reload_flag):
        """Update the reload flag reference."""
        self.reload_flag = reload_flag


def send_socket_command(socket_path: Path, command: str, **kwargs) -> dict:
    """
    Send a command to the daemon via Unix socket.
    
    Args:
        socket_path: Path to Unix socket
        command: Command to send (e.g., "reload", "terminate", "logs")
        **kwargs: Additional parameters for the command
        
    Returns:
        Response dictionary from daemon
    """
    if not socket_path.exists():
        return {
            "status": "error",
            "message": f"Socket not found at {socket_path}. Is daemon running?"
        }
    
    try:
        # Connect to socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(socket_path))
        
        # Send command
        cmd_data = {"cmd": command, **kwargs}
        command_json = json.dumps(cmd_data)
        sock.sendall(command_json.encode('utf-8'))
        
        # Receive response
        response_data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
        
        sock.close()
        
        # Parse response
        response = json.loads(response_data.decode('utf-8'))
        return response
            
    except FileNotFoundError:
        return {
            "status": "error",
            "message": f"Socket not found at {socket_path}. Is daemon running?"
        }
    except ConnectionRefusedError:
        return {
            "status": "error",
            "message": "Connection refused. Is daemon running?"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error sending command: {e}"
        }


def query_socket_logs(socket_path: Path, lines: int = 100) -> list:
    """
    Query log buffer from daemon via Unix socket.
    
    Args:
        socket_path: Path to Unix socket
        lines: Number of log lines to retrieve
        
    Returns:
        List of log entries, or empty list if query failed
    """
    response = send_socket_command(socket_path, "logs", lines=lines)
    
    if response.get("status") == "ok":
        return response.get("logs", [])
    else:
        # Don't print error here - let caller handle it
        # The error message is already in the response
        return []

