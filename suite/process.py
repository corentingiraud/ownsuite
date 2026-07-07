"""Run a command (list-argv, never a shell string). Streams output by default;
raises SuiteError with the tail on failure."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence

from .errors import SuiteError


def preflight(tools, *, ssh="", no_tunnel=False, helm_diff=False):
    """Fail fast when a required CLI tool is missing. `ssh` is only needed when a
    tunnel will actually be opened (an SSH target and no --no-tunnel). Set
    `helm_diff=True` for commands that run `helmfile apply`/`diff`."""
    tools = list(tools)
    if ssh and not no_tunnel:
        tools.append("ssh")
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SuiteError(f"missing required tools on PATH: {', '.join(missing)}")
    # helm-diff is a helm PLUGIN, not a PATH binary: `helmfile apply`/`diff` shell
    # out to `helm diff`. Verify it here so a missing plugin fails fast with an
    # actionable message instead of helmfile's opaque `unknown command "diff"`.
    if helm_diff and not _helm_diff_available():
        raise SuiteError(
            "the helm-diff plugin is missing (`helm diff` is unavailable) — "
            "run `suite deps` to install it."
        )


def _helm_diff_available():
    try:
        return subprocess.run(
            ["helm", "diff", "version"],
            capture_output=True, text=True, check=False,
        ).returncode == 0
    except OSError:
        return False


def run(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    capture: bool = False,
    check: bool = True,
    step: str | None = None,
    input_text: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    argv = list(argv)
    full_env = {**os.environ, **dict(env)} if env else None
    proc = subprocess.run(
        argv, env=full_env, cwd=cwd, text=True, input=input_text,
        capture_output=capture, timeout=timeout, check=False,
    )
    if check and proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or ""))[-2000:] if capture else ""
        raise SuiteError(
            f"{step or argv[0]}: failed (rc={proc.returncode}): "
            f"{' '.join(argv)}\n{tail}".rstrip()
        )
    return proc
