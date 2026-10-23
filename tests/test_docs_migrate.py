"""Unit tests for the Docs 6.0 backfill (suite.docs_migrate): kubectl mocked."""

from types import SimpleNamespace

import pytest

from suite import docs_migrate
from suite.errors import SuiteError


def _proc(rc=0, out=""):
    return SimpleNamespace(returncode=rc, stdout=out, stderr="")


def _patch(monkeypatch, results):
    """Record every kubectl argv; answer from `results` in order (last repeats)."""
    calls = []
    queue = list(results)

    def fake_run(argv, **kw):
        calls.append(list(argv))
        proc = queue.pop(0) if len(queue) > 1 else queue[0]
        if kw.get("check", True) and proc.returncode != 0:
            raise SuiteError("kubectl failed")
        return proc

    monkeypatch.setattr(docs_migrate, "run", fake_run)
    return calls


def _flags(call):
    return call[call.index("migrate_documents") + 1:]


def test_skipped_when_docs_disabled(monkeypatch):
    calls = _patch(monkeypatch, [_proc()])
    st = {}
    docs_migrate.run_if_enabled(["grist", "drive"], st)
    assert calls == [] and "docs_yhub_migrated" not in st


def test_dry_run_then_real_run_sets_flag(monkeypatch):
    calls = _patch(monkeypatch, [_proc(), _proc()])
    st = {}
    docs_migrate.run_if_enabled(["docs"], st)
    assert len(calls) == 2
    assert calls[0][:6] == ["kubectl", "-n", "ownsuite", "exec", "deploy/docs-backend", "--"]
    assert _flags(calls[0]) == ["--dry-run"]
    assert _flags(calls[1]) == ["--concurrency", docs_migrate.CONCURRENCY,
                                "--rate", docs_migrate.RATE]
    assert st["docs_yhub_migrated"] is True


def test_retry_failed_loop_until_clean(monkeypatch):
    calls = _patch(monkeypatch, [_proc(), _proc(1), _proc(0, "2 failed"), _proc(0, "0 failed")])
    st = {}
    docs_migrate.backfill(st)
    assert [_flags(c)[0] for c in calls] == [
        "--dry-run", "--concurrency", "--retry-failed", "--retry-failed"]
    assert st["docs_yhub_migrated"] is True


def test_failure_raises_after_bounded_attempts(monkeypatch):
    calls = _patch(monkeypatch, [_proc(), _proc(1)])
    st = {}
    with pytest.raises(SuiteError, match="still failed"):
        docs_migrate.backfill(st)
    # dry-run + real run + MAX_RETRIES retries
    assert len(calls) == 2 + docs_migrate.MAX_RETRIES
    assert "docs_yhub_migrated" not in st


def test_dry_run_failure_aborts(monkeypatch):
    calls = _patch(monkeypatch, [_proc(1)])
    with pytest.raises(SuiteError):
        docs_migrate.backfill({})
    assert len(calls) == 1
