SWAGGER_TEMPLATE = {
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
                "status": {
                    "type": "string",
                    "enum": ["queued", "running", "finished", "failed", "cancelled"],
                },
                "created_at": {"type": "string", "format": "date-time"},
                "start_time": {"type": "string", "format": "date-time"},
                "end_time": {"type": "string", "format": "date-time"},
                "exit_code": {"type": "integer"},
                "cwd": {"type": "string"},
                "log_file": {"type": "string"},
            },
        },
        "Preset": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"},
                "description": {"type": "string"},
                "cwd": {"type": "string"},
            },
        },
        "Error": {
            "type": "object",
            "properties": {"error": {"type": "string"}},
        },
    },
}

SWAGGER_CONFIG = {
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
