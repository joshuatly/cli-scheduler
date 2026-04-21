"""Runtime context shared between routes and the worker.

Attributes resolve dynamically against the root `app` module so tests that
monkeypatch `app.STORAGE`, `app.LOGS_DIR`, `app.CONFIG_FILE`, etc. keep
working without having to know about the blueprint layout.
"""


class SchedulerContext:
    def __init__(self):
        self._app_module = None
        self.runner = None

    def bind(self, app_module):
        self._app_module = app_module

    @property
    def storage(self):
        return self._app_module.STORAGE

    @property
    def logs_dir(self):
        return self._app_module.LOGS_DIR

    @property
    def base_dir(self):
        return self._app_module.BASE_DIR

    def load_config(self):
        return self._app_module.load_config()

    def save_config(self, cfg):
        return self._app_module.save_config(cfg)
