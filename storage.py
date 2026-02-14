import os
import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

class JobStore(ABC):
    @abstractmethod
    def get_all_jobs(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def add_job(self, job: Dict[str, Any]):
        pass

    @abstractmethod
    def update_job(self, job_id: str, updates: Dict[str, Any]):
        pass

class JsonJobStore(JobStore):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.lock = threading.Lock()
        
    def _load(self) -> List[Dict[str, Any]]:
        with self.lock:
            if not os.path.exists(self.file_path):
                return []
            try:
                with open(self.file_path, 'r') as f:
                    return json.load(f)
            except:
                return []

    def _save(self, jobs: List[Dict[str, Any]]):
        with self.lock:
            with open(self.file_path, 'w') as f:
                json.dump(jobs, f, indent=4)

    def get_all_jobs(self) -> List[Dict[str, Any]]:
        return self._load()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        jobs = self._load()
        for job in jobs:
            if job['id'] == job_id:
                return job
        return None

    def add_job(self, job: Dict[str, Any]):
        # We need to lock the whole read-modify-write cycle
        # But _load and _save have their own locks which might cause issues if we aren't careful
        # Ideally we should expose a 'transaction' or just lock around the high level op
        # Simpler: use the same lock object for everything
        with self.lock:
            if os.path.exists(self.file_path):
                try:
                    with open(self.file_path, 'r') as f:
                        jobs = json.load(f)
                except:
                    jobs = []
            else:
                jobs = []
            
            jobs.append(job)
            
            with open(self.file_path, 'w') as f:
                json.dump(jobs, f, indent=4)

    def update_job(self, job_id: str, updates: Dict[str, Any]):
         with self.lock:
            if os.path.exists(self.file_path):
                try:
                    with open(self.file_path, 'r') as f:
                        jobs = json.load(f)
                except:
                    return # Can't update if corrupt/missing
            else:
                return

            for job in jobs:
                if job['id'] == job_id:
                    job.update(updates)
                    break
            
            with open(self.file_path, 'w') as f:
                json.dump(jobs, f, indent=4)

class SqliteJobStore(JobStore):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock() # SQLite checks same-thread access by default, but we use strict threading in app
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    command TEXT,
                    preset TEXT,
                    input_arg TEXT,
                    status TEXT,
                    created_at TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    exit_code INTEGER,
                    cwd TEXT,
                    log_file TEXT
                )
            ''')
            conn.commit()
        finally:
            conn.close()

    def _row_to_dict(self, row):
        return {
            "id": row[0],
            "command": row[1],
            "preset": row[2],
            "input_arg": row[3],
            "status": row[4],
            "created_at": row[5],
            "start_time": row[6],
            "end_time": row[7],
            "exit_code": row[8],
            "cwd": row[9],
            "log_file": row[10]
        }

    def get_all_jobs(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            cursor = conn.execute('SELECT * FROM jobs')
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            cursor = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None
        finally:
            conn.close()

    def add_job(self, job: Dict[str, Any]):
        conn = self._get_conn()
        try:
            conn.execute('''
                INSERT INTO jobs (id, command, preset, input_arg, status, created_at, start_time, end_time, exit_code, cwd, log_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job['id'],
                job['command'],
                job.get('preset'),
                job.get('input_arg'),
                job.get('status'),
                job.get('created_at'),
                job.get('start_time'),
                job.get('end_time'),
                job.get('exit_code'),
                job.get('cwd'),
                job.get('log_file')
            ))
            conn.commit()
        finally:
            conn.close()

    def update_job(self, job_id: str, updates: Dict[str, Any]):
        conn = self._get_conn()
        try:
            # Dynamically build update query
            fields = []
            values = []
            for k, v in updates.items():
                fields.append(f"{k} = ?")
                values.append(v)
            
            values.append(job_id)
            
            sql = f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?"
            conn.execute(sql, values)
            conn.commit()
        finally:
            conn.close()
