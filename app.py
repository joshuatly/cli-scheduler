import os
import json
import uuid
import time
import threading
import subprocess
import queue
import psutil
import platform
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from flasgger import Swagger
from storage import JsonJobStore, SqliteJobStore

from utils import get_app_paths, ensure_directories

app = Flask(__name__)

swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "CLI Scheduler API",
        "description": "REST API for submitting and managing CLI jobs",
        "version": "1.0.0",
    },
    "basePath": "/",
    "schemes": ["http"],
    "consumes": ["application/json"],
    "produces": ["application/json"],
    "definitions": {
        "Job": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "command": {"type": "string"},
                "preset": {"type": "string"},
                "input_arg": {"type": "string"},
                "status": {"type": "string", "enum": ["queued", "running", "finished", "failed", "cancelled"]},
                "created_at": {"type": "string", "format": "date-time"},
                "start_time": {"type": "string", "format": "date-time"},
                "end_time": {"type": "string", "format": "date-time"},
                "exit_code": {"type": "integer"},
                "cwd": {"type": "string"},
                "log_file": {"type": "string"},
            }
        },
        "Preset": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"},
                "description": {"type": "string"},
                "cwd": {"type": "string"},
            }
        },
        "Error": {
            "type": "object",
            "properties": {
                "error": {"type": "string"}
            }
        }
    }
}

swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec_1",
            "route": "/apispec_1.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/docs",
}

swagger = Swagger(app, template=swagger_template, config=swagger_config)

# --- Configuration & Globals ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATHS = get_app_paths()
ensure_directories(PATHS)

CONFIG_FILE = str(PATHS['config_file'])
LOGS_DIR = str(PATHS['logs_dir'])

# Ensure logs directory exists - handled by ensure_directories
# os.makedirs(LOGS_DIR, exist_ok=True)

# Job Queue for sequential execution
job_queue = queue.Queue()
# Lock for config file access only (Jobs are handled by Storage)
data_lock = threading.Lock()
# Map to store running processes for cancellation
process_lock = threading.Lock()
RUNNING_PROCESSES = {}

# --- Helper Functions ---

def load_config():
    with data_lock:
        if not os.path.exists(CONFIG_FILE):
            # Fallback: Check for legacy config in project root
            legacy_config = os.path.join(BASE_DIR, 'config.json')
            if os.path.exists(legacy_config):
                try:
                    with open(legacy_config, 'r') as f:
                        print(f" * Loading legacy config from: {legacy_config}")
                        return json.load(f)
                except:
                    pass
            
            # Default config allowing local network
            default_config = {
                "presets": [
                    {
                        "name": "yt-dlp Audio",
                        "command": "yt-dlp -x --audio-format mp3 \"{url}\"",
                        "description": "Download audio as MP3 (Default)"
                    },
                    {
                        "name": "Echo Test",
                        "command": "echo \"{url}\"",
                        "description": "Simple echo for testing"
                    }
                ], 
                "storage_type": "json", 
                "allowed_ips": ["127.0.0.1", "192.168.*"]
            }
            
            # Create default config file
            try:
                print(f" * Creating default config at: {CONFIG_FILE}")
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(default_config, f, indent=4)
            except Exception as e:
                print(f" ! Failed to create default config: {e}")
                
            return default_config

        try:
            with open(CONFIG_FILE, 'r') as f:
                print(f" * Loading config from: {CONFIG_FILE}")
                return json.load(f)
        except:
             print(f" * Config not found at {CONFIG_FILE}, using defaults")
             return {
                "presets": [], 
                "storage_type": "json", 
                "allowed_ips": ["127.0.0.1", "192.168.*"]
            }

def get_version_info():
    try:
        # Get the short commit hash
        commit_hash = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], stderr=subprocess.DEVNULL).decode('utf-8').strip()
        return f"v-{commit_hash}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "v-dev"


# Initialize Storage
config = load_config()
STORAGE_TYPE = config.get('storage_type', 'json')
ALLOWED_IPS = config.get('allowed_ips', ['127.0.0.1', '192.168.*'])

# Support overrides for paths
if 'log_dir' in config:
    LOGS_DIR = os.path.expanduser(config['log_dir'])
    os.makedirs(LOGS_DIR, exist_ok=True)
