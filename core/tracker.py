"""
Time Tracker - Tracks application usage time and enforces limits.

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
import time as time_module
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, Optional, Tuple
import logging
import threading

logger = logging.getLogger(__name__)


class TimeTracker:
    """Tracks application usage time."""
    
    def __init__(self, data_directory: Path, config_manager):
        """
        Initialize time tracker.
        
        Args:
            data_directory: Directory to store tracking data
            config_manager: ConfigManager instance
        """
        self.data_directory = Path(data_directory)
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self.config = config_manager
        self.current_app = None
        self.current_start_time = None
        self.last_progress_time = None
        self.today_data = self._load_today_data()
        self.history = self._load_history()
        self.history_lock = threading.Lock()
        self.last_data_save = time_module.time()
        self.data_save_interval = 30  # Save data file at most every 30 seconds
        # Suspend detection: track last check time
        self.last_suspend_check_time = time_module.time()
    
    def _get_data_file_path(self, target_date: Optional[date] = None) -> Path:
        """Get path to data file for given date."""
        if target_date is None:
            target_date = date.today()
        
        filename = f"usage_{target_date.strftime('%Y-%m-%d')}.json"
        return self.data_directory / filename
    
    def _normalize_today_data(self, data: Dict) -> Dict:
        """
        Normalize today's data structure, ensuring all required keys exist.
        Also handles migration from old format.
        
        Args:
            data: Raw data dictionary loaded from file
            
        Returns:
            Normalized data dictionary with all required keys
        """
        normalized = {
            "date": data.get("date", date.today().isoformat()),
            "denylisted_usage": {},
            "allowlisted_usage": {},
            "total_denylisted": 0,
            "sessions": []
        }
        
        # Migrate from old format (blacklisted -> denylisted, whitelisted -> allowlisted)
        if "blacklisted_usage" in data and "denylisted_usage" not in data:
            normalized["denylisted_usage"] = data.get("blacklisted_usage", {})
        else:
            normalized["denylisted_usage"] = data.get("denylisted_usage", {})
        
        if "whitelisted_usage" in data and "allowlisted_usage" not in data:
            normalized["allowlisted_usage"] = data.get("whitelisted_usage", {})
        else:
            normalized["allowlisted_usage"] = data.get("allowlisted_usage", {})
        
        # Migrate total_denylisted_seconds -> total_denylisted
        if "total_denylisted_seconds" in data and "total_denylisted" not in data:
            normalized["total_denylisted"] = data.get("total_denylisted_seconds", 0)
        else:
            normalized["total_denylisted"] = data.get("total_denylisted", 0)
        
        # Migrate duration_seconds -> duration in sessions
        if "sessions" in data:
            normalized["sessions"] = []
            for session in data["sessions"]:
                normalized_session = session.copy()
                # Migrate duration_seconds to duration if needed
                if "duration_seconds" in normalized_session and "duration" not in normalized_session:
                    normalized_session["duration"] = normalized_session.pop("duration_seconds")
                normalized["sessions"].append(normalized_session)
        else:
            normalized["sessions"] = data.get("sessions", [])
        
        # Ensure all values are the correct type
        if not isinstance(normalized["denylisted_usage"], dict):
            normalized["denylisted_usage"] = {}
        if not isinstance(normalized["allowlisted_usage"], dict):
            normalized["allowlisted_usage"] = {}
        if not isinstance(normalized["total_denylisted"], (int, float)):
            normalized["total_denylisted"] = 0
        if not isinstance(normalized["sessions"], list):
            normalized["sessions"] = []
        
        # Preserve rest_time_modification if it exists
        if "rest_time_modification" in data:
            normalized["rest_time_modification"] = data["rest_time_modification"]
        
        # Preserve temporary_denylisted_usage if it exists
        if "temporary_denylisted_usage" in data:
            normalized["temporary_denylisted_usage"] = data["temporary_denylisted_usage"]
        
        return normalized
    
    def _load_today_data(self, target_date: Optional[date] = None) -> Dict:
        """Load usage data for the specified date (defaults to today)."""
        if target_date is None:
            target_date = date.today()
        target_date_str = target_date.isoformat()
        data_file = self._get_data_file_path(target_date)
        
        if data_file.exists():
            try:
                with open(data_file, 'r') as f:
                    raw_data = json.load(f)
                    normalized = self._normalize_today_data(raw_data)
                    stored_date = normalized.get("date")
                    if stored_date != target_date_str:
                        logger.warning(
                            "Data file %s reports date %s instead of %s. "
                            "Creating fresh usage data for the target day.",
                            data_file,
                            stored_date,
                            target_date_str,
                        )
                        return {
                            "date": target_date_str,
                            "denylisted_usage": {},
                            "allowlisted_usage": {},
                            "total_denylisted": 0,
                            "sessions": [],
                        }
                    normalized["date"] = target_date_str
                    return normalized
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Error loading data file {data_file}: {e}")
        
        return {
            "date": target_date_str,
            "denylisted_usage": {},
            "allowlisted_usage": {},
            "total_denylisted": 0,
            "sessions": [],
        }
    
    def _save_today_data(self, force: bool = False):
        """
        Save today's usage data.
        
        Args:
            force: If True, save immediately. If False, only save if enough time has passed.
        """
        current_time = time_module.time()
        
        # Throttle saves - only save if enough time has passed or forced
        if not force and (current_time - self.last_data_save) < self.data_save_interval:
            return
        
        data_date_str = self.today_data.get("date")
        target_date = None
        if data_date_str:
            try:
                target_date = datetime.fromisoformat(data_date_str).date()
            except ValueError:
                logger.warning("Invalid date format '%s' in today_data; resetting to today.", data_date_str)
                target_date = date.today()
                self.today_data["date"] = target_date.isoformat()
        else:
            target_date = date.today()
            self.today_data["date"] = target_date.isoformat()
        
        data_file = self._get_data_file_path(target_date)
        
        try:
            # Save to temporary file first, then rename (atomic operation)
            temp_file = data_file.with_suffix('.tmp')
            logger.debug(f"Saving to temp file: {temp_file}")
            with open(temp_file, 'w') as f:
                json.dump(self.today_data, f, indent=2)
            logger.debug(f"Renaming temp file to: {data_file}")
            # Atomic rename
            temp_file.replace(data_file)
            logger.debug("Today's data file saved successfully")
            self.last_data_save = current_time
        except IOError as e:
            logger.error(f"Error saving data file: {e}")
        except Exception as e:
            logger.error(f"Unexpected error saving data file: {e}", exc_info=True)
        
        # Update history (without lock - will be locked by save_history if needed)
        # Don't update history here to avoid lock contention
    
    def _ensure_today_data_keys(self):
        """Ensure today_data has required keys."""
        if "sessions" not in self.today_data:
            self.today_data["sessions"] = []
        if "denylisted_usage" not in self.today_data:
            self.today_data["denylisted_usage"] = {}
        if "allowlisted_usage" not in self.today_data:
            self.today_data["allowlisted_usage"] = {}
        if "total_denylisted" not in self.today_data:
            self.today_data["total_denylisted"] = 0

    def _increment_usage(self, app_name: str, duration: float):
        """Increment usage counters for the current app."""
        if duration <= 0 or not app_name:
            return

        self._ensure_today_data_keys()

        if self.config.is_denylisted(app_name):
            self.today_data["denylisted_usage"].setdefault(app_name, 0)
            self.today_data["denylisted_usage"][app_name] += duration
            self.today_data["total_denylisted"] += duration
        else:
            # Apps not in denylist (allowlisted or unknown) count as allowlisted_usage
            self.today_data["allowlisted_usage"].setdefault(app_name, 0)
            self.today_data["allowlisted_usage"][app_name] += duration

    def check_suspend(self) -> bool:
        """
        Check if computer was suspended by comparing time delta.
        Should be called every 10 seconds.
        
        Returns:
            True if suspend was detected, False otherwise
        """
        now = time_module.time()
        elapsed = now - self.last_suspend_check_time
        
        # If more than 1 minute has passed, computer was likely suspended
        SUSPEND_THRESHOLD = 60  # 1 minute in seconds
        
        if elapsed > SUSPEND_THRESHOLD:
            logger.info(
                f"Suspend detected: {elapsed:.1f}s gap since last check. "
                f"Time during suspend will not be counted as usage."
            )
            # Update last_progress_time to now to skip counting the suspended time
            if self.last_progress_time is not None:
                self.last_progress_time = now
            # Update suspend check time
            self.last_suspend_check_time = now
            return True
        
        # Update suspend check time
        self.last_suspend_check_time = now
        return False
    
    def _record_progress(self, force: bool = False):
        """
        Record elapsed time for the current session without ending it.
        Detects computer suspension and skips counting time during suspend.
        """
        if self.current_app is None or self.current_start_time is None:
            return

        now = time_module.time()
        if self.last_progress_time is None:
            self.last_progress_time = self.current_start_time

        elapsed = now - self.last_progress_time
        if elapsed <= 0 and not force:
            return

        # Detect suspend: if elapsed time is greater than 1 minute, computer was likely suspended
        # Don't count that time as usage
        SUSPEND_THRESHOLD = 60  # 1 minute in seconds
        
        if elapsed > SUSPEND_THRESHOLD:
            # Computer was likely suspended - skip counting this time
            logger.info(
                f"Suspend detected in progress recording: {elapsed:.1f}s gap detected. "
                f"Skipping {elapsed:.1f}s of time (not counting as usage)."
            )
            # Update last_progress_time to now to avoid accumulating the gap
            self.last_progress_time = now
            # Don't increment usage or save data for this gap
            return

        if elapsed > 0:
            self._increment_usage(self.current_app, elapsed)
            self.last_progress_time = now
            self._save_today_data()
        elif force:
            # Ensure timestamp advances even if elapsed is extremely small/zero
            self.last_progress_time = now

    def _check_new_day(self) -> bool:
        """
        Check if the date has changed and roll over today's data if needed.
        
        Returns:
            True if the day was reset, False otherwise
        """
        current_date = self.today_data.get("date")
        today_str = date.today().isoformat()
        
        if current_date == today_str:
            return False
        
        logger.info(f"New day detected (previous data date: {current_date}, current date: {today_str}). Rolling over usage data.")
        
        # End current session to record final usage for previous day
        if self.current_app is not None:
            try:
                self._end_current_session()
            except Exception as e:
                logger.error(f"Error ending session during day rollover: {e}", exc_info=True)
        
        # Ensure today's data is saved and history updated
        try:
            self._save_today_data(force=True)
        except Exception as e:
            logger.error(f"Error saving daily data during day rollover: {e}", exc_info=True)
        
        try:
            self.save_history()
        except Exception as e:
            logger.error(f"Error saving history during day rollover: {e}", exc_info=True)
        
        # Load fresh data for the new day
        self.today_data = self._load_today_data()
        self.current_app = None
        self.current_start_time = None
        self.last_progress_time = None
        
        return True
    
    def start_tracking(self, app_name: str, window_title: str):
        """
        Start tracking an application.
        
        Args:
            app_name: Application name
            window_title: Full window title
        """
        # Ensure we are tracking the correct day
        self._check_new_day()
        
        # If switching apps, record previous session
        if self.current_app is not None and self.current_app != app_name:
            self._end_current_session()
        
        self.current_app = app_name
        self.current_start_time = time_module.time()
        self.last_progress_time = self.current_start_time
    
    def _end_current_session(self):
        """End current tracking session and record it."""
        if self.current_app is None or self.current_start_time is None:
            return
        
        # Capture any remaining progress before ending session
        self._record_progress(force=True)

        duration = time_module.time() - self.current_start_time
        ended_app = self.current_app  # Store before clearing
        
        # Ensure required keys exist (defensive programming)
        self._ensure_today_data_keys()
        
        # Record session
        session = {
            "app": ended_app,
            "start": datetime.fromtimestamp(self.current_start_time).isoformat(),
            "end": datetime.now().isoformat(),
            "duration": duration
        }
        self.today_data["sessions"].append(session)
        
        # Clear current session before saving (to avoid double-counting in history)
        self.current_app = None
        self.current_start_time = None
        self.last_progress_time = None
        
        self._save_today_data()
    
    def update(self, app_name: str, window_title: str):
        """
        Update tracking with current application.
        
        Args:
            app_name: Application name
            window_title: Full window title
        """
        # Check for day rollover before recording progress
        day_reset = self._check_new_day()
        
        # Record progress for the currently active session
        self._record_progress()
        
        # Continue tracking - rest time only affects whether usage counts towards limit,
        # not whether we track it
        if day_reset or self.current_app is None or app_name != self.current_app:
            self.start_tracking(app_name, window_title)
    
    def get_current_usage(self) -> Tuple[int, int]:
        """
        Get current usage statistics.
        
        Returns:
            Tuple of (denylisted, allowlisted) in seconds
        """
        # Always calculate actual usage (temporary usage acts as a limit, not usage override)
        denylisted = self.today_data.get("total_denylisted", 0)
        
        # Add current session if tracking (only the portion since last progress)
        if self.current_app and self.current_start_time:
            reference_time = self.last_progress_time or self.current_start_time
            current_duration = max(0, time_module.time() - reference_time)
            if self.config.is_denylisted(self.current_app):
                # Denylisted: always count (even during rest time)
                denylisted += current_duration
            elif not self.config.is_allowlisted(self.current_app):
                # Unknown apps: only count if not in rest time
                if not self.config.is_rest_time():
                    denylisted += current_duration
        
        allowlisted = sum(self.today_data.get("allowlisted_usage", {}).values())
        
        # Add current session if tracking allowlisted
        if self.current_app and self.current_start_time:
            if self.config.is_allowlisted(self.current_app):
                reference_time = self.last_progress_time or self.current_start_time
                current_duration = max(0, time_module.time() - reference_time)
                allowlisted += current_duration
        
        return (int(denylisted), int(allowlisted))
    
    def get_remaining_time(self) -> int:
        """Get remaining time in seconds for denylisted apps."""
        limit = self.get_adjusted_daily_limit()
        current_usage, _ = self.get_current_usage()
        remaining = max(0, limit - current_usage)
        
        return remaining
    
    def get_adjusted_daily_limit(self) -> int:
        """
        Get the daily limit adjusted for rest time modifications, holiday multiplier,
        and temporary usage settings.
        
        Returns:
            Adjusted daily limit in seconds
        """
        weekday = datetime.now().strftime("%A").lower()
        limit = self.config.get_daily_limit(weekday)
        
        # Apply holiday multiplier
        multiplier = self.config.get_holiday_limit_multiplier()
        limit = int(limit * multiplier)
        
        # Apply rest time modification if it exists
        if "rest_time_modification" in self.today_data:
            modification = self.today_data["rest_time_modification"]
            if "adjusted_limit" in modification:
                limit = modification["adjusted_limit"]
        
        # Apply temporary usage adjustment (add or subtract from limit)
        if "temporary_denylisted_usage" in self.today_data:
            temporary_adjustment = self.today_data["temporary_denylisted_usage"]
            limit = max(0, limit + temporary_adjustment)  # Ensure limit doesn't go negative
        
        return limit
    
    def modify_rest_time(self, morning_end: Optional[str] = None,
                        evening_start: Optional[str] = None) -> Dict:
        """
        Modify rest time for the current day and adjust daily limit accordingly.
        Can only be called once per day.
        
        Evening rest time continues uninterrupted until morning_end.
        
        Args:
            morning_end: New morning rest time end (HH:MM format), None to keep current
            evening_start: New evening rest time start (HH:MM format), None to keep current
            
        Returns:
            Dict with status, message, and details about the modification
        """
        # Check if rest time has already been modified today
        if "rest_time_modification" in self.today_data:
            return {
                "status": "error",
                "message": "Rest time has already been modified for today. Only one modification per day is allowed."
            }
        
        # Get current rest times
        weekday = datetime.now().strftime("%A").lower()
        current_rest_times = self.config.get_rest_times(weekday)
        
        # Check if in holiday season
        holiday_rest = self.config._get_holiday_rest_times()
        if holiday_rest:
            current_rest_times = holiday_rest
        
        # Calculate original rest time duration
        original_duration = self.config.calculate_rest_time_duration(current_rest_times)
        
        # Determine new values
        new_evening_start = evening_start if evening_start is not None else current_rest_times["evening"]["start"]
        new_morning_end = morning_end if morning_end is not None else current_rest_times["morning"]["end"]
        
        # Evening rest time continues uninterrupted until morning_end
        # Morning rest time starts at midnight (00:00) and ends at morning_end
        new_rest_times = {
            "morning": {
                "start": "00:00",  # Morning always starts at midnight
                "end": new_morning_end
            },
            "evening": {
                "start": new_evening_start,
                "end": new_morning_end  # Evening continues until morning_end
            }
        }
        
        # Calculate new rest time duration
        new_duration = self.config.calculate_rest_time_duration(new_rest_times)
        
        # Calculate the ratio and adjust daily limit
        if original_duration > 0:
            ratio = new_duration / original_duration
        else:
            # If original duration is 0, we can't calculate ratio
            # Just use a default adjustment
            ratio = 1.0
        
        # Get base limit
        base_limit = self.config.get_daily_limit(weekday)
        multiplier = self.config.get_holiday_limit_multiplier()
        current_limit = int(base_limit * multiplier)
        
        # Adjust limit proportionally
        adjusted_limit = int(current_limit * ratio)
        
        # Store the modification
        self.today_data["rest_time_modification"] = {
            "original_rest_times": current_rest_times.copy(),
            "new_rest_times": new_rest_times.copy(),
            "original_duration": original_duration,
            "new_duration": new_duration,
            "original_limit": current_limit,
            "adjusted_limit": adjusted_limit,
            "ratio": ratio,
            "modified_at": datetime.now().isoformat()
        }
        
        # Save the data
        self._save_today_data(force=True)
        
        logger.info(
            f"Rest time modified for today: "
            f"original duration {original_duration}s, new duration {new_duration}s, "
            f"limit adjusted from {current_limit}s to {adjusted_limit}s"
        )
        
        return {
            "status": "ok",
            "message": "Rest time modified successfully",
            "original_rest_times": current_rest_times,
            "new_rest_times": new_rest_times,
            "original_duration": original_duration,
            "new_duration": new_duration,
            "original_limit": current_limit,
            "adjusted_limit": adjusted_limit,
            "ratio": ratio
        }
    
    def set_temporary_denylisted_usage(self, minutes: int) -> Dict:
        """
        Set a temporary adjustment to the daily denylisted_usage limit for the current day.
        Positive values add to the limit, negative values subtract from it.
        Can be set multiple times per day.
        
        Args:
            minutes: The adjustment in minutes (positive to add, negative to subtract)
            
        Returns:
            Dict with status, message, and details about the modification
        """
        # Convert minutes to seconds
        seconds = minutes * 60
        
        # Get base limit
        weekday = datetime.now().strftime("%A").lower()
        base_limit = self.config.get_daily_limit(weekday)
        multiplier = self.config.get_holiday_limit_multiplier()
        base_limit = int(base_limit * multiplier)
        
        # Apply rest time modification if it exists
        if "rest_time_modification" in self.today_data:
            modification = self.today_data["rest_time_modification"]
            if "adjusted_limit" in modification:
                base_limit = modification["adjusted_limit"]
        
        # Calculate new adjusted limit
        new_limit = max(0, base_limit + seconds)  # Ensure limit doesn't go negative
        
        # Get current actual usage for reference
        actual_denylisted = self.today_data.get("total_denylisted", 0)
        
        # Add current session if tracking
        if self.current_app and self.current_start_time:
            reference_time = self.last_progress_time or self.current_start_time
            current_duration = max(0, time_module.time() - reference_time)
            if self.config.is_denylisted(self.current_app):
                actual_denylisted += current_duration
            elif not self.config.is_allowlisted(self.current_app):
                if not self.config.is_rest_time():
                    actual_denylisted += current_duration
        
        # Store the temporary adjustment value (in seconds internally)
        self.today_data["temporary_denylisted_usage"] = seconds
        
        # Save the data
        self._save_today_data(force=True)
        
        logger.info(
            f"Temporary denylisted_usage adjustment set for today: "
            f"base limit {base_limit}s ({base_limit // 60}m), "
            f"adjustment {seconds}s ({minutes}m), "
            f"new limit {new_limit}s ({new_limit // 60}m), "
            f"actual usage {actual_denylisted}s ({actual_denylisted // 60}m)"
        )
        
        return {
            "status": "ok",
            "message": "Temporary denylisted_usage adjustment set successfully",
            "base_limit": base_limit,
            "adjustment_seconds": seconds,
            "adjustment_minutes": minutes,
            "new_limit": new_limit,
            "actual_denylisted": actual_denylisted,
            "remaining": max(0, new_limit - actual_denylisted)
        }
    
    def is_limit_exceeded(self) -> bool:
        """Check if daily limit is exceeded."""
        return self.get_remaining_time() <= 0
    
    def get_detailed_stats(self) -> Dict:
        """Get detailed statistics for today."""
        denylisted, allowlisted = self.get_current_usage()
        adjusted_limit = self.get_adjusted_daily_limit()
        multiplier = self.config.get_holiday_limit_multiplier()
        
        return {
            "date": self.today_data.get("date", date.today().isoformat()),
            "denylisted_usage": denylisted,
            "allowlisted_usage": allowlisted,
            "daily_limit": adjusted_limit,
            "remaining": self.get_remaining_time(),
            "limit_exceeded": self.is_limit_exceeded(),
            "denylisted_apps": self.today_data.get("denylisted_usage", {}),
            "allowlisted_apps": self.today_data.get("allowlisted_usage", {}),
            "total_sessions": len(self.today_data.get("sessions", [])),
            "in_rest_time": self.config.is_rest_time(),
            "holiday_mode": multiplier > 1.0,
            # Backward compatibility aliases
            "denylisted_usage_seconds": denylisted,
            "allowlisted_usage_seconds": allowlisted,
            "daily_limit_seconds": adjusted_limit,
            "remaining_seconds": self.get_remaining_time(),
            "blacklisted_usage_seconds": denylisted,
            "whitelisted_usage_seconds": allowlisted,
            "blacklisted_apps": self.today_data.get("denylisted_usage", {}),
            "whitelisted_apps": self.today_data.get("allowlisted_usage", {})
        }
    
    def _get_history_file_path(self) -> Path:
        """Get path to history file."""
        return self.data_directory / "history.json"
    
    def _load_history(self) -> Dict:
        """Load 30-day history from file."""
        history_file = self._get_history_file_path()
        
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    history = json.load(f)
                    # Clean up old entries (keep only last 30 days)
                    self._cleanup_history(history)
                    return history
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Error loading history file: {e}")
        
        return {
            "last_updated": datetime.now().isoformat(),
            "days": {}
        }
    
    def _cleanup_history(self, history: Dict):
        """Remove entries older than 30 days."""
        cutoff_date = date.today() - timedelta(days=30)
        days = history.get("days", {})
        
        dates_to_remove = []
        for date_str in days.keys():
            try:
                entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if entry_date < cutoff_date:
                    dates_to_remove.append(date_str)
            except ValueError:
                dates_to_remove.append(date_str)
        
        for date_str in dates_to_remove:
            del days[date_str]
    
    def _update_history(self):
        """Update history with current day's usage."""
        # Don't acquire lock here - caller should already have it
        today_str = date.today().isoformat()
        
        if "days" not in self.history:
            self.history["days"] = {}
        
        # Combine denylisted and allowlisted usage
        combined_usage = {}
        
        # Add denylisted usage
        for app, seconds in self.today_data.get("denylisted_usage", {}).items():
            if app not in combined_usage:
                combined_usage[app] = 0
            combined_usage[app] += seconds
        
        # Add allowlisted usage
        for app, seconds in self.today_data.get("allowlisted_usage", {}).items():
            if app not in combined_usage:
                combined_usage[app] = 0
            combined_usage[app] += seconds
        
        # Add current session if tracking
        if self.current_app and self.current_start_time:
            current_duration = time_module.time() - self.current_start_time
            if self.current_app not in combined_usage:
                combined_usage[self.current_app] = 0
            combined_usage[self.current_app] += current_duration
        
        # Update history for today
        self.history["days"][today_str] = {
            app: int(seconds) for app, seconds in combined_usage.items()
        }
        
        # Clean up old entries
        self._cleanup_history(self.history)
        
        # Update timestamp
        self.history["last_updated"] = datetime.now().isoformat()
    
    def save_history(self):
        """Save history to file."""
        # Use non-blocking lock acquisition to avoid hanging
        lock_acquired = False
        try:
            logger.debug("Attempting to acquire history lock...")
            # Try to acquire lock (non-blocking)
            lock_acquired = self.history_lock.acquire(blocking=False)
            if not lock_acquired:
                logger.warning("History lock is busy, skipping save (will retry on next cycle)")
                return
            
            logger.debug("History lock acquired, updating history...")
            try:
                # Update history before saving
                self._update_history()
                logger.debug("History updated")
                
                history_file = self._get_history_file_path()
                logger.debug(f"Saving history to: {history_file}")
                
                # Save to temporary file first, then rename (atomic operation)
                temp_file = history_file.with_suffix('.tmp')
                try:
                    logger.debug(f"Writing to temp file: {temp_file}")
                    with open(temp_file, 'w') as f:
                        json.dump(self.history, f, indent=2)
                    logger.debug("JSON written, renaming file...")
                    # Atomic rename
                    temp_file.replace(history_file)
                    logger.debug("History file saved successfully")
                except IOError as e:
                    logger.error(f"Error saving history file: {e}")
                    # Clean up temp file if it exists
                    if temp_file.exists():
                        try:
                            temp_file.unlink()
                        except:
                            pass
            finally:
                if lock_acquired:
                    logger.debug("Releasing history lock...")
                    self.history_lock.release()
                    logger.debug("History lock released")
        except Exception as e:
            logger.error(f"Unexpected error in save_history: {e}", exc_info=True)
            if lock_acquired:
                try:
                    self.history_lock.release()
                except:
                    pass
    
    def get_history(self) -> Dict:
        """Get a copy of the current history."""
        with self.history_lock:
            # Return a deep copy to avoid race conditions
            return json.loads(json.dumps(self.history))
    
    def stop(self):
        """Stop tracking and save data."""
        try:
            logger.info("Stopping tracker: ending current session...")
            self._end_current_session()
            logger.info("Stopping tracker: session ended")
        except Exception as e:
            logger.error(f"Error ending session: {e}", exc_info=True)
        
        try:
            logger.info("Stopping tracker: saving today's data...")
            self._save_today_data(force=True)  # Force save on shutdown
            logger.info("Stopping tracker: today's data saved")
        except Exception as e:
            logger.error(f"Error saving today's data: {e}", exc_info=True)
        
        try:
            logger.info("Stopping tracker: saving history...")
            self.save_history()
            logger.info("Stopping tracker: history saved")
        except Exception as e:
            logger.error(f"Error saving history: {e}", exc_info=True)
        
        logger.info("Stopping tracker: completed")

