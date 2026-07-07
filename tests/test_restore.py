"""Unit tests for the `suite restore` flow (suite.restore) — subprocess and HTTPS
boundaries mocked, so the backups-required gate, the not-clean safety refusal,
the --yes override and the restore-mode env handed to helmfile are exercised
without a live cluster."""

from types import SimpleNamespace

import pytest
from conftest import make_ctx

from suite import restore
from suite.errors import SuiteError


def _args(**kw):
    return SimpleNamespace(
        no_tunnel=True,               # no tunnel in tests
        yes=kw.get("yes", True),      # non-interactive
    )


def _patch_common(monkeypatch, *, calls, ctx, clean=True, verify_failed=()):
    """Record every `run(argv, env=...)` into `calls`; stub spec/seed/preflight,
    the clean-cluster probe and the post-restore verify."""
    monkeypatch.setattr(restore.spec, "load_context", lambda: ctx)
    monkeypatch.setattr(restore.config, "require_seed", lambda st, **kw: "seed")
    monkeypatch.setattr(restore.process, "preflight", lambda *a, **kw: None)
    monkeypatch.setattr(restore, "_cluster_is_clean", lambda: clean)
    monkeypatch.setattr(restore.steps, "verify_https",
                        lambda domain, enabled, trusted: list(verify_failed))
    # resolve_issuer hits kubectl over the tunnel; stub it to the live issuer.
    monkeypatch.setattr(restore, "resolve_issuer", lambda: "letsencrypt-http01")
    monkeypatch.setattr(restore.state, "save", lambda st: None)
    monkeypatch.setattr(restore, "run",
                        lambda argv, **kw: calls.append((list(argv), kw.get("env"))))


def test_refuses_when_backups_disabled(monkeypatch):
    calls = []
    ctx = make_ctx(view={"OWNSUITE_BACKUP_ENABLED": "false"})
    _patch_common(monkeypatch, calls=calls, ctx=ctx)
    with pytest.raises(SuiteError, match="backups are disabled"):
        restore.run_restore(_args())
    # Gate fires before any helmfile sync — nothing was run.
    assert calls == []


def test_external_target_needs_endpoint(monkeypatch):
    calls = []
    ctx = make_ctx(view={"OWNSUITE_BACKUP_S3_TARGET": "external"})
    _patch_common(monkeypatch, calls=calls, ctx=ctx)
    with pytest.raises(SuiteError, match="OWNSUITE_BACKUP_S3_ENDPOINT"):
        restore.run_restore(_args())
    assert calls == []


def test_refuses_on_not_clean_cluster_without_confirm(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls=calls, ctx=make_ctx(), clean=False)
    # No --yes and the typed confirmation is declined -> abort, nothing synced.
    monkeypatch.setattr(restore, "_confirm_not_clean", lambda: False)
    restore.run_restore(_args(yes=False))
    assert calls == []


def test_yes_overrides_not_clean_and_syncs(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls=calls, ctx=make_ctx(), clean=False)
    restore.run_restore(_args(yes=True))
    # --yes skips the safety gate; the restore-mode sync still runs.
    assert [c[0][-1] for c in calls] == ["sync"]


def test_passes_restore_mode_env_to_helmfile(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls=calls, ctx=make_ctx(apps=("docs",)))
    restore.run_restore(_args())
    argv, env = calls[0]
    assert argv[:3] == ["helmfile", "-f", restore.HELMFILE] and argv[-1] == "sync"
    # restore mode + backups forced on, exactly as `make restore` runs it.
    assert env["OWNSUITE_RESTORE"] == "true"
    assert env["OWNSUITE_BACKUP_ENABLED"] == "true"
    # The live issuer is pinned so restore never downgrades certs to selfsigned.
    assert env["OWNSUITE_TLS_ISSUER"] == "letsencrypt-http01"


def test_raises_when_verify_fails(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls=calls, ctx=make_ctx(), clean=True,
                  verify_failed=["auth", "docs"])
    with pytest.raises(SuiteError, match="verification failed for: auth, docs"):
        restore.run_restore(_args())
    # The sync ran; the failure is surfaced after, not silently swallowed.
    assert [c[0][-1] for c in calls] == ["sync"]
