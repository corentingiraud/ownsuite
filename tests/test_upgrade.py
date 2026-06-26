"""Unit tests for the `suite upgrade` flow (suite.upgrade) — subprocess and HTTPS
boundaries mocked, so the backup gate, snapshot/apply ordering and the
rollback-on-health-failure branch are exercised without a live cluster."""

from types import SimpleNamespace

import pytest

from suite import upgrade
from suite.errors import SuiteError


def _args(**kw):
    return SimpleNamespace(
        env_file=kw.get("env_file", ".env"),
        ssh=kw.get("ssh"),
        no_tunnel=kw.get("no_tunnel", True),  # no tunnel in tests
        yes=kw.get("yes", True),              # non-interactive
    )


def _patch_common(monkeypatch, *, calls, cfg, health_failed):
    """Record every `run(argv)` into `calls`; stub config/seed/preflight/health."""
    monkeypatch.setenv("OWNSUITE_SECRET_SEED", "seed")
    monkeypatch.setattr(upgrade.config, "load_env", lambda p: dict(cfg))
    monkeypatch.setattr(upgrade, "_preflight", lambda *a, **k: None)
    monkeypatch.setattr(upgrade, "run", lambda argv, **kw: calls.append(list(argv)))
    monkeypatch.setattr(upgrade, "_health_check", lambda domain, enabled: list(health_failed))


BASE_CFG = {"OWNSUITE_DOMAIN": "assoc.org", "OWNSUITE_BACKUP_ENABLED": "true"}


def test_refuses_when_backups_disabled(monkeypatch):
    calls = []
    cfg = {**BASE_CFG, "OWNSUITE_BACKUP_ENABLED": "false"}
    monkeypatch.delenv("OWNSUITE_BACKUP_ENABLED", raising=False)
    _patch_common(monkeypatch, calls=calls, cfg=cfg, health_failed=[])
    with pytest.raises(SuiteError, match="backups are disabled"):
        upgrade.run_upgrade(_args())
    # Gate fires before any snapshot/apply — nothing was run.
    assert calls == []


def test_requires_seed(monkeypatch):
    monkeypatch.delenv("OWNSUITE_SECRET_SEED", raising=False)
    monkeypatch.setattr(upgrade.config, "load_env", lambda p: dict(BASE_CFG))
    with pytest.raises(SuiteError, match="OWNSUITE_SECRET_SEED"):
        upgrade.run_upgrade(_args())


def test_happy_path_snapshots_then_applies(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls=calls, cfg=BASE_CFG, health_failed=[])
    upgrade.run_upgrade(_args())
    # snapshot (make backup) happens before helmfile apply; no rollback on success.
    assert ["make", "helmfile", "helmfile"] == [c[0] for c in calls]
    assert calls[0] == ["make", "backup"]
    assert calls[1][:3] == ["helmfile", "-f", upgrade.HELMFILE] and calls[1][-1] == "diff"
    assert calls[2][-1] == "apply"
    assert not any("rollback" in c for c in calls)


def test_rolls_back_affected_release_on_health_failure(monkeypatch):
    calls = []
    cfg = {**BASE_CFG, "OWNSUITE_APP_GRIST": "true"}
    _patch_common(monkeypatch, calls=calls, cfg=cfg, health_failed=["docs", "auth"])
    with pytest.raises(SuiteError, match="rolled back"):
        upgrade.run_upgrade(_args())
    rollbacks = [c for c in calls if "rollback" in c]
    # docs -> release "docs", auth -> release "keycloak"
    assert ["helm", "-n", upgrade.NS, "rollback", "docs"] in rollbacks
    assert ["helm", "-n", upgrade.NS, "rollback", "keycloak"] in rollbacks


def test_health_check_targets_keycloak_plus_enabled_apps(monkeypatch):
    seen = {}
    monkeypatch.setattr(upgrade.verify, "https_ok", lambda url, **kw: seen.setdefault(url, True))
    failed = upgrade._health_check("assoc.org", ["docs", "drive"])
    assert failed == []
    assert "https://auth.assoc.org/realms/ownsuite/.well-known/openid-configuration" in seen
    assert "https://docs.assoc.org/" in seen
    assert "https://drive.assoc.org/" in seen
