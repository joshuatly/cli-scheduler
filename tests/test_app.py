import json
import os
import time
import app
from storage import JsonJobStore

def test_index_route(client, mock_env):
    """Test dashboard loads"""
    rv = client.get('/')
    assert rv.status_code == 200
    assert b'CLI Scheduler' in rv.data

def test_presets_api(client, mock_env):
    """Test preset management"""
    # List
    rv = client.get('/presets')
    assert rv.status_code == 200
    assert b'TestPreset' in rv.data
    
    # Add
    rv = client.post('/presets/add', data={
        "name": "NewPreset",
        "command": "cmd",
        "description": "desc"
    }, follow_redirects=True)
    assert rv.status_code == 200
    assert b'NewPreset' in rv.data
    
    # Verify file update
    config = app.load_config()
    assert any(p['name'] == 'NewPreset' for p in config['presets'])

def test_submit_job(client, mock_env):
    """Test job submission"""
    rv = client.post('/submit', data={
        "preset": "TestPreset",
        "cwd": ".",
        "urls": "input_arg"
    }, follow_redirects=True)
    assert rv.status_code == 200
    
    # Check job created
    jobs = app.STORAGE.get_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]['preset'] == 'TestPreset'
    assert jobs[0]['input_arg'] == 'input_arg'
    # Check if {url} was replaced
    assert jobs[0]['command'] == 'echo input_arg'

def test_custom_command(client, mock_env):
    """Test custom command submission"""
    rv = client.post('/submit', data={
        "preset": "custom",
        "custom_command": "echo custom_val",
        "cwd": ".",
        "urls": ""
    }, follow_redirects=True)
    assert rv.status_code == 200
    
    jobs = app.STORAGE.get_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]['command'] == 'echo custom_val'
    assert jobs[0]['preset'] == 'Custom Command'

def test_worker_execution(mock_env):
    """Test backend worker logic directly"""
    # We can't easily test the threaded worker started by app.py due to global state
    # But we can verify subprocess logic if we mock subprocess or run a real echo
    
    # Create a job manually
    job_id = "test_job_1"
    job = {
        "id": job_id,
        "command": "echo hello_world",
        "status": "queued",
        "cwd": mock_env['base'],
        "log_file": f"{job_id}.log"
    }
    
    # Save job using app method (thread safe)
    app.STORAGE.add_job(job)
        
    # Put in queue
    import queue
    # We need to use the app's global queue
    app.job_queue.put(job_id)
    
    # Wait for worker to process
    for _ in range(20): # Try for 4 seconds
        time.sleep(0.2)
        jobs = app.STORAGE.get_all_jobs()
            
        if jobs[0]['status'] in ['finished', 'failed']:
            break
            
    updated_job = jobs[0]
    # Debug info if failed
    if updated_job['status'] != 'finished':
        print(f"DEBUG: Job status is {updated_job['status']}")
        # Check if log file exists and content
        log_path = os.path.join(mock_env['logs'], f"{job_id}.log")
        if os.path.exists(log_path):
             with open(log_path, 'r') as f:
                 print(f"DEBUG: Log content: {f.read()}")
        else:
             print("DEBUG: Log file not found")

    assert updated_job['status'] == 'finished'
    assert updated_job['exit_code'] == 0
    
    # Check log
    log_path = os.path.join(mock_env['logs'], f"{job_id}.log")
    assert os.path.exists(log_path)
    with open(log_path, 'r') as f:
        content = f.read()
    assert "hello_world" in content

def test_ip_restriction(client):
    """Test IP restriction middleware"""
    # Allowed Localhost
    rv = client.get('/', environ_base={'REMOTE_ADDR': '127.0.0.1'})
    assert rv.status_code == 200
    
    # Allowed LAN
    rv = client.get('/', environ_base={'REMOTE_ADDR': '192.168.1.5'})
    assert rv.status_code == 200
    
    # Denied Public/Other
    rv = client.get('/', environ_base={'REMOTE_ADDR': '10.0.0.1'})
    assert rv.status_code == 403
    
    rv = client.get('/', environ_base={'REMOTE_ADDR': '8.8.8.8'})
    assert rv.status_code == 403

def test_default_cwd(client, mock_env):
    """Test default CWD is user home"""
    rv = client.post('/submit', data={
        "preset": "TestPreset",
        # "cwd" omitted
        "urls": "input_arg"
    }, follow_redirects=True)
    assert rv.status_code == 200
    
    jobs = app.STORAGE.get_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]['cwd'] == os.path.expanduser("~")

def test_preset_cwd(client, mock_env):
    """Test preset with custom CWD"""
    # Add preset with CWD
    rv = client.post('/presets/add', data={
        "name": "CWDPreset",
        "command": "cmd",
        "description": "desc",
        "cwd": "/tmp/custom_cwd"
    }, follow_redirects=True)
    assert rv.status_code == 200
    
    # Submit job using this preset
    # Note: The form submit in real app uses JS to fill cwd field. 
    # In test, we must simulate that by sending cwd in data, 
    # OR we rely on backend to pull from preset if not provided? 
    # Wait, my backend implementation in submit() uses request.form.get('cwd', default).
    # If the JS fills it, it sends it. 
    # If I want to test the END-TO-END flow including JS, I can't with test_client.
    # But I can test that IF the form sends it (cpu JS), it works. 
    # AND I should probably update backend to ALSO check preset if CWD is missing/default?
    # No, the requirement is "presets can also customize the cwd". 
    # If the user selects preset, JS updates field. User can then edit it. 
    # So the form submission WILL contain the value. 
    # So I just test that if I submit with that value, it works. 
    # BUT explicitly, I want to verify the preset was saved with CWD.
    
    config = app.load_config()
    preset = next(p for p in config['presets'] if p['name'] == 'CWDPreset')
    assert preset['cwd'] == '/tmp/custom_cwd'
    
    # Simulate valid form submission where JS acted
    rv = client.post('/submit', data={
        "preset": "CWDPreset",
        "cwd": "/tmp/custom_cwd",
        "urls": "arg"
    }, follow_redirects=True)
    assert rv.status_code == 200
    
    jobs = app.STORAGE.get_all_jobs()
    assert jobs[0]['cwd'] == '/tmp/custom_cwd'
