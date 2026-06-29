# `suite` CLI reference

`suite` is the single command an operator uses after the server is bootstrapped: it
installs the stack, manages users, reports health, and applies upgrades. Every
subcommand runs from **your workstation** and reaches the cluster over the SSH tunnel
(the Kubernetes API is never exposed); it adds no Python dependencies of its own.

Run it as `python -m suite <command>`. Every operator action is a `suite` verb (ADR-037);
`make` is now only CI/dev shorthand (lint, the test harnesses, low-level helmfile/ssh helpers).
`make install` is kept as a one-line alias for `suite install`.

```text
suite deps                         Install Python tooling + Ansible collections
suite bootstrap                    Provision a bare server into a single-node K3s cluster
suite check                        Dry-run the bootstrap (--check --diff); applies nothing
suite install                      Guided install: bare server + domain → HTTPS
suite user add|passwd|disable      Manage Keycloak users (one identity, all apps via JIT)
suite status                       Read-only health summary (node, DB, certs, backup, apps)
suite upgrade                      Apply pending chart/image upgrades (backup-gated)
suite restore                      Restore a CLEAN cluster from off-site backups
```

## Common conventions

Most subcommands share the same connection and configuration flags:

| Flag | Default | Meaning |
|---|---|---|
| `--env-file PATH` | `.env` | Where non-secret `OWNSUITE_*` config is read from. |
| `--ssh user@host` | from `.env` (`OWNSUITE_SERVER_SSH`) | Server SSH target, used to open the tunnel. |
| `--no-tunnel` | off | Skip the tunnel and use the ambient `KUBECONFIG` (a tunnel is already open, or you have direct API access). |

**The secret seed.** `suite user`, `suite upgrade` and `suite restore` need
`OWNSUITE_SECRET_SEED` exported — the first to re-derive the Keycloak admin password, the
others to render the deployment. `suite install` generates the seed on a first run (and prints it once);
`suite status` does **not** need it. Load your config and seed before running:

```bash
set -a && source .env && set +a       # OWNSUITE_SERVER_SSH and other OWNSUITE_* config
export OWNSUITE_SECRET_SEED=...        # from your password manager (never written to .env)
```

See the [configuration reference](configuration.md) for every `OWNSUITE_*` variable.

## `suite deps`

One-time workstation setup: installs the Python tooling and Ansible collections this CLI and
the bootstrap need (`pip install -r requirements-dev.txt` + the pinned `ansible-galaxy`
collections). Run it from a fresh checkout — `suite` itself is pure standard library, so no
dependencies are needed to run `suite deps`. Takes no flags.

```bash
python -m suite deps
```

## `suite bootstrap`

Provisions a bare Debian server into a ready **single-node K3s** cluster via the Ansible
playbook (`common` → `security` → `k3s`), then fetches the kubeconfig back to you. The server
is read from the Ansible inventory (`ansible/inventory/hosts.yml`); takes no flags. Full
walkthrough: [Server bootstrap](../get-started/bootstrap.md).

```bash
python -m suite bootstrap
```

## `suite check`

Dry-runs the bootstrap (`ansible-playbook --check --diff`): shows what would change and
**applies nothing**. Use it before `suite bootstrap` to review the plan. Takes no flags.

```bash
python -m suite check
```

## `suite install`

Takes a bare server + a domain to all-in-HTTPS, end to end. Idempotent — re-run it to
resume after fixing anything. Full walkthrough: [Guided install](../get-started/install.md).

```bash
make install                                   # = python -m suite install
python -m suite install --tls-mode staging     # pass flags via python -m
```

