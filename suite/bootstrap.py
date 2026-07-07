"""`suite deps` + the Ansible server bootstrap `suite apply` runs (ADR-002/037).

  - deps         install the Python tooling + Ansible collections this CLI and
                 the bootstrap need (pip + ansible-galaxy);
  - provision()  turn a bare Debian server into a ready single-node K3s cluster
                 via the Ansible playbook — called by `suite apply` when the
                 server was never bootstrapped or the firewall flags changed.
"""

from __future__ import annotations

import json
import shutil

from .errors import SuiteError
from .process import run

ANSIBLE_DIR = "ansible"
PLAYBOOK = "bootstrap.yml"
REQUIREMENTS = "requirements.txt"
REQUIREMENTS_DEV = "requirements-dev.txt"
ANSIBLE_REQUIREMENTS = "ansible/requirements.yml"
MOLECULE_REQUIREMENTS = "molecule/requirements.yml"


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
    print("\n==> Dependencies installed.")


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
