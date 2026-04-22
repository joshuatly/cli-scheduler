"""Job statistics tracker.

Persists aggregate stats to a JSON file so history survives retention sweeps.
Call record_job() when a job finishes, record_sweep() before jobs are deleted,
and rebuild_from_jobs() on startup to catch any untracked historical jobs.
"""
import json
import os
import threading
from datetime import datetime

QUEUE_THRESHOLD_SECS = 10  # queue waits shorter than this are treated as "no queue"

_DURATION_BUCKETS = [
    ("0–10s",   0,    10),
    ("10s–1m",  10,   60),
    ("1m–5m",   60,   300),
    ("5m–30m",  300,  1800),
    ("30m+",    1800, float("inf")),
]


def _week_key(dt):
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _run_seconds(job):
    try:
        start = datetime.fromisoformat(job["start_time"])
        end = datetime.fromisoformat(job["end_time"])
        return max(0.0, (end - start).total_seconds())
    except (TypeError, ValueError, KeyError):
        return None


def _queue_seconds(job):
    try:
        created = datetime.fromisoformat(job["created_at"])
        start = datetime.fromisoformat(job["start_time"])
        return max(0.0, (start - created).total_seconds())
    except (TypeError, ValueError, KeyError):
        return None


def _bucket_label(seconds):
    for label, lo, hi in _DURATION_BUCKETS:
        if lo <= seconds < hi:
            return label
    return _DURATION_BUCKETS[-1][0]


def _empty_all_time():
    return {
        "total": 0,
        "finished": 0,
        "failed": 0,
        "cancelled": 0,
        "run_seconds_total": 0.0,
        "run_seconds_count": 0,
        "queue_seconds_total": 0.0,
        "time_saved_seconds": 0.0,
        "presets": {},
    }


def _empty_week():
    return {
        "total": 0,
        "finished": 0,
        "failed": 0,
        "cancelled": 0,
        "run_seconds_total": 0.0,
        "queue_seconds_total": 0.0,
        "time_saved_seconds": 0.0,
        "presets": {},
    }


def _empty_per_preset():
    return {
        "total": 0,
        "finished": 0,
        "failed": 0,
        "cancelled": 0,
        "run_seconds_total": 0.0,
        "run_seconds_count": 0,
        "min_run_seconds": None,
        "max_run_seconds": None,
        "last_run": None,
    }


def _empty_stats():
    return {
        "processed_ids": [],
        "weekly": {},
        "all_time": _empty_all_time(),
        "run_duration_buckets": {label: 0 for label, _, _ in _DURATION_BUCKETS},
        "per_preset": {},
    }


def _ensure_defaults(data):
    data.setdefault("processed_ids", [])
    data.setdefault("weekly", {})
    if "all_time" not in data:
        data["all_time"] = _empty_all_time()
    else:
        at = data["all_time"]
        at.setdefault("run_seconds_count", 0)
        at.setdefault("time_saved_seconds", 0.0)
        at.setdefault("presets", {})
    data.setdefault("run_duration_buckets", {label: 0 for label, _, _ in _DURATION_BUCKETS})
    data.setdefault("per_preset", {})
    return data