| Flag | Default | Meaning |
|---|---|---|
| `--domain DOMAIN` | prompted / `.env` | Base domain (each app is `<name>.{domain}`). |
| `--ssh user@host` | prompted / `.env` | Server SSH target (bootstrap, public-IP detection, tunnel). |
| `--public-ip IPV4` | detected over SSH | Override the detected server public IPv4 in the DNS records. |
| `--tls-mode selfsigned\|staging\|prod` | `prod` | `prod` issues Let's Encrypt staging then production; `staging` stops at staging (untrusted leaf); `selfsigned` skips DNS/ACME (CI / local). |
| `--non-interactive` | off | No prompts — read config from `.env` + flags (CI). |
| `--skip-bootstrap` | off | Don't run the Ansible bootstrap (server already provisioned). |
| `--skip-dns` | off | Don't print/handle DNS records. |
| `--skip-propagation` | off | Don't wait for DNS to propagate before ACME. |
| `--env-file`, `--no-tunnel` | see [conventions](#common-conventions) | |

## `suite user`

Provisions Keycloak identities. Creating a user **once** grants access to every enabled
app on first login (just-in-time — no per-app step). Guide: [Users](../operate/users.md).

```bash
suite user add alice@assoc.org        # create (or update) + show a one-time password
suite user passwd alice@assoc.org     # reset the password
suite user disable alice@assoc.org    # deactivate (revokes access to all apps at once)
```

| Flag | Applies to | Default | Meaning |
|---|---|---|---|
| `email` (positional) | all | — | The user's email, also their username. |
| `--password PW` | `add`, `passwd` | generated | Set this password instead of a generated one. |
| `--permanent` | `add`, `passwd` | off (temporary) | Don't force a password change at next login. |
| `--first-name NAME` | `add` | email local part | First name (Keycloak's profile requires one). |
| `--last-name NAME` | `add` | email local part | Last name. |
| `--local-port PORT` | all | `8081` | Local port for the Keycloak port-forward. |
| `--env-file`, `--ssh`, `--no-tunnel` | all | see [conventions](#common-conventions) | |

Generated passwords are shown **once** — hand them over securely.

## `suite status`

A read-only, point-in-time health summary, printed `OK`/`FAIL` per check: node, the
PostgreSQL cluster (and last successful backup), every certificate, the off-site backup
job, and each **enabled** app's pods. Nothing runs on the server; safe to run any time.
Guide: [Status & monitoring](../operate/status.md).

```bash
suite status
```

| Flag | Default | Meaning |
|---|---|---|
| `--env-file`, `--ssh`, `--no-tunnel` | see [conventions](#common-conventions) | |

Does **not** need `OWNSUITE_SECRET_SEED`.

## `suite upgrade`

The safe apply path for the version bumps Renovate proposes: it refuses unless backups
are on, takes a fresh pre-upgrade snapshot, shows the diff and asks to confirm, applies,
health-checks single sign-on and each enabled app, and rolls back any release that fails.
Guide: [Upgrading safely](../operate/upgrade.md).

```bash
suite upgrade            # interactive: shows the diff and asks before applying
suite upgrade --yes      # skip the confirmation (unattended)
```

| Flag | Default | Meaning |
|---|---|---|
| `--yes` | off | Skip the diff confirmation prompt. |
| `--env-file`, `--ssh`, `--no-tunnel` | see [conventions](#common-conventions) | |

Needs `OWNSUITE_SECRET_SEED` exported (to render the deployment).

## `suite restore`

Disaster recovery: rebuilds an instance from the off-site backups in restore mode (CNPG
recovery + the object/PVC restore Jobs). It refuses unless backups are configured (there
must be a source to restore from) and **refuses on a cluster that is not clean** — an
existing CNPG cluster or bound app PVCs means live data that restore would clobber. On a
non-clean cluster it asks for an explicit typed confirmation (`--yes` overrides it). After
the sync it verifies single sign-on and each enabled app over HTTPS. `make restore` is the
underlying low-level mechanism this wraps. Guide: [Backups & restore](../operate/backups.md).

```bash
suite restore            # restore onto a fresh cluster, then verify
suite restore --yes      # skip the not-clean safety confirmation (unattended)
```

| Flag | Default | Meaning |
|---|---|---|
| `--yes` | off | Skip the not-clean safety confirmation (non-interactive). |
| `--env-file`, `--ssh`, `--no-tunnel` | see [conventions](#common-conventions) | |

Needs `OWNSUITE_SECRET_SEED` exported (to render the deployment) and off-site backups
configured (`OWNSUITE_BACKUP_ENABLED=true` + a target store).
