from flask import abort, request


def is_ip_allowed(client_ip, allowed_list):
    if not allowed_list:
        return False
    for allowed in allowed_list:
        if allowed == client_ip:
            return True
        if allowed.endswith("*") and client_ip.startswith(allowed[:-1]):
            return True
    return False


def register(app, get_allowed_ips):
    @app.before_request
    def _limit_remote_addr():
        if not is_ip_allowed(request.remote_addr, get_allowed_ips()):
            abort(403)
