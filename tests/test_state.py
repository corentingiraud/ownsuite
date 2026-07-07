"""Unit tests for the machine state file (suite.state) — roundtrip, permissions,
and the seed-never-persisted invariant (ADR-012)."""

import json
import os

import pytest

from suite import state
from suite.errors import SuiteError


def _at(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNSUITE_CONFIG", str(tmp_path / "suite.yaml"))
    return tmp_path / ".suite-state.json"


def test_roundtrip_and_0600(tmp_path, monkeypatch):
    p = _at(tmp_path, monkeypatch)
    state.save({"ssh": "root@1.2.3.4", "env": {"OWNSUITE_S3_ACCESS_KEY": "k"}})
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert state.load()["ssh"] == "root@1.2.3.4"


def test_load_missing_is_empty(tmp_path, monkeypatch):
    _at(tmp_path, monkeypatch)
    assert state.load() == {}


def test_load_corrupt_raises(tmp_path, monkeypatch):
    p = _at(tmp_path, monkeypatch)
    p.write_text("{not json")
    with pytest.raises(SuiteError, match="corrupt"):
        state.load()


def test_never_persists_the_seed(tmp_path, monkeypatch):
    _at(tmp_path, monkeypatch)
    with pytest.raises(SuiteError, match="seed"):
        state.save({"env": {"OWNSUITE_SECRET_SEED": "super-secret"}})
    with pytest.raises(SuiteError, match="seed"):
        state.save({"OWNSUITE_SECRET_SEED": "super-secret"})


def test_state_lives_next_to_the_config(tmp_path, monkeypatch):
    p = _at(tmp_path, monkeypatch)
    state.save({"provider": "scaleway"})
    assert json.loads(p.read_text())["provider"] == "scaleway"
    assert os.path.dirname(state.path()) == str(tmp_path)