else:
    LOGS_DIR = str(PATHS['logs_dir'])

if STORAGE_TYPE == 'sqlite':
    if 'db_path' in config:
        DB_FILE = os.path.expanduser(config['db_path'])
        # Ensure directory for overridden DB path exists
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    else:
        DB_FILE = str(PATHS['db_file'])
    STORAGE = SqliteJobStore(DB_FILE)
else:
    if 'db_path' in config:
        JOBS_FILE = os.path.expanduser(config['db_path'])
        # Ensure directory for overridden JSON path exists
        os.makedirs(os.path.dirname(JOBS_FILE), exist_ok=True)
    else:
        # Backward compat or default
        JOBS_FILE = str(PATHS['jobs_file'])
    STORAGE = JsonJobStore(JOBS_FILE)

print(f" * Logs Directory: {LOGS_DIR}")
if 'DB_FILE' in locals():
    print(f" * Database File: {DB_FILE}")
else:
    print(f" * Jobs File: {JOBS_FILE}")


# --- Template Filters ---
@app.template_filter('time_ago')
def time_ago_filter(s):
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s)
        now = datetime.now()
        diff = now - dt
        
        seconds = diff.total_seconds()
        if seconds < 60:
            return "Just now"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            return f"{minutes}m ago"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f"{hours}h ago"
        else:
            days = int(seconds // 86400)
            return f"{days}d ago"
    except Exception:
        return s

@app.template_filter('duration')
def duration_filter(start_str, end_str=None):
    if not start_str:
        return ""
    try:
        if isinstance(start_str, (int, float)):
             seconds = int(start_str)
        else:
            start = datetime.fromisoformat(start_str)
            if end_str:
                end = datetime.fromisoformat(end_str)
            else:
                end = datetime.now()
            
            diff = end - start
            seconds = int(diff.total_seconds())
        
        if seconds < 0: return "0s"
        
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            m = seconds // 60
            s = seconds % 60
            return f"{m}m {s}s"
        else:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h}h {m}m"
    except Exception:
        return ""

# --- Middleware ---
def is_ip_allowed(client_ip, allowed_list):
    if not allowed_list: return False # Deny all if empty
    for allowed in allowed_list:
        if allowed == client_ip:
            return True
        if allowed.endswith('*'):
            prefix = allowed[:-1]
            if client_ip.startswith(prefix):
                return True
    return False

@app.before_request
def limit_remote_addr():
    # Helper to get real IP if behind proxy (optional, but good practice)
    # For now, trust remote_addr as per requirements
    client_ip = request.remote_addr
    if not is_ip_allowed(client_ip, ALLOWED_IPS):
        abort(403)  # Forbidden

@app.context_processor
def inject_footer():
    config = load_config()
    return dict(footer_text=config.get('footer_text', ''), version=get_version_info())

# Helper to save config safely
def save_config(config):
    with data_lock:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)

def get_job(job_id):
    return STORAGE.get_job(job_id)

def update_job_status(job_id, status, exit_code=None):
    updates = {'status': status}
    if exit_code is not None:
        updates['exit_code'] = exit_code
    
    if status == 'running':
        updates['start_time'] = datetime.now().isoformat()
    elif status in ['finished', 'failed']:
        updates['end_time'] = datetime.now().isoformat()
    
    STORAGE.update_job(job_id, updates)

# --- Background Worker ---

# --- Background Worker ---

