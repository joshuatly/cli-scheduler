"""Application entry point.

This module wires together the Flask app, storage, worker, and route
blueprints. It also keeps a small set of module-level names
(`STORAGE`, `LOGS_DIR`, `CONFIG_FILE`, `BASE_DIR`, `data_lock`,
`job_queue`, `load_config`, `save_config`) so tests and tooling that
import `app` directly keep working.
"""
import os
import threading

from flasgger import Swagger
from flask import Flask

import backend.config_loader as _config_loader
from backend import api as api_blueprint
from backend import filters as _filters
from backend import middleware as _middleware
from backend import views as views_blueprint
from backend.context import SchedulerContext
from backend.swagger import SWAGGER_CONFIG, SWAGGER_TEMPLATE
from backend.worker import JobRunner, RetentionSweeper
from storage import JsonJobStore, SqliteJobStore
from utils import ensure_directories, get_app_paths

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATHS = get_app_paths()
ensure_directories(PATHS)

CONFIG_FILE = str(PATHS["config_file"])
LOGS_DIR = str(PATHS["logs_dir"])

# --- Config I/O (thin wrappers so tests can monkeypatch CONFIG_FILE) ---
data_lock = threading.Lock()


def load_config():
    return _config_loader.load_config(CONFIG_FILE, BASE_DIR)


def save_config(config):
    _config_loader.save_config(CONFIG_FILE, config)


config = load_config()

# --- Storage selection ---
STORAGE_TYPE = config.get("storage_type", "json")
ALLOWED_IPS = config.get("allowed_ips", ["127.0.0.1", "192.168.*"])

if "log_dir" in config:
    LOGS_DIR = os.path.expanduser(config["log_dir"])
    os.makedirs(LOGS_DIR, exist_ok=True)

if STORAGE_TYPE == "sqlite":
    if "db_path" in config:
        DB_FILE = os.path.expanduser(config["db_path"])
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    else:
        DB_FILE = str(PATHS["db_file"])
    STORAGE = SqliteJobStore(DB_FILE)
else:
    if "db_path" in config:
        JOBS_FILE = os.path.expanduser(config["db_path"])
        os.makedirs(os.path.dirname(JOBS_FILE), exist_ok=True)
    else:
        JOBS_FILE = str(PATHS["jobs_file"])
    STORAGE = JsonJobStore(JOBS_FILE)

print(f" * Logs Directory: {LOGS_DIR}")
if "DB_FILE" in dir():
    print(f" * Database File: {DB_FILE}")
else:
    print(f" * Jobs File: {JOBS_FILE}")

# --- Flask app ---
app = Flask(__name__)
Swagger(app, template=SWAGGER_TEMPLATE, config=SWAGGER_CONFIG)

# Shared context resolves storage/paths dynamically off this module.
import sys as _sys

_ctx = SchedulerContext()
_ctx.bind(_sys.modules[__name__])

# Worker owns the queue; re-expose it so existing imports keep working.
runner = JobRunner(_ctx)
_ctx.runner = runner
job_queue = runner.job_queue

sweeper = RetentionSweeper(_ctx)

app.extensions["cli_scheduler"] = _ctx

_filters.register(app)
_middleware.register(app, lambda: ALLOWED_IPS)


@app.context_processor
def _inject_footer():
    cfg = load_config()
    return dict(
        footer_text=cfg.get("footer_text", ""),
        version=_config_loader.get_version_info(),
    )


app.register_blueprint(views_blueprint.bp)
app.register_blueprint(api_blueprint.bp)


# --- Backward-compatible module-level helpers for legacy callers/tests ---

def get_job(job_id):
    return STORAGE.get_job(job_id)


def update_job_status(job_id, status, exit_code=None):
    from datetime import datetime

    updates = {"status": status}
    if exit_code is not None:
        updates["exit_code"] = exit_code
    if status == "running":
        updates["start_time"] = datetime.now().isoformat()
    elif status in ("finished", "failed"):
        updates["end_time"] = datetime.now().isoformat()
    STORAGE.update_job(job_id, updates)


# --- Bootstrap ---
runner.init_from_storage()
runner.start()
sweeper.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
