# Screen Time Tracker

A Python application for tracking screen time in X11 environments. It monitors application usage and enforces daily limits for denylisted applications while tracking (but not limiting) allowlisted applications.

## Features

- **Application Categorization**: Allowlist and denylist applications
- **Daily Limits**: Configurable daily time limits for denylisted applications
- **Per-Weekday Limits**: Different limits for each day of the week
- **Rest Times**: Configurable rest periods (morning and evening) per weekday
- **Holiday Mode**: Extended limits and rest times during holiday seasons
- **X11 Monitoring**: Tracks active window titles in X11 environment
- **Usage Statistics**: Detailed tracking and reporting

## Requirements

### System Dependencies

- X11 environment

### Python

- Python 3.6 or higher
- `python-xlib`: `pip install python-xlib`

## Installation

### Quick Installation (Recommended)

For Debian/Ubuntu systems:

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install python3-pip python3-setuptools python3-wheel

# Install screentime
cd /path/to/screentime
sudo pip3 install .
```

This installs screentime system-wide and makes the `screentime` command available.

### Manual Installation

1. Clone or download this repository
2. Install Python dependencies:
   ```bash
   pip3 install python-xlib
   ```
3. Make the main script executable:
   ```bash
   chmod +x screentime.py
   ```
4. (Optional) Create a symlink for easy access:
   ```bash
   sudo ln -s $(pwd)/screentime.py /usr/local/bin/screentime
   ```

### Debian Package Installation

For a proper Debian package installation, see `INSTALL.md` for detailed instructions including:
- Creating a .deb package
- Systemd service setup
- Advanced configuration options

## Configuration

Configuration is stored in `~/.screentime/config.json`. If this file doesn't exist, the application will use the default configuration from `config/default_config.json`.

### Configuration Structure

```json
{
  "allowlist": ["code", "gedit", "libreoffice"],
  "denylist": ["firefox", "chrome", "discord", "steam"],
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
    "monday": {
      "morning": {"start": "00:00", "end": "08:00"},
      "evening": {"start": "21:00", "end": "23:59"}
    }
  },
  "holiday_seasons": [
    {
      "name": "Summer Holidays",
      "start_date": "2025-07-01",
      "end_date": "2025-08-31",
      "extended_rest_morning": {"start": "00:00", "end": "10:00"},
      "extended_rest_evening": {"start": "20:00", "end": "23:59"},
      "extended_limit_multiplier": 1.5
    }
  ],
  "tracking_interval": 1,
  "data_directory": "~/.screentime"
}
```

### Configuration Options

- **allowlist**: List of application names (regex matching)
- **denylist**: List of application names (regex matching)
- **daily_limit**: Default daily limit in seconds
- **weekday_limits**: Per-weekday limits in seconds
- **rest_times**: Rest periods per weekday (morning and evening)
- **holiday_seasons**: Holiday periods with extended limits and rest times
- **tracking_interval**: How often to check active window in seconds (default: 1)
- **data_directory**: Where to store usage data

## Usage

### Run the Tracker

```bash
python3 screentime.py
```

Or make it executable and run directly:

```bash
./screentime.py
```

### View Statistics

```bash
python3 screentime.py --stats
```

### Run as Daemon

```bash
python3 screentime.py
```

(Note: The application runs as a daemon by default. Use `--no-daemon` to run in foreground.)

### Verbose Logging

```bash
python3 screentime.py --verbose
```

### Custom Configuration

```bash
python3 screentime.py --config /path/to/config.json
```

## How It Works

1. **Window Monitoring**: The application continuously monitors the active X11 window using `xdotool` or `xprop`.

2. **Application Detection**: Extracts application name from window titles and matches against allowlist/denylist.

3. **Time Tracking**: 
   - Allowlisted apps: Tracked but not counted toward limits
   - Denylisted apps: Tracked and counted toward daily limit (even during rest time)
   - Unknown apps: Tracked and counted toward daily limit (unless during rest time)

4. **Limit Enforcement**: 
   - Checks daily limit based on current weekday
   - Applies holiday mode multiplier if in holiday season
   - Logs warnings when limit is exceeded

5. **Data Storage**: Usage data is stored in JSON files in the data directory, one file per day.

## Data Storage

Usage data is stored in `~/.screentime/` (or configured data directory) as JSON files:

- `usage_YYYY-MM-DD.json`: Daily usage data with detailed sessions
- `history.json`: 30-day rolling history of per-application usage times
- `config.json`: User configuration (if customized)

### History File

The `history.json` file maintains a 30-day rolling history of application usage. It stores per-application usage times in seconds for each day. The file is automatically:
- Loaded when the program starts
- Saved every 2 minutes during operation
- Saved when the program shuts down
- Automatically cleaned to keep only the last 30 days

The history file structure:
```json
{
  "last_updated": "2025-01-15T10:30:00",
  "days": {
    "2025-01-15": {
      "firefox": 3600,
      "chrome": 1800,
      "code": 7200
    },
    "2025-01-14": {
      ...
    }
  }
}
```

## Rest Times

Rest times are periods when unknown application usage is not counted toward the daily limit. Denylisted applications always count toward the limit, even during rest time. You can configure:
- Morning rest time (e.g., 00:00 to 08:00)
- Evening rest time (e.g., 21:00 to 23:59)

During holiday seasons, these rest times can be extended.

## Holiday Mode

Holiday seasons allow:
- Extended rest times (longer morning/evening periods)
- Extended daily limits (multiplier applied to base limit)

Configure holiday seasons in the configuration file with start/end dates.

## Troubleshooting

### Cannot detect active window

- Ensure `python-xlib` is installed: `pip install python-xlib`
- Check that you're running in an X11 environment
- Try running with `--verbose` to see debug messages

### Applications not being detected correctly

- Application names are matched using regex (case-insensitive)
- The monitor uses WM_CLASS when available (more reliable than window titles)
- Adjust allowlist/denylist entries to match detected names

### Limit not being enforced

- Check that applications are in the denylist
- Verify you're not in rest time
- Check weekday limits are configured correctly

## License

This project is provided as-is for personal use.