def worker():
    while True:
        try:
            job_id = job_queue.get()
            if job_id is None:
                break
            
            job = get_job(job_id)
            if not job:
                job_queue.task_done()
                continue
                
            # Refetch status to ensure we don't re-run if it changed (unlikely but safe)
            if job['status'] not in ['queued', 'running']:
                 job_queue.task_done()
                 continue

            update_job_status(job_id, 'running')
            
            command = job['command']
            log_file_path = os.path.join(LOGS_DIR, f"{job_id}.log")
            
            try:
                with open(log_file_path, 'w') as log_file:
                    # Run the command
                    # merging stdout and stderr for simplicity in logs
                    
                    # Create a clean environment for the subprocess
                    env = os.environ.copy()
                    # Remove VIRTUAL_ENV to prevent tools like uv from using the scheduler's venv
                    env.pop('VIRTUAL_ENV', None)
                    
                    # Inject HOSTNAME if not present (common issue in some shells/environments)
                    if 'HOSTNAME' not in env:
                        env['HOSTNAME'] = platform.node()
                    
                    process = subprocess.Popen(
                        command, 
                        shell=True, 
                        stdout=log_file, 
                        stderr=subprocess.STDOUT,
                        cwd=job.get('cwd', BASE_DIR),
                        env=env
                    )
                    
                    with process_lock:
                        RUNNING_PROCESSES[job_id] = process
                        
                    process.wait()
                    
                    final_status = 'finished' if process.returncode == 0 else 'failed'
                    
                    # If it was cancelled, status might already be 'cancelled' by the API
                    # But if we killed it, returncode is likely non-zero.
                    # Let's check if it's still running in our map or if status changed externally?
                    # Actually, if we kill it, process.wait() returns.
                    # We should check the current status in DB before overwriting with 'failed' 
                    # if it was 'cancelled'.
                    
                    current_job = get_job(job_id)
                    if current_job and current_job.get('status') == 'cancelled':
                        final_status = 'cancelled'
                    
                    update_job_status(job_id, final_status, process.returncode)
                    
            except Exception as e:
                with open(log_file_path, 'a') as log_file:
                    log_file.write(f"\n\nSystem Error: {str(e)}\n")
                update_job_status(job_id, 'failed', -1)
            finally:
                with process_lock:
                    RUNNING_PROCESSES.pop(job_id, None)
            
            job_queue.task_done()
        except Exception as e:
            print(f"Worker thread error: {e}")
            # Prevent tight loop if persistent error
            time.sleep(1)

def init_queue():
    """Load queued jobs from file into memory queue on startup."""
    jobs = STORAGE.get_all_jobs()
    for job in jobs:
        if job['status'] == 'queued':
            print(f"Re-queueing job {job['id']}")
            job_queue.put(job['id'])
        elif job['status'] == 'running':
            # Mark interrupted jobs as failed
            print(f"Marking interrupted job {job['id']} as failed")
            update_job_status(job['id'], 'failed', -1)
            # Append to log
            log_path = os.path.join(LOGS_DIR, job['log_file'])
            if os.path.exists(log_path):
                with open(log_path, 'a') as f:
                    f.write("\n\n[System] Job interrupted by server restart.")

# Initialize queue before starting worker
init_queue()

# Start worker thread
worker_thread = threading.Thread(target=worker, daemon=True)
worker_thread.start()

# --- Routes ---

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    jobs = STORAGE.get_all_jobs()
    # Sort by submission time descending
    jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    total_jobs = len(jobs)
    total_pages = (total_jobs + per_page - 1) // per_page
    
    # Slice jobs for current page
    start = (page - 1) * per_page
    end = start + per_page
    current_jobs = jobs[start:end]
    
    # Calculate page range for pagination UI
    page_numbers = []
    if total_pages > 0:
        # Window size +/- 2
        start_p = max(1, page - 2)
        end_p = min(total_pages, page + 2)
        
        # Always allow getting back to 1
        if start_p > 1:
            page_numbers.append(1)
            if start_p > 2:
                page_numbers.append(None) # Ellipsis
                
        for p in range(start_p, end_p + 1):
            page_numbers.append(p)
            
        if end_p < total_pages:
            if end_p < total_pages - 1:
                page_numbers.append(None) # Ellipsis
            page_numbers.append(total_pages)
    
    return render_template('index.html', jobs=current_jobs, page=page, total_pages=total_pages, total_jobs=total_jobs, page_numbers=page_numbers)

