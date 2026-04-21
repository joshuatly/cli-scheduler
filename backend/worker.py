import os
import platform
import queue
import subprocess
import threading
import time
from datetime import datetime, timedelta

import psutil


class JobRunner:
    """Background worker that consumes a job queue and runs shell commands.

    Reads `storage`, `logs_dir`, and `base_dir` from the supplied context at
    each call so tests can swap storage/path values at runtime.
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.job_queue = queue.Queue()
        self._process_lock = threading.Lock()
        self._running = {}  # job_id -> Popen
        self._thread = None

    def submit(self, job_id):
        self.job_queue.put(job_id)

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def init_from_storage(self):
        """Re-queue 'queued' jobs and mark stale 'running' jobs as failed."""
        for job in self.ctx.storage.get_all_jobs():
            if job["status"] == "queued":
                print(f"Re-queueing job {job['id']}")
                self.job_queue.put(job["id"])
            elif job["status"] == "running":
                print(f"Marking interrupted job {job['id']} as failed")
                self._update_status(job["id"], "failed", -1)
                log_path = os.path.join(self.ctx.logs_dir, job["log_file"])
                if os.path.exists(log_path):
                    with open(log_path, "a") as f:
                        f.write("\n\n[System] Job interrupted by server restart.")

    def cancel(self, job_id):
        """Terminate a running job's process tree. Safe to call when not running."""
        with self._process_lock:
            process = self._running.get(job_id)
        if not process:
            return
        try:
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            try:
                parent.terminate()
            except psutil.NoSuchProcess:
                pass
            _, alive = psutil.wait_procs(children + [parent], timeout=3)
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            print(f"Error killing job {job_id}: {e}")

    def _update_status(self, job_id, status, exit_code=None):
        updates = {"status": status}
        if exit_code is not None:
            updates["exit_code"] = exit_code
        if status == "running":
            updates["start_time"] = datetime.now().isoformat()
        elif status in ("finished", "failed"):
            updates["end_time"] = datetime.now().isoformat()
        self.ctx.storage.update_job(job_id, updates)

    def _run(self):
        while True:
            try:
                job_id = self.job_queue.get()
                if job_id is None:
                    break

                job = self.ctx.storage.get_job(job_id)
                if not job or job["status"] not in ("queued", "running"):
                    self.job_queue.task_done()
                    continue

                self._update_status(job_id, "running")
                self._execute(job)
                self.job_queue.task_done()
            except Exception as e:
                print(f"Worker thread error: {e}")
                time.sleep(1)

    def _execute(self, job):
        job_id = job["id"]
        log_path = os.path.join(self.ctx.logs_dir, f"{job_id}.log")
        try:
            with open(log_path, "w") as log_file:
                env = os.environ.copy()
                env.pop("VIRTUAL_ENV", None)
                env.setdefault("HOSTNAME", platform.node())

                process = subprocess.Popen(
                    job["command"],
                    shell=True,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    cwd=job.get("cwd", self.ctx.base_dir),
                    env=env,
                )
                with self._process_lock:
                    self._running[job_id] = process

                process.wait()

                final = "finished" if process.returncode == 0 else "failed"
                current = self.ctx.storage.get_job(job_id)
                if current and current.get("status") == "cancelled":
                    final = "cancelled"
                self._update_status(job_id, final, process.returncode)
        except Exception as e:
            with open(log_path, "a") as log_file:
                log_file.write(f"\n\nSystem Error: {str(e)}\n")
            self._update_status(job_id, "failed", -1)
        finally:
            with self._process_lock:
                self._running.pop(job_id, None)


class RetentionSweeper:
    """Background thread that periodically prunes old job records and their log files.

    Only terminal jobs (finished/failed/cancelled) are eligible for deletion.
    Reads config on each sweep so changes take effect without restart.
    """

    def __init__(self, ctx, interval_seconds=3600):
        self.ctx = ctx
        self.interval = interval_seconds
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            time.sleep(self.interval)
            try:
                self._sweep()
            except Exception as e:
                print(f"Retention sweep error: {e}")

    def _sweep(self):
        config = self.ctx.load_config()
        max_jobs = config.get("retention_max_jobs")
        max_age_days = config.get("retention_max_age_days")

        if not max_jobs and not max_age_days:
            return

        all_jobs = self.ctx.storage.get_all_jobs()
        terminal = [j for j in all_jobs
                    if j["status"] in ("finished", "failed", "cancelled")]

        to_delete = set()

        if max_age_days:
            cutoff = datetime.now() - timedelta(days=max_age_days)
            for job in terminal:
                try:
                    if datetime.fromisoformat(job["created_at"]) < cutoff:
                        to_delete.add(job["id"])
                except (ValueError, TypeError):
                    pass

        if max_jobs:
            remaining = [j for j in terminal if j["id"] not in to_delete]
            remaining.sort(key=lambda j: j.get("created_at", ""), reverse=True)
            if len(remaining) > max_jobs:
                to_delete.update(j["id"] for j in remaining[max_jobs:])

        if not to_delete:
            return

        for job in terminal:
            if job["id"] in to_delete and job.get("log_file"):
                try:
                    os.remove(os.path.join(self.ctx.logs_dir, job["log_file"]))
                except FileNotFoundError:
                    pass

        self.ctx.storage.delete_jobs(list(to_delete))
        print(f"Retention sweep: deleted {len(to_delete)} jobs")
