import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from stats import StatsTracker, QUEUE_THRESHOLD_SECS


def _iso(dt):
    return dt.isoformat()


def _job(job_id, status="finished", run_secs=60, queue_secs=0, preset="TestPreset"):
    now = datetime.now()
    created = now - timedelta(seconds=run_secs + queue_secs + 5)
    start = created + timedelta(seconds=queue_secs)
    end = start + timedelta(seconds=run_secs)
    return {
        "id": job_id,
        "command": "echo test",
        "preset": preset,
        "input_arg": "",
        "status": status,
        "created_at": _iso(created),
        "start_time": _iso(start),
        "end_time": _iso(end),
        "exit_code": 0 if status == "finished" else 1,
        "cwd": "/tmp",
        "log_file": f"{job_id}.log",
    }


@pytest.fixture
def tracker():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "stats.json")
    t = StatsTracker(path)
    yield t
    shutil.rmtree(tmp)


# --- record_job ---

def test_record_job_increments_totals(tracker):
    tracker.record_job(_job("j1", "finished", run_secs=30, queue_secs=0))
    s = tracker.get_stats()
    assert s["all_time"]["total"] == 1
    assert s["all_time"]["finished"] == 1
    assert s["all_time"]["failed"] == 0


def test_record_job_idempotent(tracker):
    job = _job("j1", "finished")
    tracker.record_job(job)
    tracker.record_job(job)
    assert tracker.get_stats()["all_time"]["total"] == 1


def test_record_job_run_duration_tracked(tracker):
    tracker.record_job(_job("j1", "finished", run_secs=120))
    s = tracker.get_stats()
    assert s["all_time"]["run_seconds_total"] >= 119
    assert s["all_time"]["run_seconds_count"] == 1


def test_record_job_no_time_saved_for_solo(tracker):
    tracker.record_job(_job("j1", "finished", run_secs=60, queue_secs=0))
    assert tracker.get_stats()["all_time"]["time_saved_seconds"] == 0.0


def test_record_job_time_saved_for_queued(tracker):
    big_queue = QUEUE_THRESHOLD_SECS + 30
    tracker.record_job(_job("j1", "finished", run_secs=60, queue_secs=big_queue))
    saved = tracker.get_stats()["all_time"]["time_saved_seconds"]
    assert saved >= 59  # approximately run_secs


def test_record_job_failed_tracked(tracker):
    tracker.record_job(_job("j1", "failed", run_secs=10))
    s = tracker.get_stats()
    assert s["all_time"]["failed"] == 1
    assert s["all_time"]["total"] == 1


def test_record_job_queued_status_not_tracked(tracker):
    job = _job("j1", "finished")
    job["status"] = "queued"
    tracker.record_job(job)
    assert tracker.get_stats()["all_time"]["total"] == 0


# --- weekly ---

def test_weekly_bucket_created(tracker):
    tracker.record_job(_job("j1", "finished"))
    s = tracker.get_stats()
    assert len(s["weekly"]) == 1
    week = list(s["weekly"].values())[0]
    assert week["total"] == 1
    assert week["finished"] == 1


# --- duration buckets ---

def test_duration_bucket_10s(tracker):
    tracker.record_job(_job("j1", "finished", run_secs=5))
    assert tracker.get_stats()["run_duration_buckets"]["0–10s"] == 1


def test_duration_bucket_1m(tracker):
    tracker.record_job(_job("j1", "finished", run_secs=90))
    assert tracker.get_stats()["run_duration_buckets"]["1m–5m"] == 1


# --- per_preset ---

def test_per_preset_tracked(tracker):
    tracker.record_job(_job("j1", "finished", preset="MyPreset", run_secs=60))
    pp = tracker.get_stats()["per_preset"]["MyPreset"]
    assert pp["total"] == 1
    assert pp["finished"] == 1
    assert pp["run_seconds_count"] == 1


def test_per_preset_avg(tracker):
    tracker.record_job(_job("j1", "finished", preset="P", run_secs=60))
    tracker.record_job(_job("j2", "finished", preset="P", run_secs=120))
    pp = tracker.get_stats()["per_preset"]["P"]
    assert pp["run_seconds_count"] == 2
    avg = pp["run_seconds_total"] / pp["run_seconds_count"]
    assert 85 <= avg <= 95  # ~90s


def test_per_preset_min_max(tracker):
    tracker.record_job(_job("j1", "finished", preset="P", run_secs=10))
    tracker.record_job(_job("j2", "finished", preset="P", run_secs=300))
    pp = tracker.get_stats()["per_preset"]["P"]
    assert pp["min_run_seconds"] <= 11
    assert pp["max_run_seconds"] >= 299


# --- record_sweep ---

def test_record_sweep_before_deletion(tracker):
    jobs = [_job("j1", "finished"), _job("j2", "failed")]
    tracker.record_sweep(jobs)
    s = tracker.get_stats()
    assert s["all_time"]["total"] == 2
    # After sweep, processed_ids should be empty (jobs are gone from storage)
    assert "j1" not in s["processed_ids"]
    assert "j2" not in s["processed_ids"]


def test_record_sweep_does_not_double_count(tracker):
    job = _job("j1", "finished")
    tracker.record_job(job)      # already counted
    tracker.record_sweep([job])  # sweep: should not re-count
    assert tracker.get_stats()["all_time"]["total"] == 1


# --- rebuild_from_jobs ---

def test_rebuild_from_jobs(tracker):
    jobs = [_job("j1", "finished"), _job("j2", "failed"), _job("j3", "queued")]
    tracker.rebuild_from_jobs(jobs)
    s = tracker.get_stats()
    assert s["all_time"]["total"] == 2  # queued not counted
    assert "j1" in s["processed_ids"]
    assert "j2" in s["processed_ids"]
    assert "j3" not in s["processed_ids"]


def test_rebuild_idempotent(tracker):
    jobs = [_job("j1", "finished")]
    tracker.rebuild_from_jobs(jobs)
    tracker.rebuild_from_jobs(jobs)
    assert tracker.get_stats()["all_time"]["total"] == 1


# --- /api/stats endpoint ---

def test_api_stats_endpoint(client, mock_env):
    import app as _app
    from stats import StatsTracker
    stats_path = os.path.join(mock_env["base"], "stats.json")
    _app._ctx.stats = StatsTracker(stats_path)

    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "all_time" in data
    assert "weekly" in data
    assert "run_duration_buckets" in data
    assert "per_preset" in data


def test_stats_page_loads(client, mock_env):
    resp = client.get("/stats")
    assert resp.status_code == 200
