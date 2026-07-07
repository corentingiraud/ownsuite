"""`suite plan` / `suite apply` / `suite destroy` — reconcile reality to
suite.yaml (ADR-042).

apply reads the one human-owned file and converges every layer on it, scoped by
what actually changed:

  1. infra      terraform — only when the suite.yaml-derived inputs changed;
  2. bootstrap  ansible — only when never bootstrapped or the firewall flags changed;
  3. dns        records + propagation gate (skipped for selfsigned);
  4. apps       helmfile apply with the rails: TLS issuer pinned from suite.yaml
                (staging->prod ladder on first issuance, ADR-019), pre-change
                snapshot, full-tree diff + confirm, prune of apps removed from
                suite.yaml (uninstall only — data is kept), HTTPS health check,
                rollback of every release of a failed app;
  5. report     the URLs.

`suite plan` is the same computation with every mutation replaced by "would".
Re-running apply on an unchanged suite.yaml is a no-op end to end.
"""

from __future__ import annotations

import json
import os

from . import (
    backup,
    bootstrap,
    config,
    dns,
    ip,
    mail,
    manifest,
    process,
    propagation,
    provision,
    spec,
    state,
    steps,
    tunnel,
)
from .errors import SuiteError
from .process import run
from .upgrade import _confirm, _rollback, _show_diff

NS = "ownsuite"
# Helm release statuses that are healthy to apply over; anything else (failed,
# pending-*, uninstalling) is a leftover from an interrupted run worth flagging.
HEALTHY_STATUSES = {"deployed", "superseded"}


def run_plan(args):
    _run(args, plan_only=True)


def run_apply(args):
    _run(args, plan_only=False)


def _run(args, plan_only):
    sp = spec.load()
    st = state.load()
    config.require_seed(st)
    domain = sp.domain
    enabled = sp.enabled_apps()

    ssh = sp.ssh or st.get("ssh", "")
    tools = ["helmfile", "helm", "kubectl"]
    if sp.tls != "selfsigned":
        tools.append("dig")  # propagation gate
    process.preflight(tools, ssh=ssh, no_tunnel=args.no_tunnel)

    # The DKIM key must exist before the DNS records and the helmfile render.
    mail_dns = _mail_dns(sp, st, plan_only=plan_only) if "messages" in enabled else None

    # 1. infra (terraform) — only with a provider in suite.yaml; BYO servers skip it.
    if sp.provider:
        provision.ensure_infra(sp, st, assume_yes=args.yes, plan_only=plan_only)
        ssh = sp.ssh or st.get("ssh", "")

    env = spec.assemble_env(sp, st)
    view = {k: v for k, v in {**os.environ, **env}.items() if k.startswith("OWNSUITE_")}

    # 2. bootstrap (ansible) — no SSH target means an ambient cluster (CI/k3d).
    flags = spec.infra_flags(sp)
    if ssh and _needs_bootstrap(st, flags):
        if plan_only:
            print(f"\n==> Would bootstrap the server (ansible, firewall flags {flags})")
        else:
            provision.write_inventory(ssh)
            bootstrap.provision(extra_vars=flags)
            st["bootstrapped"] = True
            st["infra_flags"] = flags
            state.save(st)
    elif not ssh:
        print("  no server SSH target — using the ambient cluster/KUBECONFIG")

    # 3. dns — selfsigned needs none; ACME needs the records live first.
    if sp.tls != "selfsigned":
        ipv4 = steps.detect_ipv4(ssh)
        ipv6 = ip.detect_over_ssh(ssh, 6) if ssh else None
        steps.emit_dns(domain, ipv4, ipv6, mail_dns,
                       zone_path=None if plan_only else f"{domain}.zone")
        if plan_only:
            reached, lines = propagation.check(domain, ipv4)
            print("\n".join(lines))
            print(f"  propagation: {'ok' if reached else 'NOT ready — apply will wait'}")
        else:
            print("\n==> Waiting for DNS to propagate (before triggering ACME)...")
            if not propagation.wait(domain, ipv4):
                raise SuiteError("DNS did not propagate in time; not triggering ACME")

    # 4. apps (helmfile), inside the self-managed tunnel.
    with tunnel.maybe(ssh, no_tunnel=args.no_tunnel):
        installed = _helm_list()
        if installed is None:
            if plan_only:
                print("\n==> Cluster not reachable yet — apply would create everything "
                      "(bootstrap, then the full stack).")
                print("\n==> plan only — nothing was changed.")
                return
            raise SuiteError(
                "cluster unreachable — the bootstrap step did not leave a working "
                "kubeconfig/tunnel. Re-run `suite apply` once the server is up."
            )
        _warn_stuck(installed)
        passes = _tls_passes(sp.tls)
        prune = _prune_set(sp, installed)
        if prune:
            removed = sorted({manifest.RELEASE_TO_APP[r] for r in prune})
            print(f"\n==> Removed from suite.yaml: {', '.join(removed)} — will uninstall "
                  f"{', '.join(prune)}.")
            print("    Databases, volumes and buckets are KEPT (re-enable to reuse "
                  "them); the Keycloak client is left in place.")
        _maybe_snapshot(bool(installed), view, args, plan_only)
        _show_diff({**env, "OWNSUITE_TLS_ISSUER": passes[-1][0]})
        if plan_only:
            print("\n==> plan only — nothing was changed.")
            return
        if not args.yes and not _confirm():
            print("Aborted — no changes applied.")
            return
        # Prune before the helmfile pass: pods must die before platform-configuration
        # and postgres drop the pruned apps' secrets and Database CRs from the render.
        for release in prune:
            print(f"\n==> Uninstalling {release} (removed from suite.yaml — data kept)")
            run(["helm", "-n", NS, "uninstall", release, "--wait"],
                step=f"uninstall {release}")
        *ladder, (final_issuer, final_trusted) = passes
        for issuer, trusted in ladder:
            steps.issue(env, issuer, enabled)
            failed = steps.verify_https(domain, enabled, trusted=trusted)
            if failed:
                raise SuiteError(
                    f"HTTPS verification failed for: {', '.join(failed)} "
                    f"(issuer {issuer}) — fix and re-run, apply is idempotent."
                )
        steps.issue(env, final_issuer, enabled)
        failed = steps.verify_https(domain, enabled, trusted=final_trusted)
        if failed:
            _rollback(failed)
            raise SuiteError(
                "health check failed for: " + ", ".join(failed)
                + " — rolled back the affected app(s). Re-run once resolved."
            )
    state.save(st)

    # 5. report — every mutating command ends with what changed and where to go.
    print("\n==> Done. Your suite:")
    print(f"  auth       https://auth.{domain}/  (SSO)")
    for app in enabled:
        print(f"  {app:<10} https://{app}.{domain}/")
    if prune:
        removed = sorted({manifest.RELEASE_TO_APP[r] for r in prune})
        print(f"  removed    {', '.join(removed)} (data kept)")
    print("\n    Next: `suite user add <email>` for accounts, `suite info` for "
          "credentials, `suite status` for health.")


