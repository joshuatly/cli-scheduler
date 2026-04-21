import json
import os
import subprocess
import threading

DEFAULT_CONFIG = {
    "presets": [
        {
            "name": "yt-dlp Audio",
            "command": "yt-dlp -x --audio-format mp3 \"{url}\"",
            "description": "Download audio as MP3 (Default)",
        },
        {
            "name": "Echo Test",
            "command": "echo \"{url}\"",
            "description": "Simple echo for testing",
        },
    ],
    "storage_type": "json",
    "allowed_ips": ["127.0.0.1", "192.168.*"],
}

_lock = threading.Lock()


def load_config(config_file, base_dir=None):
    with _lock:
        if not os.path.exists(config_file):
            legacy = os.path.join(base_dir, "config.json") if base_dir else None
            if legacy and os.path.exists(legacy):
                try:
                    with open(legacy, "r") as f:
                        print(f" * Loading legacy config from: {legacy}")
                        return json.load(f)
                except Exception:
                    pass

            try:
                print(f" * Creating default config at: {config_file}")
                with open(config_file, "w") as f:
                    json.dump(DEFAULT_CONFIG, f, indent=4)
            except Exception as e:
                print(f" ! Failed to create default config: {e}")
            return dict(DEFAULT_CONFIG)

        try:
            with open(config_file, "r") as f:
                print(f" * Loading config from: {config_file}")
                return json.load(f)
        except Exception:
            print(f" * Config not found at {config_file}, using defaults")
            return {
                "presets": [],
                "storage_type": "json",
                "allowed_ips": ["127.0.0.1", "192.168.*"],
            }


def save_config(config_file, config):
    with _lock:
        with open(config_file, "w") as f:
            json.dump(config, f, indent=4)


def get_version_info():
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        )
        return f"v-{commit.decode('utf-8').strip()}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "v-dev"
