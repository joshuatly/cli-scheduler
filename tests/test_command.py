import os
import subprocess
import sys

import pytest

import app
from backend.command import UnsafeInputError, render_command

posix_only = pytest.mark.skipif(os.name == "nt", reason="runs /bin/sh")

PAYLOADS = [
    "https://evil.example/$(touch${IFS}PWNED)",
    "https://evil.example/`touch PWNED`",
    'x"; touch PWNED; echo "',
    "x'; touch PWNED; echo '",
    "x; touch PWNED",
    "x && touch PWNED",
    "x | touch PWNED",
    "x\ntouch PWNED",
    "x\\\"; touch PWNED; echo \\\"",
]

TEMPLATES = [
    "printf '%s' {url}",
    'printf \'%s\' "{url}"',
    "printf '%s' '{url}'",
    'printf \'%s\' "prefix-{url}-suffix"',
]


def _run(command, cwd):
    return subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)


@posix_only
@pytest.mark.parametrize("template", TEMPLATES)
@pytest.mark.parametrize("payload", PAYLOADS)
def test_posix_payload_is_passed_literally(tmp_path, template, payload):
    result = _run(render_command(template, payload, windows=False), tmp_path)
    assert not (tmp_path / "PWNED").exists()
    expected = payload
    if "prefix-" in template:
        expected = f"prefix-{payload}-suffix"
    assert result.stdout == expected


@posix_only
def test_posix_normal_url_roundtrips(tmp_path):
    url = "https://www.youtube.com/watch?v=abc&list=x%20y#t=1"
    for template in TEMPLATES[:3]:
        assert _run(render_command(template, url, windows=False), tmp_path).stdout == url


def test_posix_plain_values_are_unchanged():
    # Existing presets keep producing the same commands for ordinary input.
    assert render_command("echo {url}", "input_arg", windows=False) == "echo input_arg"
    assert render_command('yt-dlp "{url}"', "https://a.b/c", windows=False) == 'yt-dlp "https://a.b/c"'


def test_no_placeholder_returns_template():
    assert render_command("echo hi", "$(x)", windows=False) == "echo hi"


def test_multiple_placeholders():
    assert render_command('a {url} "{url}"', "$x", windows=False) == "a '$x' \"\\$x\""


def test_escaped_quote_in_template_does_not_flip_state():
    # \" outside quotes is a literal quote, so {url} is still unquoted.
    assert render_command('echo \\" {url}', "$x", windows=False) == "echo \\\" '$x'"


def test_windows_bare_and_quoted():
    assert render_command("yt-dlp {url}", "https://a.b/c&d", windows=True) == 'yt-dlp "https://a.b/c&d"'
    assert render_command('yt-dlp "{url}"', "https://a.b/c&d", windows=True) == 'yt-dlp "https://a.b/c&d"'


def test_windows_percent_is_escaped_outside_quotes():
    assert render_command('x "{url}"', "a%PATH%b", windows=True) == 'x "a"^%"PATH"^%"b"'


def test_windows_trailing_backslash_before_quote():
    assert render_command("x {url}", "C:\\dir\\", windows=True) == 'x "C:\\dir\\\\"'


@pytest.mark.parametrize("bad", ['a"b', "a\nb", "a\rb"])
def test_windows_rejects_unquotable_input(bad):
    with pytest.raises(UnsafeInputError):
        render_command("x {url}", bad, windows=True)


@pytest.mark.skipif(sys.platform != "win32", reason="runs cmd.exe")
@pytest.mark.parametrize("payload", ["a&echo PWNED", "a|echo PWNED", "%COMSPEC%", "a^b", "(a)<b>"])
def test_windows_payload_is_passed_literally(tmp_path, payload):
    cmd = render_command('python -c "import sys;print(sys.argv[1])" {url}', payload)
    result = _run(cmd, tmp_path)
    assert result.stdout.strip() == payload


def test_api_rejects_whole_batch_on_unsafe_input(client, mock_env, monkeypatch):
    import backend.command as command

    monkeypatch.setattr(command.os, "name", "nt")
    rv = client.post("/api/jobs", json={"preset": "TestPreset", "urls": ["ok", 'bad"']})
    assert rv.status_code == 400
    assert app.STORAGE.get_all_jobs() == []


@posix_only
def test_api_stores_escaped_command(client, mock_env):
    rv = client.post("/api/jobs", json={"preset": "TestPreset", "urls": ["$(touch PWNED)"]})
    assert rv.status_code == 201
    job = rv.get_json()["jobs"][0]
    assert job["input_arg"] == "$(touch PWNED)"
    assert job["command"] == "echo '$(touch PWNED)'"


@posix_only
def test_autoqueue_stores_escaped_command(client, mock_env):
    rv = client.get("/submit?autoqueue=1&preset=TestPreset&urls=%24(id)")
    assert rv.status_code == 302
    assert app.STORAGE.get_all_jobs()[0]["command"] == "echo '$(id)'"
