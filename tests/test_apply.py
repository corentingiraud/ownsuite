"""Unit tests for `suite plan` / `suite apply` / `suite destroy` (suite.apply) —
subprocess, prompt and HTTPS boundaries mocked. The load-bearing behaviours:
plan mutates nothing, the TLS pass matrix, the snapshot gate, prune (compute +
ordering + platform releases untouched), rollback on health failure, and the
BYO/ambient-cluster skips."""

import json
from types import SimpleNamespace

import pytest
from conftest import make_spec

from suite import apply, manifest
from suite.errors import SuiteError


def _args(**kw):
    return SimpleNamespace(
        yes=kw.get("yes", True),
        no_tunnel=True,
        no_snapshot=kw.get("no_snapshot", False),
    )


class Recorder:
    """Stand-in for process.run: records argv, answers helm list / live-issuer."""

    def __init__(self, helm_list=(), live_issuer=""):
        self.calls = []
        self.helm_list = helm_list  # None => cluster unreachable
        self.live_issuer = live_issuer

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        out, rc = "", 0
        if "list" in argv and argv[0] == "helm":
            if self.helm_list is None:
                rc = 1
            else:
                out = json.dumps([{"name": n, "status": "deployed"}
                                  for n in self.helm_list])
        if "certificate" in argv:
            out = self.live_issuer
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")


def _wire(monkeypatch, *, sp, state=None, helm_list=(), live_issuer="",
          verify_failed=(), snapshots=None):
    """Patch every boundary; return (events, recorder). `events` interleaves the
    mocked helm/kubectl calls with the issue/verify passes, preserving order."""
    events = []
    rec = Recorder(helm_list, live_issuer)

    def run(argv, **kw):
        events.append(("run", list(argv)))
        return rec(argv, **kw)

    monkeypatch.setattr(apply.spec, "load", lambda path=None: sp)
    monkeypatch.setattr(apply.state, "load", lambda: dict(state or {}))
    monkeypatch.setattr(apply.state, "save", lambda st: events.append(("save", None)))
    monkeypatch.setattr(apply.config, "require_seed", lambda st, **kw: "seed")
    monkeypatch.setattr(apply.process, "preflight", lambda *a, **kw: None)
    monkeypatch.setattr(apply, "run", run)
    monkeypatch.setattr(apply, "_show_diff", lambda env: events.append(("diff", env)))
    monkeypatch.setattr(apply, "_confirm", lambda: True)
    monkeypatch.setattr(apply, "_rollback",
                        lambda failed: events.append(("rollback", list(failed))))
    monkeypatch.setattr(apply.backup, "snapshot",
                        lambda: (snapshots.append(True) if snapshots is not None
                                 else None) or ("pg", "job"))
    monkeypatch.setattr(apply.steps, "issue",
                        lambda env, issuer, enabled, **kw: events.append(("issue", issuer)))
    verifies = iter(verify_failed) if verify_failed else None
    monkeypatch.setattr(
        apply.steps, "verify_https",
        lambda d, e, trusted: events.append(("verify", trusted))
        or (next(verifies) if verifies else []),
    )
    # DNS phase boundaries (only reached when tls != selfsigned).
    monkeypatch.setattr(apply.steps, "detect_ipv4", lambda ssh: "203.0.113.10")
    monkeypatch.setattr(apply.ip, "detect_over_ssh", lambda ssh, fam: None)
    monkeypatch.setattr(apply.steps, "emit_dns", lambda *a, **kw: None)
    monkeypatch.setattr(apply.propagation, "wait", lambda d, i: True)
    monkeypatch.setattr(apply.propagation, "check", lambda d, i: (True, []))
    return events, rec


MUTATING = ("apply", "sync", "uninstall", "create", "delete", "rollback")


