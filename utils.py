import os
import platform
from pathlib import Path

def get_app_paths():
    """
    Determine application paths based on the operating system.
    
    Windows:
        Config: %APPDATA%/cli-scheduler/config.json
        Data/Logs: %LOCALAPPDATA%/cli-scheduler/
        
    Linux/Other:
        Config: ~/.config/cli-scheduler/config.json
        Data: ~/.local/cli-scheduler/
        Logs: ~/.local/cli-scheduler/logs/
    """
    home = Path.home()
    system = platform.system()
    
    if system == "Windows":
        app_data = Path(os.environ.get('APPDATA', home / 'AppData' / 'Roaming'))
        local_app_data = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
        
        config_dir = app_data / 'cli-scheduler'
        data_dir = local_app_data / 'cli-scheduler'
    else:
        # Linux / MacOS / Other
        # Follow XDG or user specified structure
        config_dir = home / '.config' / 'cli-scheduler'
        data_dir = home / '.local' / 'cli-scheduler'
    
    return {
        "config_file": config_dir / 'config.json',
        "data_dir": data_dir,
        "logs_dir": data_dir / 'logs',
        "db_file": data_dir / 'jobs.db',
        "jobs_file": data_dir / 'jobs.json'
    }

def ensure_directories(paths):
    """Ensure all necessary directories exist."""
    # Config dir
    paths['config_file'].parent.mkdir(parents=True, exist_ok=True)
    
    # Data dir (for DB/JSON)
    paths['data_dir'].mkdir(parents=True, exist_ok=True)
    
    # Logs dir
    paths['logs_dir'].mkdir(parents=True, exist_ok=True)
