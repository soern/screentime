"""
Warning management for rest time and limit warnings.

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
import logging
from datetime import datetime
from typing import Optional, Set

from utils.notifications import Notifier

logger = logging.getLogger(__name__)


class WarningManager:
    """Base class for warning managers."""
    
    def __init__(self, notifier: Notifier):
        """
        Initialize warning manager.
        
        Args:
            notifier: Notifier instance for sending notifications
        """
        self.notifier = notifier
    
    def check_and_notify(self, stats: dict) -> bool:
        """
        Check conditions and send notification if needed.
        
        Args:
            stats: Current statistics dictionary
            
        Returns:
            True if notification was sent, False otherwise
        """
        raise NotImplementedError


class RestTimeWarningManager(WarningManager):
    """Manages rest time approaching warnings."""
    
    def __init__(self, notifier: Notifier, config_manager, minutes_before: int = 15):
        """
        Initialize rest time warning manager.
        
        Args:
            notifier: Notifier instance
            config_manager: ConfigManager instance
            minutes_before: Minutes before rest time to show warning
        """
        super().__init__(notifier)
        self.config_manager = config_manager
        self.minutes_before = minutes_before
        self.warning_shown: Optional[datetime] = None
    
    def check_and_notify(self, stats: dict) -> bool:
        """Check if rest time is approaching and show notification."""
        if stats.get("in_rest_time", False):
            # Reset warning when rest time actually starts
            if self.warning_shown is not None:
                self.warning_shown = None
                logger.debug("Rest time started, warning reset")
            return False
        
        is_approaching, rest_time_start = self.config_manager.is_rest_time_approaching(
            minutes_before=self.minutes_before
        )
        
        if is_approaching and rest_time_start:
            # Only show notification once per rest time period
            if self.warning_shown != rest_time_start:
                rest_time_str = rest_time_start.strftime("%H:%M")
                self.notifier.notify(
                    title="Rest Time Approaching",
                    message=f"Rest time will start at {rest_time_str} (in {self.minutes_before} minutes). Denylisted applications will be closed.",
                    urgency="normal",
                    timeout=0  # Permanent notification
                )
                self.warning_shown = rest_time_start
                logger.info(f"Rest time warning shown: rest time starts at {rest_time_str}")
                return True
        else:
            # Reset warning if we're no longer in the warning window
            if self.warning_shown and rest_time_start:
                from datetime import datetime
                time_until_rest = (rest_time_start - datetime.now()).total_seconds() / 60
                if time_until_rest > self.minutes_before or time_until_rest < 0:
                    self.warning_shown = None
        
        return False


class LimitWarningManager(WarningManager):
    """Manages daily limit approaching warnings."""
    
    def __init__(self, notifier: Notifier, warning_thresholds: list = None):
        """
        Initialize limit warning manager.
        
        Args:
            notifier: Notifier instance
            warning_thresholds: List of minutes thresholds for warnings (default: [15, 10, 5, 4, 3, 2, 1])
        """
        super().__init__(notifier)
        self.warning_thresholds = warning_thresholds or [15, 10, 5, 4, 3, 2, 1]
        self.warnings_shown: Set[int] = set()
    
    def check_and_notify(self, stats: dict) -> bool:
        """Check if limit is approaching and show notification."""
        if stats.get("limit_exceeded", False):
            # Reset warnings when limit is exceeded
            if self.warnings_shown:
                self.warnings_shown.clear()
                logger.debug("Limit exceeded, warnings reset")
            return False
        
        if stats.get("in_rest_time", False):
            return False
        
        remaining_seconds = stats.get("remaining", 0)
        remaining_minutes = remaining_seconds // 60
        
        for threshold in self.warning_thresholds:
            # Check if we're at or just passed this threshold
            if threshold == 1:
                is_at_threshold = 0 <= remaining_minutes <= 1
            else:
                is_at_threshold = (threshold - 1) < remaining_minutes <= threshold
            
            if is_at_threshold and threshold not in self.warnings_shown:
                # Show notification
                if remaining_minutes == 1:
                    message = f"Only 1 minute of screen time remaining! Denylisted applications will be closed when limit is reached."
                else:
                    message = f"Only {remaining_minutes} minutes of screen time remaining. Denylisted applications will be closed when limit is reached."
                
                self.notifier.notify(
                    title="Screen Time Limit Warning",
                    message=message,
                    urgency="normal",
                    timeout=10000  # 10 seconds
                )
                self.warnings_shown.add(threshold)
                logger.info(f"{remaining_minutes} minutes remaining (🌙 {threshold})")
                return True
        
        # Reset warnings if we're back above 15 minutes
        if remaining_minutes > 15:
            if self.warnings_shown:
                self.warnings_shown.clear()
                logger.debug("Remaining time above 15 minutes, warnings reset")
        
        return False

