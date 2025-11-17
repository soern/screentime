"""
String utility functions.

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


def sanitize_string(text: str) -> str:
    """
    Sanitize a string by replacing all non-alphanumeric characters by underscores _.
    
    Args:
        text: String to sanitize
        
    Returns:
        Sanitized string
    """
    if not text:
        return ""
    
    return re.sub(r'[^-+:,;._ a-zA-Z0-9]', '_', text)

