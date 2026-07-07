"""Unit tests for `suite deps` and the Ansible bootstrap `suite apply` drives
(suite.bootstrap) — the subprocess and tool-discovery boundaries are mocked, so
the exact commands (incl. the JSON extra-vars carrying the firewall flags) are
asserted without touching pip/Ansible or a real server."""

import json
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
    assert argvs[0] == ["pip", "install", "-r", bootstrap.REQUIREMENTS]
    assert argvs[1] == ["pip", "install", "-r", bootstrap.REQUIREMENTS_DEV]
    assert argvs[2][:3] == ["ansible-galaxy", "collection", "install"]
    assert argvs[2][-1] == bootstrap.ANSIBLE_REQUIREMENTS
    assert argvs[3][-1] == bootstrap.MOLECULE_REQUIREMENTS


def test_provision_runs_playbook_in_ansible_dir(monkeypatch):
    calls = _patch_run(monkeypatch)
    bootstrap.provision()
    argv, cwd = calls[0]
    assert argv == ["ansible-playbook", bootstrap.PLAYBOOK]
    assert cwd == bootstrap.ANSIBLE_DIR


def test_provision_check_is_a_dry_run(monkeypatch):
    calls = _patch_run(monkeypatch)
    bootstrap.provision(check=True)
    argv, cwd = calls[0]
    assert argv == ["ansible-playbook", bootstrap.PLAYBOOK, "--check", "--diff"]
    assert cwd == bootstrap.ANSIBLE_DIR


def test_provision_passes_firewall_flags_as_typed_json(monkeypatch):
    """`-e k=v` would make booleans strings (truthy Jinja footgun); the flags must
    travel as one JSON extra-vars argument."""
    calls = _patch_run(monkeypatch)
    flags = {"enable_mailbox": False, "enable_meet": True, "enable_meet_turn": False}
    bootstrap.provision(extra_vars=flags)
    argv, _ = calls[0]
    assert argv[-2] == "-e"
    assert json.loads(argv[-1]) == flags


def test_missing_tool_fails_clearly(monkeypatch):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda t: None)
    monkeypatch.setattr(bootstrap, "run", lambda *a, **k: None)
    with pytest.raises(SuiteError, match="ansible-playbook"):
        bootstrap.provision()
