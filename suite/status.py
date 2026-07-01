"""`suite status` — a readable health summary of a running OwnSuite (ADR-033).

Reads live state over the existing SSH tunnel (ADR-014) with `kubectl get -o json`
and parses it — no extra in-cluster workload, no monitoring stack. The pure
summarising functions (``summarise_*``) take already-parsed kubectl JSON so they
are unit-tested with fixtures, never a live cluster.
"""

from __future__ import annotations

import json
import os
import shutil

from . import config, tunnel
from .errors import SuiteError
from .process import run

NS = "ownsuite"
# App -> subdomain label, mirrored from the Helmfile release conditions. Only the
# enabled ones are reported (read from .env / env via OWNSUITE_APP_*).
APPS = {
    "docs": "docs",
    "drive": "drive",
    "grist": "grist",
    "projects": "projects",
    "messages": "messages",
    "meet": "meet",
}
# Defaults match helmfile/environments/default.yaml.gotmpl: every app is off by
# default (ADR-035); only the operator's OWNSUITE_APP_* / .env turns one on.
APP_DEFAULTS = {"docs": "false", "drive": "false", "grist": "false",
                "projects": "false", "messages": "false", "meet": "false"}


def run_status(args):
    cfg = config.load_env(args.env_file)
    ssh = getattr(args, "ssh", None) or cfg.get("OWNSUITE_SERVER_SSH", "")
    _preflight(args, ssh)
    enabled = enabled_apps(cfg)

    with tunnel.maybe(ssh, no_tunnel=args.no_tunnel):
        nodes = _kubectl_json(["get", "nodes"])
        clusters = _kubectl_json(["-n", NS, "get", "clusters.postgresql.cnpg.io"])
        certs = _kubectl_json(["-n", NS, "get", "certificates.cert-manager.io"])
        cronjobs = _kubectl_json(["-n", NS, "get", "cronjobs"])
        jobs = _kubectl_json(["-n", NS, "get", "jobs"])
        pods = _kubectl_json(["-n", NS, "get", "pods"])

    print(render(nodes, clusters, certs, cronjobs, jobs, pods, enabled))


def enabled_apps(cfg):
    """Apps that are switched on, honouring env first then .env then the defaults
    (same precedence the Helmfile uses)."""
    on = []
    for app in APPS:
        key = f"OWNSUITE_APP_{app.upper()}"
        val = os.environ.get(key, cfg.get(key, APP_DEFAULTS[app]))
        if str(val).lower() == "true":
            on.append(app)
    return on


# --- pure summarisers (unit-tested against fixtures) --------------------------

def _ready(conditions, kind="Ready"):
    """True iff a status.conditions list has `kind` == True."""
    return any(c.get("type") == kind and c.get("status") == "True"
               for c in (conditions or []))


def summarise_nodes(nodes):
    out = []
    for n in nodes.get("items", []):
        name = n["metadata"]["name"]
        ready = _ready(n.get("status", {}).get("conditions"))
        out.append((name, ready))
    return out


def summarise_clusters(clusters):
    """CNPG cluster health + last-backup state from status.conditions / fields."""
    out = []
    for c in clusters.get("items", []):
        st = c.get("status", {})
        name = c["metadata"]["name"]
        instances = st.get("instances")
        ready_instances = st.get("readyInstances")
        healthy = (instances is not None and ready_instances == instances)
        # CNPG records the last backup outcome here when a Backup has run.
        last_backup = st.get("lastSuccessfulBackup")
        out.append({
            "name": name,
            "healthy": healthy,
            "ready": ready_instances,
            "instances": instances,
            "last_backup": last_backup,
        })
    return out


def summarise_certs(certs):
    out = []
    for c in certs.get("items", []):
        name = c["metadata"]["name"]
        ready = _ready(c.get("status", {}).get("conditions"))
        out.append((name, ready))
    return out


