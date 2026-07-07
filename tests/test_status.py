"""Unit tests for `suite status` parsing (suite.status) against kubectl JSON
fixtures — no tunnel, no kubectl, no live cluster."""

from suite import status


def _conds(*ready):
    return [{"type": "Ready", "status": "True" if r else "False"} for r in ready]


def test_summarise_nodes_ready_flag():
    nodes = {"items": [
        {"metadata": {"name": "n1"}, "status": {"conditions": _conds(True)}},
        {"metadata": {"name": "n2"}, "status": {"conditions": _conds(False)}},
    ]}
    assert status.summarise_nodes(nodes) == [("n1", True), ("n2", False)]


def test_summarise_clusters_health_and_last_backup():
    clusters = {"items": [{
        "metadata": {"name": "ownsuite-pg"},
        "status": {"instances": 1, "readyInstances": 1,
                   "lastSuccessfulBackup": "2026-06-26T10:00:00Z"},
    }]}
    [c] = status.summarise_clusters(clusters)
    assert c["healthy"] is True
    assert c["last_backup"] == "2026-06-26T10:00:00Z"


def test_summarise_clusters_unhealthy_when_not_all_ready():
    clusters = {"items": [{
        "metadata": {"name": "pg"},
        "status": {"instances": 2, "readyInstances": 1},
    }]}
    [c] = status.summarise_clusters(clusters)
    assert c["healthy"] is False
    assert c["last_backup"] is None


def test_summarise_certs():
    certs = {"items": [
        {"metadata": {"name": "docs-tls"}, "status": {"conditions": _conds(True)}},
        {"metadata": {"name": "drive-tls"}, "status": {"conditions": _conds(False)}},
    ]}
    assert status.summarise_certs(certs) == [("docs-tls", True), ("drive-tls", False)]


def test_summarise_backup_configured_and_last_job_ok():
    cronjobs = {"items": [{"metadata": {"name": "object-backup"}, "spec": {"suspend": False}}]}
    jobs = {"items": [
        {"metadata": {"name": "object-backup-1", "creationTimestamp": "2026-06-26T09:00:00Z"},
         "status": {"succeeded": 1}},
        {"metadata": {"name": "object-backup-manual-2",
                      "creationTimestamp": "2026-06-26T10:00:00Z"},
         "status": {"succeeded": 1}},
    ]}
    b = status.summarise_backup(cronjobs, jobs)
    assert b == {"configured": True, "suspended": False, "last_job_ok": True}


def test_summarise_backup_latest_job_failed():
    cronjobs = {"items": [{"metadata": {"name": "object-backup"}, "spec": {}}]}
    jobs = {"items": [
        {"metadata": {"name": "object-backup-1", "creationTimestamp": "2026-06-26T09:00:00Z"},
         "status": {"succeeded": 1}},
        {"metadata": {"name": "object-backup-2", "creationTimestamp": "2026-06-26T10:00:00Z"},
         "status": {"failed": 1}},
    ]}
    b = status.summarise_backup(cronjobs, jobs)
    assert b["last_job_ok"] is False


def test_summarise_backup_not_configured():
    b = status.summarise_backup({"items": []}, {"items": []})
    assert b == {"configured": False, "suspended": None, "last_job_ok": None}


def test_summarise_app_pods_matches_release_prefixed_names():
    pods = {"items": [
        {"metadata": {"labels": {"app.kubernetes.io/name": "docs-impress"}},
         "status": {"phase": "Running", "conditions": _conds(True)}},
        {"metadata": {"labels": {"app.kubernetes.io/name": "docs-impress"}},
         "status": {"phase": "Running", "conditions": _conds(True)}},
        {"metadata": {"labels": {"app.kubernetes.io/name": "drive"}},
         "status": {"phase": "Pending", "conditions": _conds(False)}},
    ]}
    assert status.summarise_app_pods(pods, "docs") == (2, 2, True)
    assert status.summarise_app_pods(pods, "drive") == (0, 1, False)
    assert status.summarise_app_pods(pods, "grist") == (0, 0, False)


def test_summarise_app_pods_ignores_job_pods():
    # A healthy deployment pod plus failed CronJob pods (meet's clean_pending_files):
    # the Job-owned pods must not count toward the app's service health.
    pods = {"items": [
        {"metadata": {"labels": {"app.kubernetes.io/name": "meet-backend"}},
         "status": {"phase": "Running", "conditions": _conds(True)}},
        {"metadata": {"labels": {"app.kubernetes.io/name": "meet-backend"},
                      "ownerReferences": [{"kind": "Job", "name": "meet-clean-1"}]},
         "status": {"phase": "Failed", "conditions": _conds(False)}},
        {"metadata": {"labels": {"app.kubernetes.io/name": "meet-backend"},
                      "ownerReferences": [{"kind": "Job", "name": "meet-purge-1"}]},
         "status": {"phase": "Failed", "conditions": _conds(False)}},
    ]}
    assert status.summarise_app_pods(pods, "meet") == (1, 1, True)


def test_logs_rejects_unknown_app():
    from types import SimpleNamespace

    import pytest

    from suite.errors import SuiteError
    with pytest.raises(SuiteError, match="unknown app 'wiki'"):
        status.run_logs(SimpleNamespace(app="wiki", no_tunnel=True, tail=100))


def test_render_smoke():
    out = status.render(
        {"items": [{"metadata": {"name": "n1"}, "status": {"conditions": _conds(True)}}]},
        {"items": []}, {"items": []}, {"items": []}, {"items": []}, {"items": []},
        ["docs"],
    )
    assert "OwnSuite status" in out
    assert "OK   n1" in out