@app.route('/submit', methods=['GET', 'POST'])
def submit():
    config = load_config()
    if request.method == 'POST':
        preset_name = request.form.get('preset')
        raw_urls = request.form.get('urls')
        cwd = request.form.get('cwd', os.path.expanduser("~"))
        
        preset_cmd = ""
        
        if preset_name == "custom":
             preset_cmd = request.form.get('custom_command')
             if not preset_cmd:
                 return "Missing custom command", 400
        else:
            # Find preset command template
            preset_cmd = next((p['command'] for p in config['presets'] if p['name'] == preset_name), None)
            if not preset_cmd:
                return "Invalid Preset", 400

        urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
        
        # If no URLs provided but we have a custom command that might not need inputs?
        # The prompt implies "Ability to enter many URL", so let's stick to generating jobs per line.
        # But if the user just wants to run a single command "dir", they might type "dir" in custom command
        # and nothing in URLs. We should support that single-run case.
        if not urls and "{url}" not in preset_cmd:
            # Run once without input arg substitution
             urls = [""] 


        new_jobs = []
        
        for url in urls:
            job_id = str(uuid.uuid4())
            # Simple replacement of {url} placeholder
            if "{url}" in preset_cmd:
                full_command = preset_cmd.replace("{url}", url)
            else:
                full_command = preset_cmd
            
            job = {
                "id": job_id,
                "command": full_command,
                "preset": preset_name if preset_name != 'custom' else 'Custom Command',
                "input_arg": url,
                "status": "queued",
                "created_at": datetime.now().isoformat(),
                "cwd": cwd,
                "log_file": f"{job_id}.log"
            }
            new_jobs.append(job)
            STORAGE.add_job(job)
            job_queue.put(job_id)
            
        # save_jobs(jobs) # Not needed as we added individually
        return redirect(url_for('index'))
        
    # GET request - check for autoqueue
    if request.args.get('autoqueue') == '1':
        preset_name = request.args.get('preset')
        cwd = request.args.get('cwd', os.path.expanduser("~"))
        raw_urls = request.args.get('urls', '')

        preset_cmd = next((p['command'] for p in config['presets'] if p['name'] == preset_name), None)
        if not preset_cmd:
            return "Invalid Preset", 400

        urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
        if not urls and "{url}" not in preset_cmd:
            urls = [""]

        for url in urls:
            job_id = str(uuid.uuid4())
            full_command = preset_cmd.replace("{url}", url) if "{url}" in preset_cmd else preset_cmd
            job = {
                "id": job_id,
                "command": full_command,
                "preset": preset_name,
                "input_arg": url,
                "status": "queued",
                "created_at": datetime.now().isoformat(),
                "cwd": cwd,
                "log_file": f"{job_id}.log"
            }
            STORAGE.add_job(job)
            job_queue.put(job_id)

        return redirect(url_for('index'))

    # GET request - check for pre-fill
    job_id = request.args.get('retry_job_id')
    default_values = {
        "preset": "",
        "cwd": os.path.expanduser("~"),
        "urls": "",
        "custom_command": ""
    }

    if job_id:
        job = get_job(job_id)
        if job:
            if job.get('preset') == 'Custom Command':
                default_values["preset"] = 'custom'
                default_values["custom_command"] = job.get('command')
            else:
                default_values["preset"] = job.get('preset', '')

            default_values["cwd"] = job.get('cwd', os.path.expanduser("~"))
            default_values["urls"] = job.get('input_arg', '')
    else:
        preset = request.args.get('preset', '')
        cwd = request.args.get('cwd', os.path.expanduser("~"))
        urls = request.args.get('urls', '')

        if preset:
            default_values["preset"] = preset
        default_values["cwd"] = cwd
        default_values["urls"] = urls

    return render_template('submit.html', presets=config['presets'], default_values=default_values, default_cwd=os.path.expanduser("~"))

@app.route('/presets', methods=['GET'])
def presets_list():
    config = load_config()
    return render_template('presets.html', presets=config['presets'])

@app.route('/presets/add', methods=['POST'])
def add_preset():
    name = request.form.get('name')
    command = request.form.get('command')
    description = request.form.get('description')
    
    if not name or not command:
        return "Missing fields", 400
        
    config = load_config()
    # Check duplicate
    if any(p['name'] == name for p in config['presets']):
        return "Preset name already exists", 400
        
    config['presets'].append({
        "name": name,
        "command": command,
        "description": description,
        "cwd": request.form.get('cwd', '')
    })
    
    save_config(config)
        
    return redirect(url_for('presets_list'))
    
@app.route('/presets/edit/<name>', methods=['GET'])
def edit_preset_form(name):
    config = load_config()
    preset = next((p for p in config['presets'] if p['name'] == name), None)
    if not preset:
        return "Preset not found", 404
    return render_template('edit_preset.html', preset=preset)

