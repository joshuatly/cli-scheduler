"""Safe substitution of user input into preset command templates.

Presets are run with ``shell=True``, so the ``{url}`` value must be escaped
for the shell that will parse it. Escaping depends on where the placeholder
sits in the template (bare, inside '...' or inside "..."), so the template is
scanned and each ``{url}`` is escaped for its own quoting context. Presets
written as ``cmd {url}``, ``cmd "{url}"`` and ``cmd '{url}'`` all stay valid.
"""
import os
import shlex

PLACEHOLDER = "{url}"


class UnsafeInputError(ValueError):
    """The input cannot be safely embedded in a command on this platform."""


def render_command(template, value, windows=None):
    """Return ``template`` with every ``{url}`` replaced by a shell-safe ``value``."""
    if PLACEHOLDER not in template:
        return template
    if windows is None:
        windows = os.name == "nt"
    quote = _quote_cmd if windows else _quote_posix
    return _substitute(template, value, quote, windows)


def _substitute(template, value, quote, windows):
    out = []
    state = None  # None, "'" or '"'
    i = 0
    n = len(template)
    while i < n:
        if template.startswith(PLACEHOLDER, i):
            out.append(quote(value, state))
            i += len(PLACEHOLDER)
            continue
        ch = template[i]
        if windows:
            # cmd.exe only knows double quotes and toggles on every one.
            if ch == '"':
                state = None if state else '"'
        elif state == "'":
            if ch == "'":
                state = None
        elif ch == "\\" and i + 1 < n:
            # Backslash escapes the next character outside quotes and inside "...".
            out.append(template[i : i + 2])
            i += 2
            continue
        elif ch in ("'", '"') and state is None:
            state = ch
        elif ch == '"' and state == '"':
            state = None
        out.append(ch)
        i += 1
    return "".join(out)


def _quote_posix(value, state):
    if state is None:
        return shlex.quote(value)
    if state == "'":
        # Close the quote, add an escaped quote, reopen.
        return value.replace("'", "'\\''")
    # Inside double quotes only these four characters are special.
    for ch in ("\\", "$", "`", '"'):
        value = value.replace(ch, "\\" + ch)
    return value


def _quote_cmd(value, state):
    # cmd.exe has no way to escape a double quote inside a quoted string.
    if '"' in value or "\n" in value or "\r" in value:
        raise UnsafeInputError("Input may not contain double quotes or line breaks")
    # Inside quotes cmd still expands %VAR%; '^%' only works outside quotes,
    # so each % is emitted between a closing and a reopening quote.
    segments = [_protect_trailing_backslashes(s) for s in value.split("%")]
    body = '"^%"'.join(segments)
    if state == '"':
        return body
    return '"' + body + '"'


def _protect_trailing_backslashes(segment):
    # Program argv parsing treats \" as a literal quote; double any backslashes
    # that end up directly before a quote we emit.
    stripped = segment.rstrip("\\")
    return stripped + "\\" * (2 * (len(segment) - len(stripped)))
