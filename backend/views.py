"""HTML view blueprint.

Templates now render shells that are hydrated by the frontend JS via the JSON
API. Form POSTs stay server-rendered so non-JS clients and the existing test
suite keep working.
"""
import os
import uuid
from datetime import datetime

from flask import Blueprint, current_app, redirect, render_template, request, url_for


bp = Blueprint("views", __name__)


def _ctx():
    return current_app.extensions["cli_scheduler"]


@bp.route("/")
def index():
    ctx = _ctx()
    presets = ctx.load_config().get("presets", [])
    return render_template("index.html", presets=presets)


@bp.route("/submit", methods=["GET", "POST"])
def submit():
    ctx = _ctx()
    cfg = ctx.load_config()

    if request.method == "POST":
        return _handle_submit_post(cfg, ctx)

    if request.args.get("autoqueue") == "1":
        return _handle_autoqueue(cfg, ctx)

    return render_template(
        "submit.html",
        presets=cfg["presets"],
        default_values=_prefill_values(ctx),
        default_cwd=os.path.expanduser("~"),
    )


@bp.route("/presets", methods=["GET"])
def presets_list():
    return render_template("presets.html", presets=_ctx().load_config()["presets"])


@bp.route("/presets/add", methods=["POST"])
def add_preset():
    ctx = _ctx()
    name = request.form.get("name")
    command = request.form.get("command")
    description = request.form.get("description")
    if not name or not command:
        return "Missing fields", 400

    cfg = ctx.load_config()
    if any(p["name"] == name for p in cfg["presets"]):
        return "Preset name already exists", 400

    cfg["presets"].append(
        {
            "name": name,
            "command": command,
            "description": description,
            "cwd": request.form.get("cwd", ""),
        }
    )
    ctx.save_config(cfg)
    return redirect(url_for("views.presets_list"))


@bp.route("/presets/edit/<name>", methods=["GET"])
def edit_preset_form(name):
    preset = next((p for p in _ctx().load_config()["presets"] if p["name"] == name), None)
    if not preset:
        return "Preset not found", 404
    return render_template("edit_preset.html", preset=preset)


@bp.route("/presets/update", methods=["POST"])
def update_preset():
    ctx = _ctx()
    original_name = request.form.get("original_name")
    name = request.form.get("name")
    command = request.form.get("command")
    description = request.form.get("description")
    if not original_name or not name or not command:
        return "Missing fields", 400

    cfg = ctx.load_config()
    if name != original_name and any(p["name"] == name for p in cfg["presets"]):
        return "Preset name already exists", 400

    for p in cfg["presets"]:
        if p["name"] == original_name:
            p["name"] = name
            p["command"] = command
            p["description"] = description
            p["cwd"] = request.form.get("cwd", "")
            break
    ctx.save_config(cfg)
    return redirect(url_for("views.presets_list"))


@bp.route("/presets/delete", methods=["POST"])
def delete_preset():
    ctx = _ctx()
    name = request.form.get("name")
    if not name:
        return "Missing name", 400
    cfg = ctx.load_config()
    cfg["presets"] = [p for p in cfg["presets"] if p["name"] != name]
    ctx.save_config(cfg)
    return redirect(url_for("views.presets_list"))


@bp.route("/stats")
def stats():
    return render_template("stats.html")


@bp.route("/job/<job_id>")
def job_details(job_id):
    ctx = _ctx()
    job = ctx.storage.get_job(job_id)
    if not job:
        return "Job not found", 404

    log_content = ""
    log_path = os.path.join(ctx.logs_dir, job["log_file"])
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            log_content = f.read()
    return render_template("job.html", job=job, log_content=log_content)


@bp.route("/rerun/<job_id>", methods=["POST"])
def rerun_job(job_id):
    ctx = _ctx()
    original = ctx.storage.get_job(job_id)
    if not original:
        return "Job not found", 404

    new_job = _clone_for_rerun(original)
    ctx.storage.add_job(new_job)
    ctx.runner.submit(new_job["id"])
    return redirect(url_for("views.index"))


@bp.route("/job/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    ctx = _ctx()
    job = ctx.storage.get_job(job_id)
    if not job:
        return "Job not found", 404

    status = job.get("status")
    if status in ("finished", "failed", "cancelled"):
        return "Job already finished", 400

    ctx.storage.update_job(
        job_id, {"status": "cancelled", "end_time": datetime.now().isoformat()}
    )
    if status == "running":
        ctx.runner.cancel(job_id)
    return redirect(url_for("views.job_details", job_id=job_id))


# --- Helpers ---

def _handle_submit_post(cfg, ctx):
    preset_name = request.form.get("preset")
    raw_urls = request.form.get("urls") or ""
    cwd = request.form.get("cwd", os.path.expanduser("~"))

    if preset_name == "custom":
        preset_cmd = request.form.get("custom_command")
        if not preset_cmd:
            return "Missing custom command", 400
    else:
        preset_cmd = next(
            (p["command"] for p in cfg["presets"] if p["name"] == preset_name), None
        )
        if not preset_cmd:
            return "Invalid Preset", 400

    urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
    if not urls and "{url}" not in preset_cmd:
        urls = [""]

    for url in urls:
        job = _build_job(preset_name, preset_cmd, url, cwd)
        ctx.storage.add_job(job)
        ctx.runner.submit(job["id"])
    return redirect(url_for("views.index"))


def _handle_autoqueue(cfg, ctx):
    preset_name = request.args.get("preset")
    cwd = request.args.get("cwd", os.path.expanduser("~"))
    raw_urls = request.args.get("urls", "")

    preset_cmd = next(
        (p["command"] for p in cfg["presets"] if p["name"] == preset_name), None
    )
    if not preset_cmd:
        return "Invalid Preset", 400

    urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
    if not urls and "{url}" not in preset_cmd:
        urls = [""]

    for url in urls:
        job = _build_job(preset_name, preset_cmd, url, cwd)
        ctx.storage.add_job(job)
        ctx.runner.submit(job["id"])
    return redirect(url_for("views.index"))


def _prefill_values(ctx):
    default_values = {
        "preset": "",
        "cwd": os.path.expanduser("~"),
        "urls": "",
        "custom_command": "",
    }

    job_id = request.args.get("retry_job_id")
    if job_id:
        job = ctx.storage.get_job(job_id)
        if job:
            if job.get("preset") == "Custom Command":
                default_values["preset"] = "custom"
                default_values["custom_command"] = job.get("command")
            else:
                default_values["preset"] = job.get("preset", "")
            default_values["cwd"] = job.get("cwd", os.path.expanduser("~"))
            default_values["urls"] = job.get("input_arg", "")
        return default_values

    default_values["preset"] = request.args.get("preset", "")
    default_values["cwd"] = request.args.get("cwd", os.path.expanduser("~"))
    default_values["urls"] = request.args.get("urls", "")
    return default_values


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
