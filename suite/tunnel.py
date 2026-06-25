"""Background SSH tunnel to the server K8s API on :6443 (ADR-014). Reuses an
existing tunnel if the port is already open, so re-runs don't stack tunnels."""

from __future__ import annotations

import contextlib
import socket
import subprocess
import time

from .errors import SuiteError


def port_open(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


@contextlib.contextmanager
def tunnel(ssh_target, *, port=6443):
    if port_open(port):
        print(f"  reusing existing tunnel on :{port}")
        yield
        return
    print(f"  opening SSH tunnel :{port} -> {ssh_target}")
    proc = subprocess.Popen(["ssh", "-N", "-L", f"{port}:127.0.0.1:{port}", ssh_target])
    try:
        for _ in range(30):
            if port_open(port):
                break
            time.sleep(1)
        else:
            raise SuiteError(f"SSH tunnel to {ssh_target} never opened :{port}")
        yield
    finally:
        proc.terminate()
