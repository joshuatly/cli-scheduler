import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from utils import get_app_paths, ensure_directories

# Platform constants
WINDOWS = "Windows"
LINUX = "Linux"

@pytest.fixture
def mock_home(tmp_path):
    """Mock the home directory to a temporary path."""
    with patch("pathlib.Path.home", return_value=tmp_path):
        yield tmp_path

@pytest.fixture
def mock_env_vars(mock_home):
    """Mock Windows environment variables."""
    app_data = mock_home / "AppData" / "Roaming"
    local_app_data = mock_home / "AppData" / "Local"
    
    with patch.dict(os.environ, {
        "APPDATA": str(app_data),
        "LOCALAPPDATA": str(local_app_data)
    }):
        yield

def test_get_app_paths_windows(mock_home, mock_env_vars):
    """Test path resolution on Windows."""
    with patch("platform.system", return_value=WINDOWS):
        paths = get_app_paths()
        
        # Expected paths
        app_data = mock_home / "AppData" / "Roaming"
        local_app_data = mock_home / "AppData" / "Local"
        
        assert paths["config_file"] == app_data / "cli-scheduler" / "config.json"
        assert paths["data_dir"] == local_app_data / "cli-scheduler"
        assert paths["logs_dir"] == local_app_data / "cli-scheduler" / "logs"
        assert paths["db_file"] == local_app_data / "cli-scheduler" / "jobs.db"

def test_get_app_paths_linux(mock_home):
    """Test path resolution on Linux."""
    with patch("platform.system", return_value=LINUX):
        paths = get_app_paths()
        
        # Expected paths
        assert paths["config_file"] == mock_home / ".config" / "cli-scheduler" / "config.json"
        assert paths["data_dir"] == mock_home / ".local" / "cli-scheduler"
        assert paths["logs_dir"] == mock_home / ".local" / "cli-scheduler" / "logs"

def test_ensure_directories(mock_home):
    """Test that directories are created."""
    # Create dummy paths object using tmp_path
    paths = {
        "config_file": mock_home / "config" / "config.json",
        "data_dir": mock_home / "data",
        "logs_dir": mock_home / "data" / "logs",
        "db_file": mock_home / "data" / "jobs.db"
    }
    
    ensure_directories(paths)
    
    assert paths["config_file"].parent.exists()
    assert paths["data_dir"].exists()
    assert paths["logs_dir"].exists()

def test_ensure_directories_with_mocks():
    """Test that mkdir is called correctly using mocks (isolation)."""
    mock_config_path = MagicMock()
    mock_data_path = MagicMock()
    mock_logs_path = MagicMock()
    
    paths = {
        "config_file": mock_config_path,
        "data_dir": mock_data_path,
        "logs_dir": mock_logs_path
    }
    
    ensure_directories(paths)
    
    # Check parent mkdir for config
    mock_config_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    # Check mkdir for directories
    mock_data_path.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_logs_path.mkdir.assert_called_once_with(parents=True, exist_ok=True)
