"""Background SSH tunnel to the server K8s API on :6443 (ADR-014). Reuses an
existing tunnel if the port is already open, so re-runs don't stack tunnels."""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import time
from pathlib import Path

from .errors import SuiteError

# The bootstrap fetches the cluster kubeconfig here (ansible/kubeconfig — the
# Ansible run's cwd is the `ansible/` dir, ADR-002). It points at 127.0.0.1:6443,
# which this tunnel forwards. Resolve it against the repo root (this package's parent)
# rather than the cwd, so `suite` finds it when run from a subdirectory too.
FETCHED_KUBECONFIG = str(Path(__file__).resolve().parents[1] / "ansible" / "kubeconfig")


def port_open(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def maybe(ssh_target, *, no_tunnel=False):
    """The tunnel context, or a no-op when tunnelling is skipped — no SSH target, or
    the operator opted into the ambient KUBECONFIG with --no-tunnel."""
    if no_tunnel or not ssh_target:
        return contextlib.nullcontext()
    return tunnel(ssh_target)


def run_tunnel(args):
    """`suite tunnel` — hold the managed SSH tunnel open for ad-hoc kubectl/k9s/etc.
    Reuses an existing tunnel, sets KUBECONFIG for this process, and prints the
    export line to paste into the shell where you'll run kubectl. Ctrl-C to close."""
    from . import process, spec

    ctx = spec.load_context()
    if not ctx.ssh:
        raise SuiteError("no server SSH target — set `server.ssh` in suite.yaml.")
    process.preflight(["ssh"], ssh=ctx.ssh)
    with maybe(ctx.ssh):
        print(f"\n  export KUBECONFIG={os.environ.get('KUBECONFIG', FETCHED_KUBECONFIG)}")
        print("  tunnel open — Ctrl-C to close.\n")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("  closing tunnel.")


@contextlib.contextmanager
def tunnel(ssh_target, *, port=6443):
    # Point kubectl/helmfile at the fetched kubeconfig unless the operator already
    # exported their own. It must be ABSOLUTE: helmfile changes cwd to resolve charts,
    # so a relative KUBECONFIG resolves wrong and helm falls back to localhost:8080
    # ("cluster unreachable"). setdefault respects an explicit export (e.g. CI).
    if os.path.exists(FETCHED_KUBECONFIG):
        os.environ.setdefault("KUBECONFIG", os.path.abspath(FETCHED_KUBECONFIG))
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
