"""
Configuration Manager - Handles loading and validation of configuration.

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
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time, timedelta
import logging

logger = logging.getLogger(__name__)

# Import default config path
_CONFIG_DIR = Path(__file__).parent.parent / "config"


class ConfigManager:
    """Manages application configuration."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_path: Path to configuration file. If None, uses default location.
        """
        if config_path is None:
            config_path = os.path.expanduser("~/.screentime/config.json")
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._validate_config()
    
    def reload_config(self):
        """Reload configuration from file."""
        logger.info(f"Reloading configuration from {self.config_path}")
        self.config = self._load_config()
        self._validate_config()
    
    def _load_config(self) -> Dict:
        """Load configuration from file or create default."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                logger.info(f"Loaded configuration from {self.config_path}")
                return config
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing config file: {e}")
                logger.info("Using default configuration")
                return self._get_default_config()
        else:
            logger.info(f"Config file not found at {self.config_path}, using defaults")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict:
        """Get default configuration."""
        default_path = _CONFIG_DIR / "default_config.json"
        if default_path.exists():
            try:
                with open(default_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load default config: {e}")
        
        # Fallback to hardcoded defaults
        return {
            "allowlist": [],
            "denylist": [],
            "daily_limit": 7200,
            "weekday_limits": {
                "monday": 7200,
                "tuesday": 7200,
                "wednesday": 7200,
                "thursday": 7200,
                "friday": 7200,
                "saturday": 10800,
                "sunday": 10800
            },
            "rest_times": {
                day: {
                    "morning": {"start": "00:00", "end": "08:00"},
                    "evening": {"start": "21:00", "end": "23:59"}
                }
                for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            },
            "holiday_seasons": [],
            "tracking_interval": 1,
            "data_directory": "~/.screentime"
        }
    
    def _validate_config(self):
        """Validate configuration structure."""
        required_keys = ["allowlist", "denylist", "daily_limit", "weekday_limits", "rest_times"]
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required configuration key: {key}")
        
        # Validate weekday limits
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for day in weekdays:
            if day not in self.config["weekday_limits"]:
                logger.warning(f"Missing weekday limit for {day}, using default")
                self.config["weekday_limits"][day] = self.config["daily_limit"]
            
            if day not in self.config["rest_times"]:
                logger.warning(f"Missing rest times for {day}, using default")
                self.config["rest_times"][day] = {
                    "morning": {"start": "00:00", "end": "08:00"},
                    "evening": {"start": "21:00", "end": "23:59"}
                }
    
    def _matches_list(self, app_name: str, list_name: str) -> bool:
        """
        Check if application matches any entry in the specified list using regex matching.
        
        Args:
            app_name: Application name to check (will be escaped to prevent regex injection)
            list_name: Name of the list to check ('allowlist' or 'denylist')
            
        Returns:
            True if the application matches any entry in the list, False otherwise
        """
        # Escape the app_name to prevent regex injection from malicious window titles
        app_lower = re.escape(app_name.lower())
        list_entries = self.config.get(list_name, [])
        
        for entry in list_entries:
            # Use the config entry as a regex pattern (allows regex in config)
            # Search the escaped app_name against this pattern
            pattern = entry.lower()
            try:
                if re.search(pattern, app_lower):
                    return True
            except re.error as e:
                logger.warning(f"Invalid regex pattern for {list_name} entry '{entry}': {e}")
        return False
    
    def is_allowlisted(self, app_name: str) -> bool:
        """Check if application is allowlisted using regex matching."""
        return self._matches_list(app_name, "allowlist")
    
    def is_denylisted(self, app_name: str) -> bool:
        """Check if application is denylisted using regex matching."""
        return self._matches_list(app_name, "denylist")
    
    # Backward compatibility aliases
    def is_whitelisted(self, app_name: str) -> bool:
        """Check if application is allowlisted (backward compatibility alias)."""
        return self.is_allowlisted(app_name)
    
    def is_blacklisted(self, app_name: str) -> bool:
        """Check if application is denylisted (backward compatibility alias)."""
        return self.is_denylisted(app_name)
    
    def get_daily_limit(self, weekday: Optional[str] = None) -> int:
        """Get daily limit in seconds for given weekday."""
        if weekday is None:
            weekday = datetime.now().strftime("%A").lower()
        
        return self.config["weekday_limits"].get(weekday, self.config["daily_limit"])
    
    def get_rest_times(self, weekday: Optional[str] = None) -> Dict:
        """Get rest times for given weekday."""
        if weekday is None:
            weekday = datetime.now().strftime("%A").lower()
        
        return self.config["rest_times"].get(weekday, {
            "morning": {"start": "00:00", "end": "08:00"},
            "evening": {"start": "21:00", "end": "23:59"}
        })
    
    def is_rest_time(self, current_time: Optional[time] = None) -> bool:
        """Check if current time is within rest period."""
        if current_time is None:
            current_time = datetime.now().time()
        
        weekday = datetime.now().strftime("%A").lower()
        rest_times = self.get_rest_times(weekday)
        
        # Check if in holiday season (extended rest times)
        holiday_rest = self._get_holiday_rest_times()
        if holiday_rest:
            rest_times = holiday_rest
        
        # Check morning rest time
        morning_start = self._parse_time(rest_times["morning"]["start"])
        morning_end = self._parse_time(rest_times["morning"]["end"])
        
        if morning_start <= morning_end:
            if morning_start <= current_time <= morning_end:
                return True
        else:  # Spans midnight
            if current_time >= morning_start or current_time <= morning_end:
                return True
        
        # Check evening rest time
        evening_start = self._parse_time(rest_times["evening"]["start"])
        evening_end = self._parse_time(rest_times["evening"]["end"])
        
        if evening_start <= evening_end:
            if evening_start <= current_time <= evening_end:
                return True
        else:  # Spans midnight
            if current_time >= evening_start or current_time <= evening_end:
                return True
        
        return False
    
    def _get_holiday_rest_times(self) -> Optional[Dict]:
        """Get extended rest times if currently in holiday season."""
        today = datetime.now().date()
        
        for holiday in self.config.get("holiday_seasons", []):
            try:
                start_date = datetime.strptime(holiday["start_date"], "%Y-%m-%d").date()
                end_date = datetime.strptime(holiday["end_date"], "%Y-%m-%d").date()
                
                if start_date <= today <= end_date:
                    return {
                        "morning": holiday.get("extended_rest_morning", {
                            "start": "00:00", "end": "08:00"
                        }),
                        "evening": holiday.get("extended_rest_evening", {
                            "start": "21:00", "end": "23:59"
                        })
                    }
            except (KeyError, ValueError) as e:
                logger.warning(f"Invalid holiday season config: {e}")
                continue
        
        return None
    
    def get_holiday_limit_multiplier(self) -> float:
        """Get limit multiplier if in holiday season."""
        today = datetime.now().date()
        
        for holiday in self.config.get("holiday_seasons", []):
            try:
                start_date = datetime.strptime(holiday["start_date"], "%Y-%m-%d").date()
                end_date = datetime.strptime(holiday["end_date"], "%Y-%m-%d").date()
                
                if start_date <= today <= end_date:
                    return holiday.get("extended_limit_multiplier", 1.0)
            except (KeyError, ValueError) as e:
                logger.warning(f"Invalid holiday season config: {e}")
                continue
        
        return 1.0
    
    def _parse_time(self, time_str: str) -> time:
        """Parse time string (HH:MM) to time object."""
        try:
            hour, minute = map(int, time_str.split(":"))
            return time(hour, minute)
        except ValueError:
            logger.error(f"Invalid time format: {time_str}")
            return time(0, 0)
    
    def get_tracking_interval(self) -> int:
        """Get tracking interval in seconds."""
        return self.config.get("tracking_interval", 1)
    
    def get_data_directory(self) -> Path:
        """Get data directory path."""
        data_dir = os.path.expanduser(self.config.get("data_directory", "~/.screentime"))
        return Path(data_dir)
    
    def get_next_rest_time_start(self) -> Optional[datetime]:
        """
        Get the datetime when the next rest time period starts.
        
        Returns:
            datetime object for next rest time start, or None if no rest time today
        """
        now = datetime.now()
        weekday = now.strftime("%A").lower()
        rest_times = self.get_rest_times(weekday)
        
        # Check if in holiday season (extended rest times)
        holiday_rest = self._get_holiday_rest_times()
        if holiday_rest:
            rest_times = holiday_rest
        
        morning_start = self._parse_time(rest_times["morning"]["start"])
        evening_start = self._parse_time(rest_times["evening"]["start"])
        
        # Create datetime objects for today
        today = now.date()
        morning_dt = datetime.combine(today, morning_start)
        evening_dt = datetime.combine(today, evening_start)
        
        # If morning start is before now, it's tomorrow
        if morning_dt <= now:
            morning_dt += timedelta(days=1)
        
        # If evening start is before now, it's tomorrow
        if evening_dt <= now:
            evening_dt += timedelta(days=1)
        
        # Return the earlier of the two
        if morning_dt < evening_dt:
            return morning_dt
        else:
            return evening_dt
    
    def is_rest_time_approaching(self, minutes_before: int = 15) -> Tuple[bool, Optional[datetime]]:
        """
        Check if rest time is approaching within the specified minutes.
        
        Args:
            minutes_before: Number of minutes before rest time to trigger warning
            
        Returns:
            Tuple of (is_approaching: bool, rest_time_start: Optional[datetime])
        """
        next_rest_start = self.get_next_rest_time_start()
        if next_rest_start is None:
            return (False, None)
        
        now = datetime.now()
        time_until_rest = (next_rest_start - now).total_seconds() / 60  # minutes
        
        # Check if we're within the warning window
        if 0 <= time_until_rest <= minutes_before:
            return (True, next_rest_start)
        
        return (False, next_rest_start)
    
    def calculate_rest_time_duration(self, rest_times: Optional[Dict] = None) -> int:
        """
        Calculate total rest time duration in seconds for a given rest_times dict.
        
        Args:
            rest_times: Rest times dict with morning/evening start/end. If None, uses current weekday.
            
        Returns:
            Total rest time duration in seconds
        """
        if rest_times is None:
            weekday = datetime.now().strftime("%A").lower()
            rest_times = self.get_rest_times(weekday)
            # Check if in holiday season
            holiday_rest = self._get_holiday_rest_times()
            if holiday_rest:
                rest_times = holiday_rest
        
        def time_duration_seconds(start_str: str, end_str: str) -> int:
            """Calculate duration between two time strings in seconds."""
            start_time = self._parse_time(start_str)
            end_time = self._parse_time(end_str)
            
            # Convert to datetime for today to calculate difference
            today = datetime.now().date()
            start_dt = datetime.combine(today, start_time)
            end_dt = datetime.combine(today, end_time)
            
            # Handle case where end is before start (spans midnight)
            if end_dt < start_dt:
                end_dt += timedelta(days=1)
            
            return int((end_dt - start_dt).total_seconds())
        
        morning_duration = time_duration_seconds(
            rest_times["morning"]["start"],
            rest_times["morning"]["end"]
        )
        evening_duration = time_duration_seconds(
            rest_times["evening"]["start"],
            rest_times["evening"]["end"]
        )
        
        return morning_duration + evening_duration

