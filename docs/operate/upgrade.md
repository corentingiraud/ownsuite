# Upgrading safely

New versions of the apps and the platform arrive as small, reviewable changes to the pinned
versions in the project — proposed automatically and merged when you're ready. `suite upgrade`
is how you apply them to your server **without risking your data**.

The command will not upgrade unless backups are enabled, and it always takes a fresh backup
**before** touching anything. If the upgrade leaves an app unhealthy, it rolls that app back to
the version that was working.

```bash
set -a && source .env && set +a       # OWNSUITE_SECRET_SEED + OWNSUITE_SERVER_SSH

suite upgrade
```

## What it does, step by step

1. **Checks backups are on.** If off-site backups are disabled, it refuses and stops — an
   upgrade without a recovery net is not allowed.
2. **Takes a pre-upgrade snapshot.** It runs the same on-demand backup as `make backup` (a
   database base backup plus an off-site copy of your files), so you have a clean restore point
   from the moment just before the change.
3. **Shows you the diff.** It prints exactly what would change and asks you to confirm. Nothing
   is applied until you say yes. Use `--yes` to skip the prompt (for unattended runs).
4. **Applies the upgrade.**
5. **Checks health.** It verifies that single sign-on and each enabled app still answer over
   HTTPS.
6. **Rolls back on failure.** If any app fails its health check, that app is rolled back to its
   previous version automatically, and the command exits with an error telling you what failed.

If everything passes, you're done — running the newer version with the same data.

## Before and after

Run [`suite status`](status.md) before you upgrade to confirm everything is healthy, and again
afterwards to see the result. If an upgrade rolled something back, fix the cause (check the
release notes for that version) and re-run `suite upgrade`.

## How it connects

`suite upgrade` works over the same private SSH tunnel as the rest of the admin commands, and
needs your `OWNSUITE_SECRET_SEED` exported (to render the deployment). Add `--no-tunnel` if a
tunnel is already open or you have a working `KUBECONFIG`; point it elsewhere with
`--ssh user@host`.

!!! warning "The snapshot is your safety net"
    A rollback restores the previous **version**, but only the pre-upgrade **backup** can undo
    data changes. That's why backups are mandatory: keep your `OWNSUITE_SECRET_SEED` and the
    backup passphrase safe, or a restore won't be possible. See
    [Backups & restore](backups.md).
