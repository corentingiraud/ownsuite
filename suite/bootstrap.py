"""`suite deps` / `suite bootstrap` / `suite check` — workstation tooling and
server provisioning (ADR-037).

These were `make deps` / `make bootstrap` / `make check`; they are user-facing
operations, so they belong on the `suite` CLI (the `make` surface is now CI/dev
shorthand only). Each is a thin wrapper around the tools the operator already has:

  - deps      install the Python tooling + Ansible collections this CLI and the
              bootstrap need (pip + ansible-galaxy);
  - bootstrap provision a bare server into a ready single-node K3s cluster, via the
              Ansible playbook (ADR-002);
  - check     dry-run that bootstrap (--check --diff) — applies nothing.

`suite install` reuses ``provision()`` for its server-provisioning step instead of
shelling out to `make`.
"""

from __future__ import annotations

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


def run_bootstrap(args):
    provision()


def run_check(args):
    provision(check=True)


def provision(*, check=False):
    """Provision the server via Ansible. ``check=True`` is a no-op dry-run
    (--check --diff). Reused by `suite install` for its bootstrap step."""
    _require(["ansible-playbook"])
    extra = ["--check", "--diff"] if check else []
    verb = "Dry-running" if check else "Running"
    print(f"\n==> {verb} the server bootstrap (ansible)")
    run(["ansible-playbook", PLAYBOOK, *extra], cwd=ANSIBLE_DIR,
        step="ansible-playbook bootstrap")


def _require(tools):
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SuiteError(f"missing required tools on PATH: {', '.join(missing)}")
