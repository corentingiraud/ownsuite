"""Unit tests for `suite sync` (suite.sync) — subprocess and HTTPS boundaries mocked,
so selector resolution, the live-issuer injection, the snapshot gate and the scoped
rollback-on-health-failure branch are exercised without a live cluster."""

from types import SimpleNamespace

import pytest

from suite import sync, upgrade
from suite.errors import SuiteError


def _args(**kw):
    return SimpleNamespace(
        env_file=kw.get("env_file", ".env"),
        ssh=kw.get("ssh"),
        no_tunnel=kw.get("no_tunnel", True),   # no tunnel in tests
        yes=kw.get("yes", True),               # non-interactive
        no_snapshot=kw.get("no_snapshot", False),
        diff=kw.get("diff", False),
        selector=kw.get("selector"),
        app=kw.get("app"),
    )


def _patch_common(monkeypatch, *, calls, cfg, health_failed):
    """Record every `run(argv)` into `calls`; stub config/seed/preflight/issuer/health."""
    monkeypatch.setenv("OWNSUITE_SECRET_SEED", "seed")
    monkeypatch.setattr(sync.config, "load_env", lambda p: dict(cfg))
    monkeypatch.setattr(sync, "_preflight", lambda *a, **k: None)
    monkeypatch.setattr(sync, "resolve_issuer", lambda: "letsencrypt-http01")

    def recorder(argv, **kw):
        calls.append((list(argv), kw))

    monkeypatch.setattr(sync, "run", recorder)
    # `_snapshot`/`_show_diff` are reused from the upgrade module, so they call
    # `upgrade.run`; record those into the same list to see the full call order.
    monkeypatch.setattr(upgrade, "run", recorder)
    monkeypatch.setattr(sync, "_health_check", lambda domain, releases: list(health_failed))
    # The stuck-release check does its own `helm list`; not the unit under test here.
    monkeypatch.setattr(sync, "_warn_stuck_releases", lambda releases: None)


BASE_CFG = {"OWNSUITE_DOMAIN": "assoc.org", "OWNSUITE_BACKUP_ENABLED": "true"}


# --- selector / release resolution ------------------------------------------------

def test_app_expands_to_release_group():
    assert sync._resolve_releases(_args(app=["drive"])) == [
        "drive-ingress", "drive", "drive-media-proxy",
    ]


def test_unknown_app_errors():
    with pytest.raises(SuiteError, match="unknown --app 'nope'"):
        sync._resolve_releases(_args(app=["nope"]))


def test_selector_and_app_merge_and_dedup():
    # -l drive (already in the drive group) must not appear twice.
    got = sync._resolve_releases(_args(app=["drive"], selector=["drive", "grist"]))
    assert got == ["drive-ingress", "drive", "drive-media-proxy", "grist"]


def test_empty_selection_errors(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls=calls, cfg=BASE_CFG, health_failed=[])
    with pytest.raises(SuiteError, match="nothing selected"):
        sync.run_sync(_args())
    assert calls == []


def test_selector_args_uses_name_label():
    assert sync._selector_args(["drive", "drive-ingress"]) == [
        "-l", "name=drive", "-l", "name=drive-ingress",
    ]


# --- platform-configuration auto-inclusion ----------------------------------------

def test_add_platform_config_prepended_for_app_release():
    assert sync._add_platform_config(["drive", "drive-media-proxy"]) == [
        "platform-configuration", "drive", "drive-media-proxy",
    ]


def test_add_platform_config_noop_when_already_present():
    assert sync._add_platform_config(["platform-configuration", "drive"]) == [
        "platform-configuration", "drive",
    ]


def test_add_platform_config_noop_when_nothing_needs_it():
    assert sync._add_platform_config(["postgres"]) == ["postgres"]


# --- stuck-release warning ---------------------------------------------------------

def test_warn_stuck_releases_flags_non_healthy(monkeypatch, capsys):
    import json as _json
    payload = _json.dumps([
        {"name": "drive", "status": "failed"},
        {"name": "docs", "status": "deployed"},
    ])
    monkeypatch.setattr(sync, "run", lambda *a, **k: SimpleNamespace(stdout=payload))
    sync._warn_stuck_releases(["drive", "docs"])
    out = capsys.readouterr().out
    assert "drive" in out and "failed" in out
    assert "NOTE docs" not in out                          # healthy -> not flagged


# --- --diff mode -------------------------------------------------------------------

def test_diff_mode_shows_diff_and_applies_nothing(monkeypatch):
    calls = []
    # backups disabled + no --no-snapshot: --diff must still skip the gate + snapshot.
    cfg = {**BASE_CFG, "OWNSUITE_BACKUP_ENABLED": "false"}
    monkeypatch.delenv("OWNSUITE_BACKUP_ENABLED", raising=False)
    _patch_common(monkeypatch, calls=calls, cfg=cfg, health_failed=[])
    sync.run_sync(_args(selector=["drive"], diff=True))
    argvs = [c[0] for c in calls]
    assert any(a[3] == "diff" for a in argvs)              # showed the diff
    assert not any(a[3] == "sync" for a in argvs)          # applied nothing
    assert ["make", "backup"] not in argvs                 # no snapshot


