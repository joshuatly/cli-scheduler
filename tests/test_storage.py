import pytest
import os
import json
import sqlite3
import tempfile
import sys
from typing import Dict, Any

# Add parent directory to path to import app and storage
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from storage import JsonJobStore, SqliteJobStore

# Fixtures for JsonJobStore
@pytest.fixture
def json_store_file():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)

@pytest.fixture
def json_store(json_store_file):
    return JsonJobStore(json_store_file)

# Fixtures for SqliteJobStore
@pytest.fixture
def sqlite_store_file():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)

@pytest.fixture
def sqlite_store(sqlite_store_file):
    return SqliteJobStore(sqlite_store_file)

# Helper to create a dummy job
def create_job(job_id: str = "job1", status: str = "pending") -> Dict[str, Any]:
    return {
        "id": job_id,
        "command": "echo test",
        "status": status,
        "created_at": "2024-01-01T00:00:00",
        "start_time": None,
        "end_time": None,
        "exit_code": None,
        "cwd": "/tmp",
        "log_file": None,
        "preset": "default",
        "input_arg": ""
    }

# --- Tests for JsonJobStore ---

def test_json_add_job(json_store):
    job = create_job()
    json_store.add_job(job)
    
    stored_jobs = json_store.get_all_jobs()
    assert len(stored_jobs) == 1
    assert stored_jobs[0]['id'] == job['id']

def test_json_get_job(json_store):
    job = create_job("job_abc")
    json_store.add_job(job)
    
    retrieved = json_store.get_job("job_abc")
    assert retrieved is not None
    assert retrieved['id'] == "job_abc"
    
    assert json_store.get_job("scam") is None

def test_json_update_job(json_store):
    job = create_job("job_update", "pending")
    json_store.add_job(job)
    
    json_store.update_job("job_update", {"status": "running", "start_time": "2024-01-01T00:01:00"})
    
    updated = json_store.get_job("job_update")
    assert updated['status'] == "running"
    assert updated['start_time'] == "2024-01-01T00:01:00"

def test_json_persistence(json_store_file):
    # 1. Create store, add job
    store1 = JsonJobStore(json_store_file)
    job = create_job("persist_job")
    store1.add_job(job)
    
    # 2. Create new store instance pointing to same file
    store2 = JsonJobStore(json_store_file)
    jobs = store2.get_all_jobs()
    
    assert len(jobs) == 1
    assert jobs[0]['id'] == "persist_job"

def test_json_empty_file(json_store_file):
    # Ensure it handles empty/non-existent file gracefully
    if os.path.exists(json_store_file):
        os.remove(json_store_file)
        
    store = JsonJobStore(json_store_file)
    assert store.get_all_jobs() == []

# --- Tests for SqliteJobStore ---

def test_sqlite_init(sqlite_store_file):
    # Test table creation
    store = SqliteJobStore(sqlite_store_file)
    conn = sqlite3.connect(sqlite_store_file)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs';")
    assert cursor.fetchone() is not None
    conn.close()

def test_sqlite_add_job(sqlite_store):
    job = create_job("sql_job")
    sqlite_store.add_job(job)
    
    jobs = sqlite_store.get_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]['id'] == "sql_job"

def test_sqlite_get_job(sqlite_store):
    job = create_job("sql_get")
    sqlite_store.add_job(job)
    
    retrieved = sqlite_store.get_job("sql_get")
    assert retrieved is not None
    assert retrieved['id'] == "sql_get"
    
    assert sqlite_store.get_job("non_existent") is None

def test_sqlite_update_job(sqlite_store):
    job = create_job("sql_update", "pending")
    sqlite_store.add_job(job)
    
    sqlite_store.update_job("sql_update", {"status": "completed", "exit_code": 0})
    
    updated = sqlite_store.get_job("sql_update")
    assert updated['status'] == "completed"
    assert updated['exit_code'] == 0

def test_sqlite_persistence(sqlite_store_file):
    store1 = SqliteJobStore(sqlite_store_file)
    job = create_job("sql_persist")
    store1.add_job(job)

    store2 = SqliteJobStore(sqlite_store_file)
    jobs = store2.get_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]['id'] == "sql_persist"

# --- Tests for delete_jobs ---

def test_json_delete_jobs(json_store):
    for i in range(3):
        json_store.add_job(create_job(f"del_json_{i}"))

    json_store.delete_jobs(["del_json_0", "del_json_2"])

    remaining = json_store.get_all_jobs()
    assert len(remaining) == 1
    assert remaining[0]['id'] == "del_json_1"

def test_json_delete_jobs_noop_on_empty(json_store):
    json_store.delete_jobs([])
    assert json_store.get_all_jobs() == []

def test_sqlite_delete_jobs(sqlite_store):
    for i in range(3):
        sqlite_store.add_job(create_job(f"del_sql_{i}"))

    sqlite_store.delete_jobs(["del_sql_0", "del_sql_2"])

    remaining = sqlite_store.get_all_jobs()
    assert len(remaining) == 1
    assert remaining[0]['id'] == "del_sql_1"

def test_sqlite_delete_jobs_noop_on_empty(sqlite_store):
    sqlite_store.delete_jobs([])
    assert sqlite_store.get_all_jobs() == []
