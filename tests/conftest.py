import pytest
import os
import shutil
import tempfile
import sys
import json
import time
from threading import Thread

# Add parent directory to path to import app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app

@pytest.fixture
def client():
    app.app.config['TESTING'] = True
    with app.app.test_client() as client:
        yield client

@pytest.fixture
def mock_env(monkeypatch):
    # Create temp dirs for testing
    temp_dir = tempfile.mkdtemp()
    logs_dir = os.path.join(temp_dir, 'logs')
    jobs_file = os.path.join(temp_dir, 'jobs.json')
    config_file = os.path.join(temp_dir, 'config.json')
    
    os.makedirs(logs_dir)
    with open(jobs_file, 'w') as f:
        json.dump([], f)
    with open(config_file, 'w') as f:
        json.dump({"presets": [{"name": "TestPreset", "command": "echo {url}", "description": "Test"}]}, f)

    # Monkeypatch global variables in app.py
    monkeypatch.setattr(app, 'BASE_DIR', temp_dir)
    monkeypatch.setattr(app, 'CONFIG_FILE', config_file)
    monkeypatch.setattr(app, 'LOGS_DIR', logs_dir)
    
    # Initialize Storage with temp jobs file
    from storage import JsonJobStore
    app.STORAGE = JsonJobStore(jobs_file)
    
    # Clear queue
    while not app.job_queue.empty():
        try:
            app.job_queue.get_nowait()
            app.job_queue.task_done()
        except:
            pass
            
    yield {
        "base": temp_dir,
        "logs": logs_dir,
        "jobs": jobs_file,
        "config": config_file
    }
    
    # Cleanup
    # 1. Clear queue
    while not app.job_queue.empty():
        try:
            app.job_queue.get_nowait()
            app.job_queue.task_done()
        except:
            pass

    # 2. Wait for running jobs to finish (to release file handles)
    for _ in range(50): # Wait up to 5 seconds
        try:
            with app.data_lock: # safely read
                 if os.path.exists(jobs_file):
                    with open(jobs_file, 'r') as f:
                        jobs = json.load(f)
                    if not any(j['status'] == 'running' for j in jobs):
                        break
                 else:
                    break
        except:
            pass
        time.sleep(0.1)

    try:
        shutil.rmtree(temp_dir)
    except Exception as e:
        print(f"Warning: Failed to cleanup temp dir: {e}")
