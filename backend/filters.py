from datetime import datetime


def time_ago(s):
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s)
        seconds = (datetime.now() - dt).total_seconds()
        if seconds < 60:
            return "Just now"
        if seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        if seconds < 86400:
            return f"{int(seconds // 3600)}h ago"
        return f"{int(seconds // 86400)}d ago"
    except Exception:
        return s


def duration(start_str, end_str=None):
    if not start_str:
        return ""
    try:
        if isinstance(start_str, (int, float)):
            seconds = int(start_str)
        else:
            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str) if end_str else datetime.now()
            seconds = int((end - start).total_seconds())

        if seconds < 0:
            return "0s"
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    except Exception:
        return ""


def register(app):
    app.add_template_filter(time_ago, "time_ago")
    app.add_template_filter(duration, "duration")
