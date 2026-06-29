"""Unit tests for the `suite deps` / `bootstrap` / `check` verbs (suite.bootstrap)
— the subprocess and tool-discovery boundaries are mocked, so the exact commands
(and the --check --diff dry-run) are asserted without touching pip/Ansible or a
real server."""

from types import SimpleNamespace

import pytest

from suite import bootstrap
from suite.errors import SuiteError


def _patch_run(monkeypatch):
    """Record every `run(argv, cwd=..., step=...)` and make every tool 'present'."""
    calls = []
    monkeypatch.setattr(bootstrap.shutil, "which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr(bootstrap, "run",
                        lambda argv, **kw: calls.append((list(argv), kw.get("cwd"))))
    return calls


def test_deps_installs_pip_then_ansible_collections(monkeypatch):
    calls = _patch_run(monkeypatch)
    bootstrap.run_deps(SimpleNamespace())
    argvs = [c[0] for c in calls]
    assert argvs[0] == ["pip", "install", "-r", bootstrap.REQUIREMENTS_DEV]
    assert argvs[1][:3] == ["ansible-galaxy", "collection", "install"]
    assert argvs[1][-1] == bootstrap.ANSIBLE_REQUIREMENTS
    assert argvs[2][-1] == bootstrap.MOLECULE_REQUIREMENTS


def test_bootstrap_runs_playbook_in_ansible_dir_without_check(monkeypatch):
    calls = _patch_run(monkeypatch)
    bootstrap.run_bootstrap(SimpleNamespace())
    argv, cwd = calls[0]
    assert argv == ["ansible-playbook", bootstrap.PLAYBOOK]
    assert cwd == bootstrap.ANSIBLE_DIR


def test_check_is_a_dry_run(monkeypatch):
    calls = _patch_run(monkeypatch)
    bootstrap.run_check(SimpleNamespace())
    argv, cwd = calls[0]
    assert argv == ["ansible-playbook", bootstrap.PLAYBOOK, "--check", "--diff"]
    assert cwd == bootstrap.ANSIBLE_DIR


def test_missing_tool_fails_clearly(monkeypatch):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda t: None)
    monkeypatch.setattr(bootstrap, "run", lambda *a, **k: None)
    with pytest.raises(SuiteError, match="ansible-playbook"):
        bootstrap.run_bootstrap(SimpleNamespace())
