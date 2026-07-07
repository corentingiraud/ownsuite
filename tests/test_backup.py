"""Unit tests for the snapshot / `suite backup` machinery (suite.backup) — the
kubectl boundary mocked. Covers the tolerant skip when the backup machinery is
absent (a retried first bring-up must not die on its own snapshot) and the
poll-to-completion loop."""

import json
from types import SimpleNamespace

import pytest

from suite import backup
from suite.errors import SuiteError


def _machinery(present):
    def run(argv, **kw):
        if "get" in argv and ("clusters.postgresql.cnpg.io" in " ".join(argv)
                              or "cronjob/object-backup" in argv):
            return SimpleNamespace(returncode=0 if present else 1, stdout="")
        return SimpleNamespace(returncode=0, stdout="")
    return run


def test_snapshot_skips_when_machinery_absent(monkeypatch, capsys):
    monkeypatch.setattr(backup, "run", _machinery(False))
    assert backup.snapshot() is None
    assert "skipping the snapshot" in capsys.readouterr().out


def test_snapshot_creates_backup_cr_and_object_job(monkeypatch):
    calls = []

    def run(argv, **kw):
        calls.append((list(argv), kw.get("input_text")))
        out = "backup.postgresql.cnpg.io/ownsuite-pg-ondemand-abc" \
            if "-f" in argv else ""
        return SimpleNamespace(returncode=0, stdout=out)

    monkeypatch.setattr(backup, "run", run)
    pg, job = backup.snapshot()
    assert pg == "ownsuite-pg-ondemand-abc"
    assert job.startswith("object-backup-manual-")
    creates = [c for c in calls if "create" in c[0]]
    manifest_text = creates[0][1]
    assert "kind: Backup" in manifest_text
    assert "barman-cloud.cloudnative-pg.io" in manifest_text
    assert creates[1][0][-1] == job
    assert "--from=cronjob/object-backup" in creates[1][0]


def test_wait_polls_until_completed(monkeypatch):
    phases = iter(["running", "running", "completed"])

    def run(argv, **kw):
        if "jsonpath={.status.phase}" in argv:
            return SimpleNamespace(returncode=0, stdout=next(phases))
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            {"status": {"succeeded": 1}}))

    monkeypatch.setattr(backup, "run", run)
    monkeypatch.setattr(backup.time, "sleep", lambda s: None)
    backup._wait("pg-backup", "object-job")  # returns without raising


def test_wait_raises_on_failed_backup(monkeypatch):
    monkeypatch.setattr(
        backup, "run",
        lambda argv, **kw: SimpleNamespace(returncode=0, stdout="failed"))
    monkeypatch.setattr(backup.time, "sleep", lambda s: None)
    with pytest.raises(SuiteError, match="failed"):
        backup._wait("pg-backup", "object-job")


def test_wait_raises_on_failed_object_job(monkeypatch):
    def run(argv, **kw):
        if "jsonpath={.status.phase}" in argv:
            return SimpleNamespace(returncode=0, stdout="completed")
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            {"status": {"conditions": [{"type": "Failed", "status": "True"}]}}))

    monkeypatch.setattr(backup, "run", run)
    monkeypatch.setattr(backup.time, "sleep", lambda s: None)
    with pytest.raises(SuiteError, match="object-backup job"):
        backup._wait("pg-backup", "object-job")
