"""Run a command (list-argv, never a shell string). Streams output by default;
raises SuiteError with the tail on failure."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence

from .errors import SuiteError


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