def summarise_backup(cronjobs, jobs):
    """Off-site backup state: is the object-backup CronJob present + not suspended,
    and did its most recent Job succeed?"""
    cj = next((c for c in cronjobs.get("items", [])
               if c["metadata"]["name"] == "object-backup"), None)
    if cj is None:
        return {"configured": False, "suspended": None, "last_job_ok": None}
    suspended = bool(cj.get("spec", {}).get("suspend", False))
    # Most recent object-backup* Job by creationTimestamp; succeeded?
    backup_jobs = [j for j in jobs.get("items", [])
                   if j["metadata"]["name"].startswith("object-backup")]
    last_job_ok = None
    if backup_jobs:
        latest = max(backup_jobs,
                     key=lambda j: j["metadata"].get("creationTimestamp", ""))
        last_job_ok = (latest.get("status", {}).get("succeeded", 0) or 0) >= 1
    return {"configured": True, "suspended": suspended, "last_job_ok": last_job_ok}


def summarise_app_pods(pods, app):
    """(running, total, all_ready) for one app's pods, matched on the
    app.kubernetes.io/name (or the `app` label) carrying the app name."""
    items = [p for p in pods.get("items", []) if _pod_app(p) == app]
    total = len(items)
    running = sum(1 for p in items if p.get("status", {}).get("phase") == "Running")
    all_ready = total > 0 and all(
        _ready(p.get("status", {}).get("conditions")) for p in items
    )
    return running, total, all_ready


def _pod_app(pod):
    labels = pod.get("metadata", {}).get("labels", {})
    name = labels.get("app.kubernetes.io/name") or labels.get("app") or ""
    # Upstream charts prefix release names (e.g. "docs-impress"); match on substring
    # so "docs"/"drive"/"grist"/"projects"/"messages" all resolve.
    for app in APPS:
        if name == app or name.startswith(f"{app}-") or app in name.split("-"):
            return app
    return name


def render(nodes, clusters, certs, cronjobs, jobs, pods, enabled):
    def mark(ok):
        return "OK  " if ok else "FAIL"

    lines = ["", "OwnSuite status", "=" * 40, "", "Node:"]
    for name, ready in summarise_nodes(nodes):
        lines.append(f"  {mark(ready)} {name}")

    lines += ["", "Database (CloudNativePG):"]
    cl = summarise_clusters(clusters)
    if not cl:
        lines.append("  (no CNPG cluster found)")
    for c in cl:
        lines.append(f"  {mark(c['healthy'])} {c['name']} "
                     f"({c['ready']}/{c['instances']} ready)")
        lb = c["last_backup"] or "never"
        lines.append(f"       last successful backup: {lb}")

    lines += ["", "Certificates (cert-manager):"]
    cs = summarise_certs(certs)
    if not cs:
        lines.append("  (no certificates found)")
    for name, ready in cs:
        lines.append(f"  {mark(ready)} {name}")

    lines += ["", "Off-site backup:"]
    b = summarise_backup(cronjobs, jobs)
    if not b["configured"]:
        lines.append("  FAIL not configured (off-site object backup CronJob missing)")
    else:
        lines.append(f"  {mark(not b['suspended'])} object-backup CronJob "
                     f"({'suspended' if b['suspended'] else 'active'})")
        if b["last_job_ok"] is None:
            lines.append("       last run: none yet")
        else:
            lines.append(f"  {mark(b['last_job_ok'])} last backup job "
                         f"{'succeeded' if b['last_job_ok'] else 'FAILED'}")

    lines += ["", "Apps:"]
    if not enabled:
        lines.append("  (none enabled)")
    for app in enabled:
        running, total, ready = summarise_app_pods(pods, app)
        lines.append(f"  {mark(ready)} {app} ({running}/{total} pods running)")

    lines.append("")
    return "\n".join(lines)


# --- live-cluster boundary ---------------------------------------------------

def _kubectl_json(argv):
    proc = run(["kubectl", *argv, "-o", "json"], capture=True, step="kubectl get")
    return json.loads(proc.stdout or "{}")


def _preflight(args, ssh):
    tools = ["kubectl"]
    if not args.no_tunnel and ssh:
        tools.append("ssh")
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SuiteError(f"missing required tools on PATH: {', '.join(missing)}")