class StatsTracker:
    """Aggregate job stats that survive retention sweeps."""

    def __init__(self, stats_file):
        self.stats_file = stats_file
        self.lock = threading.Lock()

    # --- Internal helpers (caller must hold self.lock) ---

    def _load(self):
        if not os.path.exists(self.stats_file):
            return _empty_stats()
        try:
            with open(self.stats_file, "r") as f:
                return _ensure_defaults(json.load(f))
        except Exception:
            return _empty_stats()

    def _save(self, data):
        with open(self.stats_file, "w") as f:
            json.dump(data, f, indent=2)

    def _apply_job(self, data, job):
        """Incorporate one job into data in-place. Caller holds lock."""
        status = job.get("status", "")
        if status not in ("finished", "failed", "cancelled"):
            return

        run_secs = _run_seconds(job)
        queue_secs = _queue_seconds(job)

        # Time saved: if a job had to wait in queue, the user would have had to
        # watch the previous job finish to manually start this one. The time
        # they saved is this job's own run duration.
        time_saved = 0.0
        if (run_secs is not None and queue_secs is not None
                and queue_secs > QUEUE_THRESHOLD_SECS):
            time_saved = run_secs

        try:
            created = datetime.fromisoformat(job["created_at"])
        except (ValueError, TypeError, KeyError):
            created = datetime.now()
        week = _week_key(created)
        preset = job.get("preset") or "Unknown"

        # all_time
        at = data["all_time"]
        at["total"] += 1
        at[status] = at.get(status, 0) + 1
        if run_secs is not None:
            at["run_seconds_total"] += run_secs
            at["run_seconds_count"] = at.get("run_seconds_count", 0) + 1
        if queue_secs is not None:
            at["queue_seconds_total"] += queue_secs
        at["time_saved_seconds"] = at.get("time_saved_seconds", 0.0) + time_saved
        at["presets"][preset] = at["presets"].get(preset, 0) + 1

        # weekly
        if week not in data["weekly"]:
            data["weekly"][week] = _empty_week()
        wk = data["weekly"][week]
        wk["total"] += 1
        wk[status] = wk.get(status, 0) + 1
        if run_secs is not None:
            wk["run_seconds_total"] += run_secs
        if queue_secs is not None:
            wk["queue_seconds_total"] += queue_secs
        wk["time_saved_seconds"] = wk.get("time_saved_seconds", 0.0) + time_saved
        wk["presets"][preset] = wk["presets"].get(preset, 0) + 1

        # duration bucket (only meaningful runs)
        if run_secs is not None and status in ("finished", "failed"):
            label = _bucket_label(run_secs)
            data["run_duration_buckets"][label] = (
                data["run_duration_buckets"].get(label, 0) + 1
            )

        # per_preset
        if preset not in data["per_preset"]:
            data["per_preset"][preset] = _empty_per_preset()
        pp = data["per_preset"][preset]
        pp["total"] += 1
        pp[status] = pp.get(status, 0) + 1
        if run_secs is not None and status in ("finished", "failed"):
            pp["run_seconds_total"] += run_secs
            pp["run_seconds_count"] = pp.get("run_seconds_count", 0) + 1
            cur_min = pp.get("min_run_seconds")
            cur_max = pp.get("max_run_seconds")
            pp["min_run_seconds"] = run_secs if cur_min is None else min(cur_min, run_secs)
            pp["max_run_seconds"] = run_secs if cur_max is None else max(cur_max, run_secs)
        created_str = job.get("created_at")
        if created_str and (pp.get("last_run") is None or created_str > pp["last_run"]):
            pp["last_run"] = created_str

    # --- Public API ---

    def record_job(self, job):
        """Record stats for a completed job. Safe to call multiple times (idempotent)."""
        job_id = job.get("id")
        if not job_id:
            return
        if job.get("status") not in ("finished", "failed", "cancelled"):
            return
        with self.lock:
            data = self._load()
            processed = set(data["processed_ids"])
            if job_id in processed:
                return
            self._apply_job(data, job)
            processed.add(job_id)
            data["processed_ids"] = list(processed)
            self._save(data)

    def record_sweep(self, jobs):
        """Record stats for jobs about to be deleted. Must be called before deletion."""
        with self.lock:
            data = self._load()
            processed = set(data["processed_ids"])
            for job in jobs:
                job_id = job.get("id")
                if not job_id:
                    continue
                if job_id not in processed:
                    self._apply_job(data, job)
                # Remove from processed_ids: the job is leaving storage.
                # Its stats are now permanently in the aggregates.
                processed.discard(job_id)
            data["processed_ids"] = list(processed)
            self._save(data)

    def rebuild_from_jobs(self, jobs):
        """Process untracked historical jobs on startup. Idempotent."""
        with self.lock:
            data = self._load()
            processed = set(data["processed_ids"])
            changed = False
            for job in jobs:
                job_id = job.get("id")
                if not job_id or job_id in processed:
                    continue
                if job.get("status") not in ("finished", "failed", "cancelled"):
                    continue
                self._apply_job(data, job)
                processed.add(job_id)
                changed = True
            if changed:
                data["processed_ids"] = list(processed)
                self._save(data)

    def get_stats(self):
        """Return the full stats dict."""
        with self.lock:
            return self._load()
