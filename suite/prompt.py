"""Interactive prompts for the guided installer, wrapping `questionary`.

One place imports the library, so swapping it (or degrading it) is a single-file
change. The import is lazy — importing this module is always safe (CI /
non-interactive paths never call these functions and so never need questionary).
`questionary` needs a TTY; callers only reach here in interactive mode. A cancelled
prompt (Ctrl-C / EOF) returns None from `.ask()`, surfaced as KeyboardInterrupt so
`cli.main` prints "Aborted." like everywhere else.
"""

from __future__ import annotations

from .errors import SuiteError


def _q():
    try:
        import questionary
    except ImportError as exc:  # `suite deps` installs it (requirements.txt)
        raise SuiteError(
            "questionary is required for interactive prompts — run `suite deps` "
            "(or `pip install questionary`), or pass --non-interactive."
        ) from exc
    return questionary


def _ask(question):
    answer = question.ask()
    if answer is None:  # user hit Ctrl-C / EOF
        raise KeyboardInterrupt
    return answer


def text(msg, default="", validate=None):
    return _ask(_q().text(msg, default=default or "", validate=validate)).strip()


def select(msg, choices, default=None):
    return _ask(_q().select(msg, choices=choices, default=default))


def confirm(msg, default=True):
    return _ask(_q().confirm(msg, default=default))


def password(msg):
    """Hidden input (no echo) — for pasting the secret seed, never stored."""
    return _ask(_q().password(msg)).strip()


def checkbox(msg, choices, checked=()):
    """Multi-select. `choices` are labels; `checked` pre-ticks a subset."""
    q = _q()
    opts = [q.Choice(c, checked=c in checked) for c in choices]
    return _ask(q.checkbox(msg, choices=opts))