@app.route('/presets/update', methods=['POST'])
def update_preset():
    original_name = request.form.get('original_name')
    name = request.form.get('name')
    command = request.form.get('command')
    description = request.form.get('description')
    
    if not original_name or not name or not command:
        return "Missing fields", 400
        
    config = load_config()
    
    # Check if name is taken by ANOTHER preset (not self)
    if name != original_name and any(p['name'] == name for p in config['presets']):
        return "Preset name already exists", 400
        
    for p in config['presets']:
        if p['name'] == original_name:
            p['name'] = name
            p['command'] = command
            p['description'] = description
            p['cwd'] = request.form.get('cwd', '')
            break
    
    save_config(config)
        
    return redirect(url_for('presets_list'))

@app.route('/presets/delete', methods=['POST'])
def delete_preset():
    name = request.form.get('name')
    if not name:
        return "Missing name", 400
        
    config = load_config()
    config['presets'] = [p for p in config['presets'] if p['name'] != name]
    
    save_config(config)
        
    return redirect(url_for('presets_list'))

@app.route('/job/<job_id>')
def job_details(job_id):
    job = get_job(job_id)
    if not job:
        return "Job not found", 404
        
    log_content = ""
    log_path = os.path.join(LOGS_DIR, job['log_file'])
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            log_content = f.read()
            
    return render_template('job.html', job=job, log_content=log_content)