def test_plan_makes_zero_mutating_calls(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")
    events, _ = _wire(monkeypatch, sp=sp, helm_list=("docs", "tchap"))
    apply.run_plan(SimpleNamespace(yes=False, no_tunnel=True))
    argvs = [e[1] for e in events if e[0] == "run"]
    assert not [a for a in argvs if set(a) & set(MUTATING)]
    assert not [e for e in events if e[0] in ("issue", "save")]


def test_apply_prunes_removed_apps_before_the_helmfile_pass(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")
    events, _ = _wire(monkeypatch, sp=sp,
                      helm_list=("docs", "meet", "livekit", "platform-configuration"))
    apply.run_apply(_args())
    uninstalls = [e[1] for e in events
                  if e[0] == "run" and "uninstall" in e[1]]
    # Only meet's installed releases, in reverse helmfile order; platform stays.
    assert [u[4] for u in uninstalls] == ["livekit", "meet"]
    first_issue = events.index(("issue", "selfsigned"))
    assert all(events.index(("run", u)) < first_issue for u in uninstalls)


def test_first_prod_apply_runs_the_staging_ladder(monkeypatch):
    sp = make_spec(apps=("docs",), tls="prod")
    events, _ = _wire(monkeypatch, sp=sp, helm_list=("docs",), live_issuer="")
    apply.run_apply(_args())
    assert [e for e in events if e[0] == "issue"] == [
        ("issue", "letsencrypt-staging"), ("issue", "letsencrypt-http01")]
    assert [e for e in events if e[0] == "verify"] == [
        ("verify", False), ("verify", True)]


def test_steady_prod_apply_is_a_single_trusted_pass(monkeypatch):
    sp = make_spec(apps=("docs",), tls="prod")
    events, _ = _wire(monkeypatch, sp=sp, helm_list=("docs",),
                      live_issuer="letsencrypt-http01")
    apply.run_apply(_args())
    assert [e for e in events if e[0] == "issue"] == [("issue", "letsencrypt-http01")]
    assert [e for e in events if e[0] == "verify"] == [("verify", True)]


def test_selfsigned_is_a_single_untrusted_pass(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")
    events, _ = _wire(monkeypatch, sp=sp, helm_list=())
    apply.run_apply(_args())
    assert [e for e in events if e[0] == "issue"] == [("issue", "selfsigned")]
    assert [e for e in events if e[0] == "verify"] == [("verify", False)]


def test_health_failure_rolls_back_and_raises(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")
    events, _ = _wire(monkeypatch, sp=sp, helm_list=("docs",),
                      verify_failed=[["docs"]])
    with pytest.raises(SuiteError, match="rolled back"):
        apply.run_apply(_args())
    assert ("rollback", ["docs"]) in events


def test_snapshot_skipped_on_empty_cluster(monkeypatch):
    snaps = []
    sp = make_spec(apps=("docs",), tls="selfsigned",
                   backup={"enabled": True, "target": "in-cluster"})
    _wire(monkeypatch, sp=sp, helm_list=(), snapshots=snaps)
    apply.run_apply(_args())
    assert snaps == []


def test_snapshot_taken_on_live_cluster_with_backups(monkeypatch):
    snaps = []
    sp = make_spec(apps=("docs",), tls="selfsigned",
                   backup={"enabled": True, "target": "in-cluster"})
    monkeypatch.setenv("OWNSUITE_BACKUP_ENABLED", "true")
    _wire(monkeypatch, sp=sp, helm_list=("docs",), snapshots=snaps)
    apply.run_apply(_args())
    assert snaps == [True]


def test_no_backups_on_live_cluster_needs_typed_consent(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")
    monkeypatch.delenv("OWNSUITE_BACKUP_ENABLED", raising=False)
    _wire(monkeypatch, sp=sp, helm_list=("docs",))
    monkeypatch.setattr("builtins.input", lambda prompt="": "nope")
    with pytest.raises(SuiteError, match="aborted"):
        apply.run_apply(_args(yes=False))


def test_no_backups_with_yes_proceeds_with_warning(monkeypatch):
    snaps = []
    sp = make_spec(apps=("docs",), tls="selfsigned")
    monkeypatch.delenv("OWNSUITE_BACKUP_ENABLED", raising=False)
    events, _ = _wire(monkeypatch, sp=sp, helm_list=("docs",), snapshots=snaps)
    apply.run_apply(_args(yes=True))
    assert snaps == []  # no snapshot, but the apply went through
    assert ("issue", "selfsigned") in events


def test_no_provider_skips_terraform_and_no_ssh_skips_bootstrap(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")  # no provider, no ssh
    called = []
    monkeypatch.setattr(apply.provision, "ensure_infra",
                        lambda *a, **kw: called.append("infra"))
    monkeypatch.setattr(apply.bootstrap, "provision",
                        lambda **kw: called.append("bootstrap"))
    _wire(monkeypatch, sp=sp, helm_list=())
    apply.run_apply(_args())
    assert called == []


def test_bootstrap_reruns_when_firewall_flags_change(monkeypatch, tmp_path):
    sp = make_spec(apps=("docs", "meet"), tls="selfsigned", ssh="root@1.2.3.4")
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("{}")
    monkeypatch.setattr(apply.tunnel, "FETCHED_KUBECONFIG", str(kubeconfig))
    bootstraps = []
    monkeypatch.setattr(apply.provision, "write_inventory", lambda ssh: None)
    monkeypatch.setattr(apply.bootstrap, "provision",
                        lambda **kw: bootstraps.append(kw.get("extra_vars")))
    old_flags = {"enable_mailbox": False, "enable_meet": False,
                 "enable_meet_turn": False}
    _wire(monkeypatch, sp=sp, helm_list=("docs",),
          state={"bootstrapped": True, "infra_flags": old_flags})
    apply.run_apply(_args())
    assert bootstraps == [{"enable_mailbox": False, "enable_meet": True,
                           "enable_meet_turn": False}]


def test_bootstrap_skipped_when_up_to_date(monkeypatch, tmp_path):
    sp = make_spec(apps=("docs",), tls="selfsigned", ssh="root@1.2.3.4")
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("{}")
    monkeypatch.setattr(apply.tunnel, "FETCHED_KUBECONFIG", str(kubeconfig))
    bootstraps = []
    monkeypatch.setattr(apply.bootstrap, "provision",
                        lambda **kw: bootstraps.append(1))
    flags = {"enable_mailbox": False, "enable_meet": False,
             "enable_meet_turn": False}
    monkeypatch.setattr(apply.tunnel, "maybe",
                        lambda ssh, no_tunnel: __import__("contextlib").nullcontext())
    _wire(monkeypatch, sp=sp, helm_list=("docs",),
          state={"bootstrapped": True, "infra_flags": flags})
    apply.run_apply(_args())
    assert bootstraps == []


def test_apply_raises_when_cluster_unreachable(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")
    _wire(monkeypatch, sp=sp, helm_list=None)
    with pytest.raises(SuiteError, match="cluster unreachable"):
        apply.run_apply(_args())


def test_plan_survives_unreachable_cluster(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")
    events, _ = _wire(monkeypatch, sp=sp, helm_list=None)
    apply.run_plan(SimpleNamespace(yes=False, no_tunnel=True))  # must not raise
    assert not [e for e in events if e[0] == "issue"]


def test_prune_set_never_touches_platform_releases():
    sp = make_spec(apps=(), tls="selfsigned")
    installed = {"keycloak": "deployed", "postgres": "deployed",
                 "platform-configuration": "deployed",
                 "meet": "deployed", "livekit-egress": "deployed"}
    assert apply._prune_set(sp, installed) == ["livekit-egress", "meet"]
    for release in apply._prune_set(sp, installed):
        assert release in manifest.RELEASE_TO_APP


def test_destroy_needs_typed_confirmation(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")
    events, _ = _wire(monkeypatch, sp=sp, helm_list=("docs",))
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    apply.run_destroy(SimpleNamespace(yes=False, no_tunnel=True))
    assert not [e for e in events if e[0] == "run" and "destroy" in e[1]]


def test_destroy_with_yes_runs_helmfile_destroy(monkeypatch):
    sp = make_spec(apps=("docs",), tls="selfsigned")
    events, _ = _wire(monkeypatch, sp=sp, helm_list=("docs",))
    apply.run_destroy(SimpleNamespace(yes=True, no_tunnel=True))
    assert [e[1][-1] for e in events if e[0] == "run" and "helmfile" in e[1][0]] \
        == ["destroy"]
