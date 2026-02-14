# CLI Scheduler

A lightweight, web-based task scheduler for running CLI commands and presets. Built with Flask.

## Features

*   **Web Dashboard**: View job status (Queued, Running, Finished, Failed) and logs in real-time.
*   **Presets**: Create and manage reusable command templates (e.g., `yt-dlp {url}`).
*   **Custom Commands**: Run arbitrary shell commands directly from the UI.
*   **Concurrency**: Jobs run sequentially in a background thread to prevent system overload.
*   **Persistence**: Jobs are saved to JSON files (`jobs.json`) by default, with optional SQLite support.
*   **Security**: Restricts access to local network (IP allowlist) by default.
*   **Cross-Platform**: Works on Windows and Linux.

## Installation

1.  **Clone the repository** (or download files).
2.  **Install Python 3.x**.
3.  **Run the application**:

### Windows
Double-click `run.bat` or run in PowerShell:
```powershell
.\run.bat
```

### Linux
Make the script executable and run it:
```bash
chmod +x run.sh
./run.sh
```

The application will start at `http://localhost:5000`.

## Usage

### 1. Dashboard
The home page shows a list of all jobs.
*   **Status**: Color-coded badges.
*   **Logs**: Click "View" to see the full output of any job.
*   **Auto-Refresh**: The dashboard updates every 5 seconds.

### 2. Submit Jobs
Click "New Job" or "Submit Job".
*   **Select Preset**: Choose a pre-configured command.
*   **Input**: Enter arguments (e.g., URLs), one per line. The `{url}` placeholder in the preset will be replaced by each line.
*   **Custom Command**: Select "Custom Command" to type a full shell command (e.g., `ping 8.8.8.8`).

### 3. Manage Presets
Click "Presets" in the navigation bar.
*   **Add**: Create new command templates.
*   **Edit/Delete**: Manage existing presets.

## Configuration

*   `config.json`: Master configuration file.
    *   `storage_type`: Set to `"json"` (default) or `"sqlite"`.
    *   `allowed_ips`: List of allowed IPs or patterns (e.g., `["127.0.0.1", "192.168.*"]`).
*   `jobs.json` / `jobs.db`: Stores job history (depending on `storage_type`).
*   `logs/`: Directory containing text logs for each job.

## Development

*   **Backend**: Flask (`app.py`)
*   **Frontend**: HTML/CSS (`templates/`, `static/`)
*   **Tests**: Run `python -m pytest tests/` to verify functionality.

## License
Open Source.
