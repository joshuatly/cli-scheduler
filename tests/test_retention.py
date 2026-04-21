import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from storage import JsonJobStore
from backend.worker import RetentionSweeper


def _iso(dt):
    return dt.isoformat()


def _make_job(job_id, status="finished", days_ago=0):
    created = datetime.now() - timedelta(days=days_ago)
    return {
        "id": job_id,
        "command": "echo test",
        "preset": "default",
        "input_arg": "",
        "status": status,
        "created_at": _iso(created),
        "start_time": None,
        "end_time": None,
        "exit_code": 0,
        "cwd": "/tmp",
        "log_file": f"{job_id}.log",
    }


class _FakeCtx:
    def __init__(self, store, logs_dir, config):
        self.storage = store
        self.logs_dir = logs_dir
        self._config = config

    def load_config(self):
        return self._config


@pytest.fixture
def env():
    tmp = tempfile.mkdtemp()
    logs = os.path.join(tmp, "logs")
    os.makedirs(logs)
    jobs_file = os.path.join(tmp, "jobs.json")
    store = JsonJobStore(jobs_file)
    yield store, logs
    shutil.rmtree(tmp)


def _sweeper(store, logs, config):
    ctx = _FakeCtx(store, logs, config)
    return RetentionSweeper(ctx)


# --- Tests ---

def test_sweep_noop_when_disabled(env):
    store, logs = env
    store.add_job(_make_job("j1", "finished", days_ago=100))
    store.add_job(_make_job("j2", "finished", days_ago=200))

    _sweeper(store, logs, {"retention_max_jobs": None, "retention_max_age_days": None})._sweep()

    assert len(store.get_all_jobs()) == 2


def test_sweep_age_policy(env):
    store, logs = env
    store.add_job(_make_job("old1", "finished", days_ago=40))
    store.add_job(_make_job("old2", "failed", days_ago=35))
    store.add_job(_make_job("recent", "finished", days_ago=5))

    _sweeper(store, logs, {"retention_max_jobs": None, "retention_max_age_days": 30})._sweep()

    remaining_ids = {j["id"] for j in store.get_all_jobs()}
    assert remaining_ids == {"recent"}


def test_sweep_age_policy_skips_active_jobs(env):
    store, logs = env
    store.add_job(_make_job("old_done", "finished", days_ago=40))
    store.add_job(_make_job("old_queued", "queued", days_ago=40))
    store.add_job(_make_job("old_running", "running", days_ago=40))

    _sweeper(store, logs, {"retention_max_jobs": None, "retention_max_age_days": 30})._sweep()

    remaining_ids = {j["id"] for j in store.get_all_jobs()}
    assert "old_queued" in remaining_ids
    assert "old_running" in remaining_ids
    assert "old_done" not in remaining_ids


def test_sweep_count_policy(env):
    store, logs = env
    # Add 5 jobs from oldest to newest
    for i in range(5):
        store.add_job(_make_job(f"j{i}", "finished", days_ago=50 - i))

    _sweeper(store, logs, {"retention_max_jobs": 2, "retention_max_age_days": None})._sweep()

    remaining = store.get_all_jobs()
    assert len(remaining) == 2
    # The 2 most recent jobs (smallest days_ago) should survive
    remaining_ids = {j["id"] for j in remaining}
    assert remaining_ids == {"j3", "j4"}


def test_sweep_count_policy_skips_active_jobs(env):
    store, logs = env
    store.add_job(_make_job("done1", "finished", days_ago=10))
    store.add_job(_make_job("done2", "finished", days_ago=5))
    store.add_job(_make_job("running1", "running", days_ago=3))

    _sweeper(store, logs, {"retention_max_jobs": 1, "retention_max_age_days": None})._sweep()

    remaining_ids = {j["id"] for j in store.get_all_jobs()}
    assert "running1" in remaining_ids
    assert "done2" in remaining_ids
    assert "done1" not in remaining_ids


def test_sweep_log_file_deleted(env):
    store, logs = env
    job = _make_job("todel", "finished", days_ago=40)
    store.add_job(job)

    log_path = os.path.join(logs, "todel.log")
    with open(log_path, "w") as f:
        f.write("output\n")

    _sweeper(store, logs, {"retention_max_jobs": None, "retention_max_age_days": 30})._sweep()

    assert not os.path.exists(log_path)
    assert store.get_job("todel") is None


def test_sweep_missing_log_file_no_error(env):
    store, logs = env
    store.add_job(_make_job("j1", "finished", days_ago=40))
    # Intentionally do not create the log file

    _sweeper(store, logs, {"retention_max_jobs": None, "retention_max_age_days": 30})._sweep()

    assert store.get_job("j1") is None


def test_sweep_both_policies(env):
    store, logs = env
    # old_done: age policy triggers (>30 days)
    store.add_job(_make_job("old_done", "finished", days_ago=40))
    # recent jobs: only count policy applies, keep 1 of 3
    for i in range(3):
        store.add_job(_make_job(f"recent{i}", "finished", days_ago=i))

    _sweeper(store, logs, {"retention_max_jobs": 1, "retention_max_age_days": 30})._sweep()

    remaining_ids = {j["id"] for j in store.get_all_jobs()}
    # old_done removed by age, only newest recent job survives count policy
    assert "old_done" not in remaining_ids
    assert "recent0" in remaining_ids  # days_ago=0 is the newest
    assert len(remaining_ids) == 1
