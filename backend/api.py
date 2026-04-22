"""JSON API blueprint.

All state-changing endpoints return JSON so the frontend can update in place
without full page reloads.
"""
import os
import uuid
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request


bp = Blueprint("api", __name__, url_prefix="/api")


def _ctx():
    """Grab runtime objects attached to the Flask app at startup."""
    return current_app.extensions["cli_scheduler"]


# --- Jobs ---

@bp.route("/jobs", methods=["GET"])
def list_jobs():
    """List jobs with optional status filter and pagination.
    ---
    tags: [Jobs]
    parameters:
      - name: page
        in: query
        type: integer
        default: 1
      - name: per_page
        in: query
        type: integer
        default: 20
      - name: status
        in: query
        type: string
        enum: [queued, running, finished, failed, cancelled]
    responses:
      200:
        description: Paginated job list
        schema:
          type: object
          properties:
            jobs:
              type: array
              items: {$ref: '#/definitions/Job'}
            page: {type: integer}
            per_page: {type: integer}
            total: {type: integer}
            total_pages: {type: integer}
    """
    ctx = _ctx()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    status_filter = request.args.get("status")

    jobs = ctx.storage.get_all_jobs()
    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    if status_filter:
        jobs = [j for j in jobs if j.get("status") == status_filter]

    total = len(jobs)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    return jsonify(
        {
            "jobs": jobs[start : start + per_page],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }
    )


@bp.route("/jobs", methods=["POST"])
def submit_jobs():
    """Submit one or more jobs using a saved preset.
    ---
    tags: [Jobs]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [preset]
          properties:
            preset: {type: string}
            urls:
              type: array
              items: {type: string}
            cwd: {type: string}
    responses:
      201:
        description: Jobs created
        schema:
          type: object
          properties:
            jobs:
              type: array
              items: {$ref: '#/definitions/Job'}
      400:
        description: Bad request
        schema: {$ref: '#/definitions/Error'}
    """
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    preset_name = data.get("preset")
    urls = data.get("urls", [])

    if not preset_name:
        return jsonify({"error": "Missing 'preset' field"}), 400

    cfg = ctx.load_config()
    matched = next((p for p in cfg["presets"] if p["name"] == preset_name), None)
    if not matched:
        return jsonify({"error": f"Preset '{preset_name}' not found"}), 400

    preset_cmd = matched["command"]
    cwd = data.get("cwd") or matched.get("cwd") or os.path.expanduser("~")

    if not urls and "{url}" not in preset_cmd:
        urls = [""]
    if not urls:
        return jsonify({"error": "No URLs provided for a preset that requires {url}"}), 400

    new_jobs = []
    for url in urls:
        job = _build_job(preset_name, preset_cmd, url, cwd)
        ctx.storage.add_job(job)
        ctx.runner.submit(job["id"])
        new_jobs.append(job)
    return jsonify({"jobs": new_jobs}), 201


