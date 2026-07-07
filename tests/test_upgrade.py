"""Unit tests for the `suite upgrade` flow (suite.upgrade) — subprocess and HTTPS
boundaries mocked, so the backup gate, snapshot/apply ordering and the
rollback-on-health-failure branch are exercised without a live cluster."""

from types import SimpleNamespace

import pytest
from conftest import make_ctx

from suite import upgrade
from suite.errors import SuiteError


def _args(**kw):
    return SimpleNamespace(
        no_tunnel=True,               # no tunnel in tests
        yes=kw.get("yes", True),      # non-interactive
    )


def _patch_common(monkeypatch, *, calls, ctx, health_failed=()):
    """Record every `run(argv)` into `calls`; stub spec/seed/preflight/health."""
    monkeypatch.setattr(upgrade.spec, "load_context", lambda: ctx)
    monkeypatch.setattr(upgrade.config, "require_seed", lambda st, **kw: "seed")
    monkeypatch.setattr(upgrade.process, "preflight", lambda *a, **kw: None)
    monkeypatch.setattr(upgrade, "resolve_issuer", lambda: "letsencrypt-http01")
    monkeypatch.setattr(upgrade.backup, "snapshot",
                        lambda: calls.append(["snapshot"]) or ("pg", "job"))
    monkeypatch.setattr(upgrade.state, "save", lambda st: None)
    monkeypatch.setattr(upgrade, "run", lambda argv, **kw: calls.append(list(argv)))
    monkeypatch.setattr(upgrade.steps, "verify_https",
                        lambda domain, enabled, trusted: list(health_failed))


def test_refuses_when_backups_disabled(monkeypatch):
    calls = []
    ctx = make_ctx(view={"OWNSUITE_BACKUP_ENABLED": "false"})
    _patch_common(monkeypatch, calls=calls, ctx=ctx)
    with pytest.raises(SuiteError, match="backups are disabled"):
        upgrade.run_upgrade(_args())
    # Gate fires before any snapshot/apply — nothing was run.
    assert calls == []


def test_refuses_when_backup_machinery_missing(monkeypatch):
    calls = []
    ctx = make_ctx()
    _patch_common(monkeypatch, calls=calls, ctx=ctx)
    monkeypatch.setattr(upgrade.backup, "snapshot", lambda: None)
    with pytest.raises(SuiteError, match="machinery is not installed"):
        upgrade.run_upgrade(_args())


def test_happy_path_snapshots_then_applies(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls=calls, ctx=make_ctx())
    upgrade.run_upgrade(_args())
    # snapshot happens before helmfile diff/apply; no rollback on success.
    assert [c[0] for c in calls] == ["snapshot", "helmfile", "helmfile"]
    assert calls[1][:4] == ["helmfile", "-f", upgrade.HELMFILE, "diff"] and "--context" in calls[1]
    assert calls[2][-1] == "apply"
    assert not any("rollback" in c for c in calls)


def test_rolls_back_every_release_of_a_failed_app(monkeypatch):
    """The old RELEASE_BY_HOST map was missing meet/tchap entirely and knew only
    one release per app — a broken meet upgrade was never rolled back. The
    manifest fixes both: every release of the failed app rolls back."""
    calls = []
    ctx = make_ctx(apps=("meet", "tchap"))
    _patch_common(monkeypatch, calls=calls, ctx=ctx,
                  health_failed=["meet", "auth"])
    with pytest.raises(SuiteError, match="rolled back"):
        upgrade.run_upgrade(_args())
    rollbacks = [c[-1] for c in calls if "rollback" in c]
    assert rollbacks == ["meet", "meet-media-proxy", "livekit", "livekit-egress",
                         "keycloak"]


def test_injects_resolved_issuer_into_apply_env(monkeypatch):
    """The apply must render with the live issuer, never the helmfile `selfsigned`
    default — the footgun that reissued real certs as self-signed (issue #62)."""
    seen = {}
    ctx = make_ctx()
    monkeypatch.setattr(upgrade.spec, "load_context", lambda: ctx)
    monkeypatch.setattr(upgrade.config, "require_seed", lambda st, **kw: "seed")
    monkeypatch.setattr(upgrade.process, "preflight", lambda *a, **kw: None)
    monkeypatch.setattr(upgrade, "resolve_issuer", lambda: "letsencrypt-http01")
    monkeypatch.setattr(upgrade.backup, "snapshot", lambda: ("pg", "job"))
    monkeypatch.setattr(upgrade.state, "save", lambda st: None)
    monkeypatch.setattr(upgrade.steps, "verify_https", lambda d, e, trusted: [])

    def _run(argv, **kw):
        if argv[-1] == "apply":
            seen["env"] = kw.get("env")

    monkeypatch.setattr(upgrade, "run", _run)
    upgrade.run_upgrade(_args())
    assert seen["env"]["OWNSUITE_TLS_ISSUER"] == "letsencrypt-http01"


def test_resolve_issuer_prefers_env(monkeypatch):
    monkeypatch.setenv("OWNSUITE_TLS_ISSUER", "letsencrypt-staging")
    # env wins → no kubectl call at all.
    monkeypatch.setattr(upgrade, "run", lambda *a, **k: pytest.fail("should not shell out"))
    assert upgrade.resolve_issuer() == "letsencrypt-staging"


def test_resolve_issuer_reads_from_cluster(monkeypatch):
    monkeypatch.delenv("OWNSUITE_TLS_ISSUER", raising=False)
    monkeypatch.setattr(
        upgrade, "run",
        lambda argv, **kw: SimpleNamespace(stdout="letsencrypt-http01\n"),
    )
    assert upgrade.resolve_issuer() == "letsencrypt-http01"


def test_resolve_issuer_errors_when_unknown(monkeypatch):
    monkeypatch.delenv("OWNSUITE_TLS_ISSUER", raising=False)
    monkeypatch.setattr(upgrade, "run", lambda argv, **kw: SimpleNamespace(stdout=""))
    with pytest.raises(SuiteError, match="could not determine the live TLS issuer"):
        upgrade.resolve_issuer()
