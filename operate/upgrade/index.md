# Upgrading safely

New versions of the apps and the platform arrive as small, reviewable changes to the pinned versions in the project — proposed automatically and merged when you're ready. `suite upgrade` is how you apply them to your server **without risking your data**.

The command will not upgrade unless backups are enabled, and it always takes a fresh backup **before** touching anything. If the upgrade leaves an app unhealthy, it rolls that app back to the version that was working.

```
set -a && source .env && set +a       # OWNSUITE_SECRET_SEED + OWNSUITE_SERVER_SSH

suite upgrade
```

## What it does, step by step

1. **Checks backups are on.** If off-site backups are disabled, it refuses and stops — an upgrade without a recovery net is not allowed.
1. **Takes a pre-upgrade snapshot.** It runs the same on-demand backup as `make backup` (a database base backup plus an off-site copy of your files), so you have a clean restore point from the moment just before the change.
1. **Shows you the diff.** It prints exactly what would change and asks you to confirm. Nothing is applied until you say yes. Use `--yes` to skip the prompt (for unattended runs).
1. **Applies the upgrade.**
1. **Checks health.** It verifies that single sign-on and each enabled app still answer over HTTPS.
1. **Rolls back on failure.** If any app fails its health check, that app is rolled back to its previous version automatically, and the command exits with an error telling you what failed.

If everything passes, you're done — running the newer version with the same data.

## Before and after

Run [`suite status`](https://corentingiraud.github.io/ownsuite/operate/status/index.md) before you upgrade to confirm everything is healthy, and again afterwards to see the result. If an upgrade rolled something back, fix the cause (check the release notes for that version) and re-run `suite upgrade`.

## How it connects

`suite upgrade` works over the same private SSH tunnel as the rest of the admin commands, and needs your `OWNSUITE_SECRET_SEED` exported (to render the deployment). Add `--no-tunnel` if a tunnel is already open or you have a working `KUBECONFIG`; point it elsewhere with `--ssh user@host`.

The snapshot is your safety net

A rollback restores the previous **version**, but only the pre-upgrade **backup** can undo data changes. That's why backups are mandatory: keep your `OWNSUITE_SECRET_SEED` and the backup passphrase safe, or a restore won't be possible. See [Backups & restore](https://corentingiraud.github.io/ownsuite/operate/backups/index.md).

## Surgical change to one component

Sometimes you need to reapply **one** component — say you changed a single app's config and want it live without reconciling everything else. `suite sync` does exactly that, keeping the same rails as `suite upgrade` but scoped to the releases you name:

```
set -a && source .env && set +a       # OWNSUITE_SECRET_SEED + OWNSUITE_SERVER_SSH

suite sync --app drive                # drive's whole release group (ingress + app + media proxy)
suite sync -l drive-media-proxy       # just one release, by name
```

It takes a pre-sync snapshot, shows a diff **limited to those releases**, applies only them, and health-checks (and, on failure, rolls back) **only** the affected app — nothing else in the stack is touched. Crucially, it always applies the TLS issuer that's actually in force, so a targeted sync can never silently reissue your certificates as self-signed.

For a config-only change with no data at risk, skip the snapshot:

```
suite sync -l drive-media-proxy --no-snapshot
```

Use this instead of a hand-run `helmfile -l`

Running `helmfile -l name=… sync` by hand skips the snapshot, the health check **and** the TLS issuer injection — the last silently downgrades live certificates to `selfsigned`. `suite sync` is the safe way to target a single release.