def run_destroy(args):
    """Uninstall every release of the suite (the old `make destroy`, with rails)."""
    sp = spec.load()
    st = state.load()
    config.require_seed(st)  # helmfile must render to know what to destroy
    ssh = sp.ssh or st.get("ssh", "")
    process.preflight(["helmfile", "kubectl"], ssh=ssh, no_tunnel=args.no_tunnel)
    if not args.yes:
        print("\nThis uninstalls EVERY release of the suite from the cluster.\n"
              "Data (volumes, buckets, provider resources, the server) is NOT deleted.")
        if input("Type 'destroy' to proceed: ").strip().lower() != "destroy":
            print("Aborted — nothing changed.")
            return
    env = spec.assemble_env(sp, st)
    with tunnel.maybe(ssh, no_tunnel=args.no_tunnel):
        # Render-only issuer pin: destroy templates the tree but applies nothing.
        env["OWNSUITE_TLS_ISSUER"] = _live_issuer() or "selfsigned"
        run(["helmfile", "-f", steps.HELMFILE, "destroy"], env=env,
            step="helmfile destroy")
    print("\n==> Suite removed. Volumes/buckets were kept; `suite apply` rebuilds.")
    if sp.provider:
        print(f"    Server teardown is separate: "
              f"tofu -chdir=terraform/environments/{sp.provider} destroy")


# --- helpers -----------------------------------------------------------------

def _needs_bootstrap(st, flags):
    return (not os.path.exists(tunnel.FETCHED_KUBECONFIG)
            or not st.get("bootstrapped")
            or st.get("infra_flags") != flags)