@app.route('/api/job/<job_id>/log')
def job_log_api(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    log_path = os.path.join(LOGS_DIR, job['log_file'])
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            return jsonify({"content": f.read()})
    return jsonify({"content": ""})

@app.route('/rerun/<job_id>', methods=['POST'])
def rerun_job(job_id):
    original_job = get_job(job_id)
    if not original_job:
        return "Job not found", 404
        
    new_job_id = str(uuid.uuid4())
    new_job = original_job.copy()
    new_job['id'] = new_job_id
    new_job['status'] = "queued"
    new_job['created_at'] = datetime.now().isoformat()
    new_job['start_time'] = None
    new_job['end_time'] = None
    new_job['exit_code'] = None
    new_job['log_file'] = f"{new_job_id}.log"
    
    jobs = STORAGE.get_all_jobs() # Not strictly needed if we just append, but logic below was appending
    STORAGE.add_job(new_job)
    job_queue.put(new_job_id)
    
    return redirect(url_for('index'))

@app.route('/job/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    job = get_job(job_id)
    if not job:
        return "Job not found", 404
        
    status = job.get('status')
    
    if status in ['finished', 'failed', 'cancelled']:
        return "Job already finished", 400
        
    if status == 'queued':
        update_job_status(job_id, 'cancelled')
        # We can't easily remove from queue.Queue, but worker handles it by checking status.
        return redirect(url_for('job_details', job_id=job_id))
        
    if status == 'running':
        # Try to terminate process
        update_job_status(job_id, 'cancelled') # Mark as cancelled first
        
        with process_lock:
            process = RUNNING_PROCESSES.get(job_id)
            if process:
                try:
                    # Use psutil to kill entire process tree
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)
                    
                    # Terminate children first
                    for child in children:
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                            
                    # Terminate parent
                    try:
                        parent.terminate()
                    except psutil.NoSuchProcess:
                        pass
                    
                    # Wait for termination and force kill if needed
                    gone, alive = psutil.wait_procs(children + [parent], timeout=3)
                    for p in alive:
                        try:
                            p.kill()
                        except psutil.NoSuchProcess:
                            pass
                            
                except psutil.NoSuchProcess:
                    pass # Already gone
                except Exception as e:
                    print(f"Error killing job {job_id}: {e}")
                    
    return redirect(url_for('job_details', job_id=job_id))

# --- REST API Routes ---

@app.route('/api/jobs', methods=['GET'])
def api_list_jobs():
    """List all jobs with optional filtering and pagination.
    ---
    tags:
      - Jobs
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
              items:
                $ref: '#/definitions/Job'
            page:
              type: integer
            per_page:
              type: integer
            total:
              type: integer
            total_pages:
              type: integer
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status_filter = request.args.get('status')

    jobs = STORAGE.get_all_jobs()
    jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    if status_filter:
        jobs = [j for j in jobs if j.get('status') == status_filter]

    total = len(jobs)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    page_jobs = jobs[start:start + per_page]

    return jsonify({
        "jobs": page_jobs,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    })


@app.route('/api/jobs', methods=['POST'])
def api_submit_jobs():
    """Submit one or more jobs.
    ---
    tags:
      - Jobs
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - preset
          properties:
            preset:
              type: string
              description: Preset name (must match a preset defined in config)
            urls:
              type: array
              items:
                type: string
              description: List of input arguments substituted for {url}
    responses:
      201:
        description: Jobs created
        schema:
          type: object
          properties:
            jobs:
              type: array
              items:
                $ref: '#/definitions/Job'
      400:
        description: Bad request
        schema:
          $ref: '#/definitions/Error'
    """
    data = request.get_json(silent=True) or {}
    cfg = load_config()

    preset_name = data.get('preset')
    urls = data.get('urls', [])

    if not preset_name:
        return jsonify({"error": "Missing 'preset' field"}), 400

    matched_preset = next((p for p in cfg['presets'] if p['name'] == preset_name), None)
    if not matched_preset:
        return jsonify({"error": f"Preset '{preset_name}' not found"}), 400

    preset_cmd = matched_preset['command']
    cwd = matched_preset.get('cwd') or os.path.expanduser("~")

    if not urls and "{url}" not in preset_cmd:
        urls = [""]

    if not urls:
        return jsonify({"error": "No URLs provided for a preset that requires {url}"}), 400

    new_jobs = []
    for url in urls:
        job_id = str(uuid.uuid4())
        full_command = preset_cmd.replace("{url}", url) if "{url}" in preset_cmd else preset_cmd
        job = {
            "id": job_id,
            "command": full_command,
            "preset": preset_name,
            "input_arg": url,
            "status": "queued",
            "created_at": datetime.now().isoformat(),
            "cwd": cwd,
            "log_file": f"{job_id}.log",
        }
        new_jobs.append(job)
        STORAGE.add_job(job)
        job_queue.put(job_id)

    return jsonify({"jobs": new_jobs}), 201


@app.route('/api/jobs/<job_id>', methods=['GET'])
def api_get_job(job_id):
    """Get a single job by ID.
    ---
    tags:
      - Jobs
    parameters:
      - name: job_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Job details
        schema:
          $ref: '#/definitions/Job'
      404:
        description: Job not found
        schema:
          $ref: '#/definitions/Error'
    """
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
def api_cancel_job(job_id):
    """Cancel a queued or running job.
    ---
    tags:
      - Jobs
    parameters:
      - name: job_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Job cancelled
        schema:
          $ref: '#/definitions/Job'
      400:
        description: Job already finished
        schema:
          $ref: '#/definitions/Error'
      404:
        description: Job not found
        schema:
          $ref: '#/definitions/Error'
    """
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    status = job.get('status')
    if status in ['finished', 'failed', 'cancelled']:
        return jsonify({"error": "Job already finished"}), 400

    update_job_status(job_id, 'cancelled')

    if status == 'running':
        with process_lock:
            process = RUNNING_PROCESSES.get(job_id)
            if process:
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
                    gone, alive = psutil.wait_procs(children + [parent], timeout=3)
                    for p in alive:
                        try:
                            p.kill()
                        except psutil.NoSuchProcess:
                            pass
                except psutil.NoSuchProcess:
                    pass
                except Exception as e:
                    print(f"Error killing job {job_id}: {e}")

    return jsonify(get_job(job_id))


@app.route('/api/jobs/<job_id>/rerun', methods=['POST'])
def api_rerun_job(job_id):
    """Rerun a job by creating a new copy of it.
    ---
    tags:
      - Jobs
    parameters:
      - name: job_id
        in: path
        type: string
        required: true
    responses:
      201:
        description: New job created
        schema:
          $ref: '#/definitions/Job'
      404:
        description: Original job not found
        schema:
          $ref: '#/definitions/Error'
    """
    original_job = get_job(job_id)
    if not original_job:
        return jsonify({"error": "Job not found"}), 404

    new_job_id = str(uuid.uuid4())
    new_job = original_job.copy()
    new_job['id'] = new_job_id
    new_job['status'] = "queued"
    new_job['created_at'] = datetime.now().isoformat()
    new_job['start_time'] = None
    new_job['end_time'] = None
    new_job['exit_code'] = None
    new_job['log_file'] = f"{new_job_id}.log"

    STORAGE.add_job(new_job)
    job_queue.put(new_job_id)

    return jsonify(new_job), 201


@app.route('/api/jobs/<job_id>/log', methods=['GET'])
def api_job_log(job_id):
    """Get the log output for a job.
    ---
    tags:
      - Jobs
    parameters:
      - name: job_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Job log content
        schema:
          type: object
          properties:
            content:
              type: string
      404:
        description: Job not found
        schema:
          $ref: '#/definitions/Error'
    """
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    log_path = os.path.join(LOGS_DIR, job['log_file'])
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            return jsonify({"content": f.read()})
    return jsonify({"content": ""})


@app.route('/api/presets', methods=['GET'])
def api_list_presets():
    """List all presets.
    ---
    tags:
      - Presets
    responses:
      200:
        description: List of presets
        schema:
          type: object
          properties:
            presets:
              type: array
              items:
                $ref: '#/definitions/Preset'
    """
    cfg = load_config()
    return jsonify({"presets": cfg['presets']})


@app.route('/api/presets', methods=['POST'])
def api_create_preset():
    """Create a new preset.
    ---
    tags:
      - Presets
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [name, command]
          properties:
            name:
              type: string
            command:
              type: string
            description:
              type: string
            cwd:
              type: string
    responses:
      201:
        description: Preset created
        schema:
          $ref: '#/definitions/Preset'
      400:
        description: Bad request
        schema:
          $ref: '#/definitions/Error'
    """
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    command = data.get('command', '').strip()

    if not name or not command:
        return jsonify({"error": "Missing required fields: name, command"}), 400

    cfg = load_config()
    if any(p['name'] == name for p in cfg['presets']):
        return jsonify({"error": f"Preset '{name}' already exists"}), 400

    preset = {
        "name": name,
        "command": command,
        "description": data.get('description', ''),
        "cwd": data.get('cwd', ''),
    }
    cfg['presets'].append(preset)
    save_config(cfg)

    return jsonify(preset), 201


@app.route('/api/presets/<name>', methods=['PUT'])
def api_update_preset(name):
    """Update an existing preset.
    ---
    tags:
      - Presets
    parameters:
      - name: name
        in: path
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
            command:
              type: string
            description:
              type: string
            cwd:
              type: string
    responses:
      200:
        description: Preset updated
        schema:
          $ref: '#/definitions/Preset'
      400:
        description: Bad request
        schema:
          $ref: '#/definitions/Error'
      404:
        description: Preset not found
        schema:
          $ref: '#/definitions/Error'
    """
    data = request.get_json(silent=True) or {}
    cfg = load_config()

    preset = next((p for p in cfg['presets'] if p['name'] == name), None)
    if not preset:
        return jsonify({"error": f"Preset '{name}' not found"}), 404

    new_name = data.get('name', name).strip()
    if new_name != name and any(p['name'] == new_name for p in cfg['presets']):
        return jsonify({"error": f"Preset '{new_name}' already exists"}), 400

    preset['name'] = new_name
    if 'command' in data:
        preset['command'] = data['command']
    if 'description' in data:
        preset['description'] = data['description']
    if 'cwd' in data:
        preset['cwd'] = data['cwd']

    save_config(cfg)
    return jsonify(preset)


@app.route('/api/presets/<name>', methods=['DELETE'])
def api_delete_preset(name):
    """Delete a preset.
    ---
    tags:
      - Presets
    parameters:
      - name: name
        in: path
        type: string
        required: true
    responses:
      200:
        description: Preset deleted
        schema:
          type: object
          properties:
            message:
              type: string
      404:
        description: Preset not found
        schema:
          $ref: '#/definitions/Error'
    """
    cfg = load_config()
    original_count = len(cfg['presets'])
    cfg['presets'] = [p for p in cfg['presets'] if p['name'] != name]

    if len(cfg['presets']) == original_count:
        return jsonify({"error": f"Preset '{name}' not found"}), 404

    save_config(cfg)
    return jsonify({"message": f"Preset '{name}' deleted"})


if __name__ == '__main__':
    # Threaded=True is default for Flask, but good to be explicit
    # app.run(debug=True, port=5000)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