def test_sync_diff_flag_parses():
    from suite import cli
    args = cli.build_parser().parse_args(["sync", "--app", "docs", "--diff"])
    assert args.diff is True


# --- happy path: snapshot -> diff -> sync (not apply), issuer injected -------------

def test_happy_path_snapshots_then_syncs_with_selector(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls=calls, cfg=BASE_CFG, health_failed=[])
    sync.run_sync(_args(selector=["drive-media-proxy"]))
    argvs = [c[0] for c in calls]
    assert argvs[0] == ["make", "backup"]                 # snapshot first
    assert argvs[1][:3] == ["helmfile", "-f", sync.HELMFILE] and argvs[1][3] == "diff"
    assert argvs[2][3] == "sync"                          # sync, NOT apply
    assert not any("apply" in a for a in argvs)
    # both diff and sync carry the scoped selector
    for a in (argvs[1], argvs[2]):
        assert a[-2:] == ["-l", "name=drive-media-proxy"]
    # the sync env carries the resolved (never-selfsigned) issuer
    sync_env = calls[2][1]["env"]
    assert sync_env["OWNSUITE_TLS_ISSUER"] == "letsencrypt-http01"


def test_no_snapshot_skips_backup_and_gate(monkeypatch):
    calls = []
    # backups disabled: default would refuse, but --no-snapshot skips the gate entirely.
    cfg = {**BASE_CFG, "OWNSUITE_BACKUP_ENABLED": "false"}
    monkeypatch.delenv("OWNSUITE_BACKUP_ENABLED", raising=False)
    _patch_common(monkeypatch, calls=calls, cfg=cfg, health_failed=[])
    sync.run_sync(_args(selector=["drive"], no_snapshot=True))
    argvs = [c[0] for c in calls]
    assert ["make", "backup"] not in argvs
    assert argvs[0][3] == "diff"                          # straight to diff


def test_snapshot_default_requires_backups(monkeypatch):
    calls = []
    cfg = {**BASE_CFG, "OWNSUITE_BACKUP_ENABLED": "false"}
    monkeypatch.delenv("OWNSUITE_BACKUP_ENABLED", raising=False)
    _patch_common(monkeypatch, calls=calls, cfg=cfg, health_failed=[])
    with pytest.raises(SuiteError, match="backups are disabled"):
        sync.run_sync(_args(selector=["drive"]))
    assert calls == []


def test_requires_seed(monkeypatch):
    monkeypatch.delenv("OWNSUITE_SECRET_SEED", raising=False)
    monkeypatch.setattr(sync.config, "load_env", lambda p: dict(BASE_CFG))
    with pytest.raises(SuiteError, match="OWNSUITE_SECRET_SEED"):
        sync.run_sync(_args(selector=["drive"]))


def test_seed_may_come_from_env_file(monkeypatch):
    """The seed can be read from .env (cfg), not only an exported env var."""
    calls = []
    cfg = {**BASE_CFG, "OWNSUITE_SECRET_SEED": "from-dotenv"}
    _patch_common(monkeypatch, calls=calls, cfg=cfg, health_failed=[])
    monkeypatch.delenv("OWNSUITE_SECRET_SEED", raising=False)  # only .env has it
    sync.run_sync(_args(selector=["drive"], no_snapshot=True))
    assert any(c[0][3] == "sync" for c in calls)  # reached helmfile sync, no error


# --- scoped rollback ---------------------------------------------------------------

def test_rolls_back_only_selected_releases_on_health_failure(monkeypatch):
    calls = []
    # sync the whole drive group; drive's host fails.
    _patch_common(monkeypatch, calls=calls, cfg=BASE_CFG, health_failed=["drive"])
    with pytest.raises(SuiteError, match="rolled back"):
        sync.run_sync(_args(app=["drive"]))
    rollbacks = [c[0] for c in calls if "rollback" in c[0]]
    rolled = {c[-1] for c in rollbacks}
    assert rolled == {"drive-ingress", "drive", "drive-media-proxy"}
    # never touches an unrelated release
    assert "grist" not in rolled


# --- scoped health check -----------------------------------------------------------

def test_health_check_targets_only_selected_apps(monkeypatch):
    seen = {}
    monkeypatch.setattr(sync.verify, "https_ok", lambda url, **kw: seen.setdefault(url, True))
    failed = sync._health_check("assoc.org", ["drive-media-proxy"])
    assert failed == []
    assert seen == {"https://drive.assoc.org/": True}     # only drive's host, once


def test_health_check_uses_oidc_url_for_keycloak(monkeypatch):
    seen = {}
    monkeypatch.setattr(sync.verify, "https_ok", lambda url, **kw: seen.setdefault(url, True))
    sync._health_check("assoc.org", ["keycloak"])
    assert list(seen) == [
        "https://auth.assoc.org/realms/ownsuite/.well-known/openid-configuration"
    ]


def test_health_check_skips_platform_releases(monkeypatch):
    calls = []
    monkeypatch.setattr(sync.verify, "https_ok", lambda url, **kw: calls.append(url))
    assert sync._health_check("assoc.org", ["postgres"]) == []
    assert calls == []                                    # no public host -> no check
