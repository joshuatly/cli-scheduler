"""Backend package for CLI Scheduler.

The Flask app is constructed in app.py (at the project root) so that legacy
imports (`import app`, `app.STORAGE`, `app.job_queue`, ...) keep working for
tests and tooling. This package hosts the modular pieces: config loading,
background worker, template filters, middleware, and route blueprints.
"""
