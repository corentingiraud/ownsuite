"""`suite status` / `suite apps` / `suite logs` — read-only views of a running
OwnSuite (ADR-033, issue #82).

Everything reads live state over the self-managed SSH tunnel (ADR-014) with
`kubectl get -o json` and parses it — no extra in-cluster workload, no
monitoring stack. The pure summarising functions (``summarise_*``) take
already-parsed kubectl JSON so they are unit-tested with fixtures, never a
live cluster.
"""

from __future__ import annotations

import json

from . import manifest, process, spec, tunnel
from .errors import SuiteError
from .process import run

NS = "ownsuite"
# App names from the single manifest; every app is off by default (ADR-035).
APPS = list(manifest.APPS)


def run_status(args):
    ctx = spec.load_context()
    process.preflight(["kubectl"], ssh=ctx.ssh, no_tunnel=args.no_tunnel)
    enabled = ctx.spec.enabled_apps()

    with tunnel.maybe(ctx.ssh, no_tunnel=args.no_tunnel):
        nodes = _kubectl_json(["get", "nodes"])
        clusters = _kubectl_json(["-n", NS, "get", "clusters.postgresql.cnpg.io"])
        certs = _kubectl_json(["-n", NS, "get", "certificates.cert-manager.io"])
        cronjobs = _kubectl_json(["-n", NS, "get", "cronjobs"])
        jobs = _kubectl_json(["-n", NS, "get", "jobs"])
        pods = _kubectl_json(["-n", NS, "get", "pods"])

    print(render(nodes, clusters, certs, cronjobs, jobs, pods, enabled))


def run_apps(args):
    """`suite apps` — the catalog: every available app, whether suite.yaml enables
    it, whether it is actually installed, its pod health, and its URL."""
    ctx = spec.load_context()
    process.preflight(["kubectl", "helm"], ssh=ctx.ssh, no_tunnel=args.no_tunnel)
    enabled = set(ctx.spec.enabled_apps())
    with tunnel.maybe(ctx.ssh, no_tunnel=args.no_tunnel):
        # helm v4 dropped `-a`/`--all`; `list` already reports every status by default.
        proc = run(["helm", "-n", NS, "list", "-o", "json"],
                   capture=True, check=False, step="helm list")
        installed = set()
        if proc.returncode == 0:
            installed = {r["name"] for r in json.loads(proc.stdout or "[]")}
        pods = (_kubectl_json(["-n", NS, "get", "pods"])
                if installed else {"items": []})

    rows = [("APP", "ENABLED", "INSTALLED", "HEALTH", "URL")]
    for name, app in manifest.APPS.items():
        deployed = any(r in installed for r in app.releases)
        if deployed:
            running, total, ready = summarise_app_pods(pods, name)
            health = "OK" if ready else f"{running}/{total} pods"
        else:
            health = "-"
        rows.append((
            name,
            "yes" if name in enabled else "no",
            "yes" if deployed else "no",
            health,
            f"https://{name}.{ctx.spec.domain}/" if deployed else "-",
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(f"{cell:<{w}}" for cell, w in zip(row, widths, strict=True)).rstrip())
    print("\nEnable an app: add it under `apps:` in suite.yaml, then `suite apply`.")


def run_logs(args):
    """`suite logs <app>` — tail the app's pods over the managed tunnel."""
    if args.app not in manifest.APPS:
        raise SuiteError(
            f"unknown app '{args.app}' (choose from: {', '.join(manifest.APPS)})"
        )
    ctx = spec.load_context()
    process.preflight(["kubectl"], ssh=ctx.ssh, no_tunnel=args.no_tunnel)
    with tunnel.maybe(ctx.ssh, no_tunnel=args.no_tunnel):
        pods = _kubectl_json(["-n", NS, "get", "pods"])
        names = [p["metadata"]["name"] for p in pods.get("items", [])
                 if _pod_app(p) == args.app]
        if not names:
            raise SuiteError(
                f"no pods found for {args.app} — is it deployed? (`suite apps`)"
            )
        for name in names:
            print(f"\n==> {name}")
            run(["kubectl", "-n", NS, "logs", name, "--all-containers",
                 f"--tail={args.tail}", "--prefix"], check=False,
                step=f"logs {name}")


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
    """(running, total, all_ready) for one app's long-running pods, matched on the
    app.kubernetes.io/name (or the `app` label) carrying the app name. One-shot
    Job/CronJob pods (migrations, file-cleanup crons) are excluded: they legitimately
    end Succeeded/Failed and are not service health, so counting them would flip a
    healthy app to FAIL (e.g. meet's clean_pending_files cron)."""
    items = [p for p in pods.get("items", [])
             if _pod_app(p) == app and not _job_pod(p)]
    total = len(items)
    running = sum(1 for p in items if p.get("status", {}).get("phase") == "Running")
    all_ready = total > 0 and all(
        _ready(p.get("status", {}).get("conditions")) for p in items
    )
    return running, total, all_ready


def _job_pod(pod):
    """True if the pod is owned by a Job (batch), i.e. a one-shot Job/CronJob pod."""
    owners = pod.get("metadata", {}).get("ownerReferences", [])
    return any(o.get("kind") == "Job" for o in owners)


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