def _mail_dns(sp, st, *, plan_only):
    """MailDns for the records + a stable DKIM key for the helmfile render. Ambient
    env wins; else the key from the machine state; else generate one (persisted on
    apply — it must be stable across runs or outbound mail fails DKIM)."""
    key = os.environ.get("OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64") \
        or st.get("env", {}).get("OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64")
    if not key:
        key = mail.generate_dkim_private_b64()
        if plan_only:
            print("  mailbox: a DKIM key will be generated and stored on apply")
        else:
            st.setdefault("env", {})["OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64"] = key
            state.save(st)
            print("  generated the mailbox DKIM key (stored in the machine state)")
    opts = sp.app_options("messages")
    return dns.MailDns(
        mail_host=f"mail.{sp.domain}",
        spf_include=str(opts.get("spf_include", "spf.infomaniak.ch")),
        dkim_selector=str(opts.get("dkim_selector", "ownsuite")),
        dkim_public_key=mail.dkim_public_p(key),
        dmarc_rua=str(opts.get("dmarc_rua", "")),
    )


def _tls_passes(tls_mode):
    """[(issuer, trusted), ...]. suite.yaml owns the issuer — ambient
    OWNSUITE_TLS_ISSUER is deliberately stomped per pass, so nothing can silently
    downgrade the certs (the rail `suite sync` existed for). First prod issuance
    proves HTTP-01 on Let's Encrypt staging before burning prod rate limits."""
    target = spec.ISSUER_BY_TLS[tls_mode]
    if target != steps.PROD_ISSUER:
        return [(target, False)]
    if _live_issuer() == steps.PROD_ISSUER:
        return [(steps.PROD_ISSUER, True)]
    return [(steps.STAGING_ISSUER, False), (steps.PROD_ISSUER, True)]


def _live_issuer():
    proc = run(["kubectl", "-n", NS, "get", "certificate", "keycloak-tls",
                "-o", "jsonpath={.spec.issuerRef.name}"],
               capture=True, check=False, step="detect TLS issuer")
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _helm_list():
    """{release: status} in the workloads namespace, or None when the cluster is
    not reachable (fresh server / nothing bootstrapped yet)."""
    # helm v4 dropped `-a`/`--all`; `list` already reports every status by default.
    proc = run(["helm", "-n", NS, "list", "-o", "json"],
               capture=True, check=False, step="helm list")
    if proc.returncode != 0:
        return None
    try:
        return {r["name"]: r.get("status", "") for r in json.loads(proc.stdout or "[]")}
    except (ValueError, TypeError):
        return None


def _warn_stuck(installed):
    """Flag releases left in a non-healthy Helm state (e.g. `failed` from an
    interrupted run). Applying reconciles them; surfacing it tells the operator
    why a re-run was needed."""
    for name, st in installed.items():
        if st not in HEALTHY_STATUSES:
            print(f"  NOTE {name} is in Helm state '{st}' (likely an interrupted "
                  "run) — this apply will reconcile it.")


def _prune_set(sp, installed):
    """Installed releases whose app is no longer in suite.yaml, uninstall order
    (reverse of the helmfile order). Only manifest app releases — platform
    releases are never pruned."""
    enabled = set(sp.enabled_apps())
    prune = []
    for name, app in manifest.APPS.items():
        if name in enabled:
            continue
        prune += [r for r in reversed(app.releases) if r in installed]
    return prune


def _maybe_snapshot(cluster_in_use, view, args, plan_only):
    """The snapshot gate: nothing to lose on an empty cluster; backups on -> always
    snapshot; backups off on a live cluster -> explicit typed consent (a loud
    warning under --yes, which must never deadlock CI)."""
    backups_on = view.get("OWNSUITE_BACKUP_ENABLED", "false").lower() == "true"
    if not cluster_in_use:
        if plan_only:
            print("  snapshot: none (first bring-up — nothing to lose yet)")
        return
    if plan_only:
        print(f"  snapshot before apply: {'yes' if backups_on else 'NO — backups disabled'}")
        return
    if args.no_snapshot:
        print("  skipping the snapshot (--no-snapshot)")
        return
    if backups_on:
        backup.snapshot()
        return
    print("\nWARNING: backups are DISABLED (backup.enabled: false) — this change "
          "has no snapshot to fall back to.")
    if args.yes:
        return
    if input("Type 'no-backup' to proceed without a safety net: ").strip() != "no-backup":
        raise SuiteError(
            "aborted — enable backups in suite.yaml (backup: {enabled: true}) "
            "or re-run and type 'no-backup'."
        )
