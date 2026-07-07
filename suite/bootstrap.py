"""`suite deps` + the Ansible server bootstrap `suite apply` runs (ADR-002/037).

  - deps         install the Python tooling + Ansible collections this CLI and
                 the bootstrap need (pip + ansible-galaxy);
  - provision()  turn a bare Debian server into a ready single-node K3s cluster
                 via the Ansible playbook — called by `suite apply` when the
                 server was never bootstrapped or the firewall flags changed.
"""

from __future__ import annotations

import io
import json
import os
import platform
import re
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

from .errors import SuiteError
from .process import run

ANSIBLE_DIR = "ansible"
PLAYBOOK = "bootstrap.yml"
REQUIREMENTS = "requirements.txt"
REQUIREMENTS_DEV = "requirements-dev.txt"
ANSIBLE_REQUIREMENTS = "ansible/requirements.yml"
MOLECULE_REQUIREMENTS = "molecule/requirements.yml"

# Single source of the helm-diff pin: read the version straight from the CI action
# so the workstation install and CI stay consistent and Renovate tracks one line.
CLUSTER_TOOLS_ACTION = ".github/actions/setup-cluster-tools/action.yml"


def run_deps(args):
    _require(["pip", "ansible-galaxy"])
    print("\n==> Installing Python tooling + Ansible collections")
    # Runtime deps for the `python -m suite` fallback. The short `suite` command
    # is installed separately and globally with `pipx install --editable .` so it
    # is on PATH in any shell, not just an activated venv (ADR-040).
    run(["pip", "install", "-r", REQUIREMENTS], step="pip install (cli)")
    run(["pip", "install", "-r", REQUIREMENTS_DEV], step="pip install (dev)")
    run(["ansible-galaxy", "collection", "install", "-r", ANSIBLE_REQUIREMENTS],
        step="ansible-galaxy (app)")
    run(["ansible-galaxy", "collection", "install", "-r", MOLECULE_REQUIREMENTS],
        step="ansible-galaxy (test harness)")
    install_helm_diff()
    print("\n==> Dependencies installed.")


def install_helm_diff():
    """Install the pinned helm-diff plugin into helm's plugin dir. `suite apply`
    runs `helmfile apply`/`diff`, which shell out to `helm diff` (an external
    plugin — helm has no built-in `diff`). The release tarball ships the prebuilt
    binary, so extract it straight in: no install hook, no provenance step (helm
    discovers any valid plugin dir at runtime). This mirrors the CI action."""
    if not shutil.which("helm"):
        print("  helm not on PATH yet — skipping the helm-diff plugin "
              "(install helm, then re-run `suite deps`)")
        return
    version = _helm_diff_version()
    if _helm_diff_installed(version):
        print(f"  helm-diff {version} already installed")
        return
    plugins_dir = _helm_plugins_dir()
    asset = _helm_diff_asset()
    url = (f"https://github.com/databus23/helm-diff/releases/download/"
           f"{version}/{asset}")
    print(f"\n==> Installing the helm-diff {version} plugin ({asset})")
    # The tarball's top-level dir is `diff/`, so it lands at <plugins>/diff.
    shutil.rmtree(os.path.join(plugins_dir, "diff"), ignore_errors=True)
    os.makedirs(plugins_dir, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ownsuite-suite-deps"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (pinned github release URL)
        data = resp.read()
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        try:
            tf.extractall(plugins_dir, filter="data")
        except TypeError:  # Python < 3.11.4: no `filter` kwarg
            tf.extractall(plugins_dir)


def _helm_diff_version():
    text = Path(CLUSTER_TOOLS_ACTION).read_text()
    m = re.search(r'HELMDIFF_VERSION:\s*"(v[\d.]+)"', text)
    if not m:
        raise SuiteError(
            f"could not read HELMDIFF_VERSION from {CLUSTER_TOOLS_ACTION}")
    return m.group(1)


def _helm_diff_installed(version):
    proc = run(["helm", "diff", "version"], capture=True, check=False,
               step="helm diff version")
    return proc.returncode == 0 and version.lstrip("v") in (proc.stdout or "")


def _helm_plugins_dir():
    """helm's effective plugin dir (honours $HELM_PLUGINS, else the OS default)."""
    proc = run(["helm", "env", "HELM_PLUGINS"], capture=True, step="helm env")
    return (proc.stdout or "").strip().strip('"')


def _helm_diff_asset():
    """The release asset for this workstation, e.g. helm-diff-macos-arm64.tgz
    (helm-diff names macOS assets `macos`, not `darwin`)."""
    os_name = "macos" if sys.platform == "darwin" else "linux"
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    return f"helm-diff-{os_name}-{arch}.tgz"


def provision(*, check=False, extra_vars=None):
    """Provision the server via Ansible. ``check=True`` is a no-op dry-run
    (--check --diff). ``extra_vars`` (e.g. the enable_meet/enable_mailbox
    firewall flags) are passed as JSON so booleans stay typed."""
    _require(["ansible-playbook"])
    extra = ["--check", "--diff"] if check else []
    if extra_vars:
        extra += ["-e", json.dumps(extra_vars)]
    verb = "Dry-running" if check else "Running"
    print(f"\n==> {verb} the server bootstrap (ansible)")
    run(["ansible-playbook", PLAYBOOK, *extra], cwd=ANSIBLE_DIR,
        step="ansible-playbook bootstrap")


def _require(tools):
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SuiteError(f"missing required tools on PATH: {', '.join(missing)}")
