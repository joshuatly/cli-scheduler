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

## Installation with uv

If you prefer using [uv](https://github.com/astral-sh/uv) for fast dependency management:

1.  **Install uv** (if not installed):
    ```bash
    pip install uv
    ```

2.  **Create a virtual environment**:
    ```bash
    uv venv
    ```

3.  **Install dependencies**:
    ```bash
    uv pip install -r requirements.txt
    ```

4.  **Run the application**:
    ```bash
    # Windows
    .venv\Scripts\python app.py

    # Linux
    uv run app.py
    ```

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

### 4. URL-Driven Job Submission

The `/submit` route supports query parameters for automation, bookmarks, and external integrations.

#### Form Pre-fill

Open the New Job form with fields pre-populated:

```
/submit?preset=<preset_name>&urls=<url1>%0A<url2>&cwd=<path>
```

| Parameter | Description |
|-----------|-------------|
| `preset` | Name of the preset to select (must match exactly) |
| `urls` | Input arguments, newline-separated (`%0A` URL-encoded) |
| `cwd` | Working directory to pre-fill |

**Example:**
```
http://localhost:5000/submit?preset=yt-dlp+Audio&urls=https%3A//example.com&cwd=%2Fhome%2Fuser
```

The form opens pre-filled but the user still reviews and submits manually.

#### Auto-queue (Headless Submission)

Add `autoqueue=1` to bypass the form entirely — jobs are created and queued immediately, then the browser redirects to the dashboard.

```
/submit?autoqueue=1&preset=<preset_name>&urls=<url1>%0A<url2>&cwd=<path>
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `autoqueue` | Yes | Must be `1` to trigger auto-queue |
| `preset` | Yes | Name of an existing preset |
| `urls` | No | Newline-separated input args; one job created per line |
| `cwd` | No | Working directory; defaults to home directory |

**Example:**
```
http://localhost:5000/submit?autoqueue=1&preset=yt-dlp+Audio&urls=https%3A//example.com
```

If `urls` contains multiple lines, one job is queued per line. If `urls` is omitted and the preset command contains no `{url}` placeholder, a single job is queued with no input argument.

#### Retry / Edit a Past Job

From any job detail page, click **Edit** to open the New Job form pre-filled with that job's original preset, working directory, and input arguments:

```
/submit?retry_job_id=<job_id>
```

## Configuration

The application stores configuration and data in standard system locations:

### Windows
*   **Config**: `%APPDATA%\cli-scheduler\config.json`
*   **Data**: `%LOCALAPPDATA%\cli-scheduler\`
*   **Logs**: `%LOCALAPPDATA%\cli-scheduler\logs\`

### Linux / Other
*   **Config**: `~/.config/cli-scheduler/config.json`
*   **Data**: `~/.local/cli-scheduler/`
*   **Logs**: `~/.local/cli-scheduler/logs/`

### Files
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
