import os
import json
import uuid
import time
import threading
import subprocess
import queue
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from storage import JsonJobStore, SqliteJobStore

app = Flask(__name__)

# --- Configuration & Globals ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Ensure logs directory exists
os.makedirs(LOGS_DIR, exist_ok=True)

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
            return {"presets": [], "storage_type": "json", "allowed_ips": ["127.0.0.1"]}
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"presets": [], "storage_type": "json", "allowed_ips": ["127.0.0.1"]}

# Initialize Storage
config = load_config()
STORAGE_TYPE = config.get('storage_type', 'json')
ALLOWED_IPS = config.get('allowed_ips', ['127.0.0.1', '192.168.*'])

if STORAGE_TYPE == 'sqlite':
    DB_FILE = os.path.join(BASE_DIR, 'jobs.db')
    STORAGE = SqliteJobStore(DB_FILE)
else:
    JOBS_FILE = os.path.join(BASE_DIR, 'jobs.json')
    STORAGE = JsonJobStore(JOBS_FILE)

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
    return dict(footer_text=config.get('footer_text', ''))

# Helper to save config safely
def save_config(config):
    with data_lock:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)



            
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
                # For custom commands, we need to try and reverse engineer the template/command?
                # Or just put the full command in the custom box and leave inputs empty?
                # Simpler: just put the full executed command as the custom template and leave URL empty.
                default_values["custom_command"] = job.get('command')
                # If we had separate input_arg, we could try to put it back, but 
                # for simplicity in generic case, if it was custom, we just let them edit the full command string.
                default_values["custom_command"] = job.get('command')
                # If we had separate input_arg, we could try to put it back, but 
                # for simplicity in generic case, if it was custom, we just let them edit the full command string.
            else:
                default_values["preset"] = job.get('preset', '')
            
            default_values["cwd"] = job.get('cwd', os.path.expanduser("~"))
            default_values["urls"] = job.get('input_arg', '')
            
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
                    # process.terminate() # SIGTERM
                    # On Windows, terminate() is kill(). On Linux, it's SIGTERM.
                    # Since user mentioned "waiting for keyboard input", simple terminate might work.
                    # If it's really stuck, might need kill().
                    import signal
                    process.send_signal(signal.SIGTERM) # Try friendly first
                    
                    # Give it a moment? No, api should return fast.
                    # Worker thread runs process.wait(), which should return once terminated.
                except Exception as e:
                    print(f"Error killing job {job_id}: {e}")
                    
    return redirect(url_for('job_details', job_id=job_id))

if __name__ == '__main__':
    # Threaded=True is default for Flask, but good to be explicit
    # app.run(debug=True, port=5000)
    app.run(host='0.0.0.0', port=5000, debug=True)