@bp.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    """Get a single job.
    ---
    tags: [Jobs]
    parameters:
      - {name: job_id, in: path, type: string, required: true}
    responses:
      200:
        description: Job
        schema: {$ref: '#/definitions/Job'}
      404:
        description: Not found
        schema: {$ref: '#/definitions/Error'}
    """
    ctx = _ctx()
    job = ctx.storage.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@bp.route("/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    """Cancel a queued or running job.
    ---
    tags: [Jobs]
    parameters:
      - {name: job_id, in: path, type: string, required: true}
    responses:
      200:
        description: Cancelled
        schema: {$ref: '#/definitions/Job'}
      400:
        description: Job already finished
        schema: {$ref: '#/definitions/Error'}
      404:
        description: Not found
        schema: {$ref: '#/definitions/Error'}
    """
    ctx = _ctx()
    job = ctx.storage.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    status = job.get("status")
    if status in ("finished", "failed", "cancelled"):
        return jsonify({"error": "Job already finished"}), 400

    ctx.storage.update_job(job_id, {"status": "cancelled", "end_time": datetime.now().isoformat()})
    if status == "running":
        ctx.runner.cancel(job_id)
    return jsonify(ctx.storage.get_job(job_id))


@bp.route("/jobs/<job_id>/rerun", methods=["POST"])
def rerun_job(job_id):
    """Create a new copy of a job and queue it.
    ---
    tags: [Jobs]
    parameters:
      - {name: job_id, in: path, type: string, required: true}
    responses:
      201:
        description: New job
        schema: {$ref: '#/definitions/Job'}
      404:
        description: Not found
        schema: {$ref: '#/definitions/Error'}
    """
    ctx = _ctx()
    original = ctx.storage.get_job(job_id)
    if not original:
        return jsonify({"error": "Job not found"}), 404

    new_job = _clone_for_rerun(original)
    ctx.storage.add_job(new_job)
    ctx.runner.submit(new_job["id"])
    return jsonify(new_job), 201


@bp.route("/jobs/<job_id>/log", methods=["GET"])
def job_log(job_id):
    """Get a job's log output.
    ---
    tags: [Jobs]
    parameters:
      - {name: job_id, in: path, type: string, required: true}
    responses:
      200:
        description: Log content
        schema:
          type: object
          properties:
            content: {type: string}
      404:
        description: Not found
        schema: {$ref: '#/definitions/Error'}
    """
    ctx = _ctx()
    job = ctx.storage.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    log_path = os.path.join(ctx.logs_dir, job["log_file"])
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            return jsonify({"content": f.read()})
    return jsonify({"content": ""})


# --- Presets ---

@bp.route("/presets", methods=["GET"])
def list_presets():
    """List all presets.
    ---
    tags: [Presets]
    responses:
      200:
        description: Presets
        schema:
          type: object
          properties:
            presets:
              type: array
              items: {$ref: '#/definitions/Preset'}
    """
    return jsonify({"presets": _ctx().load_config()["presets"]})


@bp.route("/presets", methods=["POST"])
def create_preset():
    """Create a preset.
    ---
    tags: [Presets]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [name, command]
          properties:
            name: {type: string}
            command: {type: string}
            description: {type: string}
            cwd: {type: string}
    responses:
      201:
        description: Created
        schema: {$ref: '#/definitions/Preset'}
      400:
        description: Bad request
        schema: {$ref: '#/definitions/Error'}
    """
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    command = (data.get("command") or "").strip()
    if not name or not command:
        return jsonify({"error": "Missing required fields: name, command"}), 400

    cfg = ctx.load_config()
    if any(p["name"] == name for p in cfg["presets"]):
        return jsonify({"error": f"Preset '{name}' already exists"}), 400

    preset = {
        "name": name,
        "command": command,
        "description": data.get("description", ""),
        "cwd": data.get("cwd", ""),
    }
    cfg["presets"].append(preset)
    ctx.save_config(cfg)
    return jsonify(preset), 201


@bp.route("/presets/<name>", methods=["PUT"])
def update_preset(name):
    """Update a preset.
    ---
    tags: [Presets]
    parameters:
      - {name: name, in: path, type: string, required: true}
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            name: {type: string}
            command: {type: string}
            description: {type: string}
            cwd: {type: string}
    responses:
      200:
        description: Updated
        schema: {$ref: '#/definitions/Preset'}
      400:
        description: Bad request
        schema: {$ref: '#/definitions/Error'}
      404:
        description: Not found
        schema: {$ref: '#/definitions/Error'}
    """
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    cfg = ctx.load_config()
    preset = next((p for p in cfg["presets"] if p["name"] == name), None)
    if not preset:
        return jsonify({"error": f"Preset '{name}' not found"}), 404

    new_name = (data.get("name") or name).strip()
    if new_name != name and any(p["name"] == new_name for p in cfg["presets"]):
        return jsonify({"error": f"Preset '{new_name}' already exists"}), 400

    preset["name"] = new_name
    for field in ("command", "description", "cwd"):
        if field in data:
            preset[field] = data[field]

    ctx.save_config(cfg)
    return jsonify(preset)


@bp.route("/presets/<name>", methods=["DELETE"])
def delete_preset(name):
    """Delete a preset.
    ---
    tags: [Presets]
    parameters:
      - {name: name, in: path, type: string, required: true}
    responses:
      200:
        description: Deleted
      404:
        description: Not found
        schema: {$ref: '#/definitions/Error'}
    """
    ctx = _ctx()
    cfg = ctx.load_config()
    before = len(cfg["presets"])
    cfg["presets"] = [p for p in cfg["presets"] if p["name"] != name]
    if len(cfg["presets"]) == before:
        return jsonify({"error": f"Preset '{name}' not found"}), 404
    ctx.save_config(cfg)
    return jsonify({"message": f"Preset '{name}' deleted"})


# --- Stats ---

@bp.route("/stats", methods=["GET"])
def get_stats():
    """Return aggregated job statistics.
    ---
    tags: [Stats]
    responses:
      200:
        description: Statistics
    """
    from stats import _DURATION_BUCKETS

    ctx = _ctx()
    data = ctx.stats.get_stats()
    at = data["all_time"]

    avg_run = (
        at["run_seconds_total"] / at["run_seconds_count"]
        if at.get("run_seconds_count")
        else 0
    )

    weekly_sorted = sorted(data["weekly"].items(), key=lambda x: x[0])
    weeks_param = request.args.get("weeks", "12")
    if weeks_param == "all":
        weekly = [{"week": k, **v} for k, v in weekly_sorted]
    else:
        try:
            n = max(1, int(weeks_param))
        except ValueError:
            n = 12
        weekly = [{"week": k, **v} for k, v in weekly_sorted[-n:]]

    buckets = [
        {"label": label, "count": data["run_duration_buckets"].get(label, 0)}
        for label, _, _ in _DURATION_BUCKETS
    ]

    per_preset = []
    for name, pp in data["per_preset"].items():
        count = pp.get("run_seconds_count", 0)
        avg = pp["run_seconds_total"] / count if count else 0
        per_preset.append({
            "name": name,
            "total": pp.get("total", 0),
            "finished": pp.get("finished", 0),
            "failed": pp.get("failed", 0),
            "cancelled": pp.get("cancelled", 0),
            "avg_run_seconds": avg,
            "min_run_seconds": pp.get("min_run_seconds"),
            "max_run_seconds": pp.get("max_run_seconds"),
            "last_run": pp.get("last_run"),
        })
    per_preset.sort(key=lambda x: x["total"], reverse=True)

    return jsonify({
        "all_time": {**at, "avg_run_seconds": avg_run},
        "weekly": weekly,
        "run_duration_buckets": buckets,
        "per_preset": per_preset,
    })


# --- Legacy alias (kept for tests / existing links) ---

@bp.route("/job/<job_id>/log", methods=["GET"])
def legacy_job_log(job_id):
    return job_log(job_id)


# --- Helpers ---

def _build_job(preset_name, preset_cmd, url, cwd):
    job_id = str(uuid.uuid4())
    command = preset_cmd.replace("{url}", url) if "{url}" in preset_cmd else preset_cmd
    return {
        "id": job_id,
        "command": command,
        "preset": preset_name if preset_name != "custom" else "Custom Command",
        "input_arg": url,
        "status": "queued",
        "created_at": datetime.now().isoformat(),
        "cwd": cwd,
        "log_file": f"{job_id}.log",
    }


def _clone_for_rerun(original):
    new_id = str(uuid.uuid4())
    clone = original.copy()
    clone.update(
        {
            "id": new_id,
            "status": "queued",
            "created_at": datetime.now().isoformat(),
            "start_time": None,
            "end_time": None,
            "exit_code": None,
            "log_file": f"{new_id}.log",
        }
    )
    return clone
