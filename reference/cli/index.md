# `suite` CLI reference

`suite` is the single command an operator uses after the server is bootstrapped: it installs the stack, manages users, reports health, and applies upgrades. Every subcommand runs from **your workstation** and reaches the cluster over the SSH tunnel (the Kubernetes API is never exposed); it adds no Python dependencies of its own.

Two ways to invoke it (ADR-040):

- **`python -m suite <command>`** — always works from the repo checkout, no install step. This is what runs the first `suite deps`.
- **`suite <command>`** — the short form, once you install the CLI on your `PATH`:

```
pipx install --editable .    # global `suite` command, available in any shell
pipx ensurepath              # once, if pipx's bin dir isn't on your PATH yet
```

`pipx` keeps the CLI in its own isolated environment yet on `PATH` everywhere — so `suite` works whether or not a project virtualenv is active. (A plain `pip install -e .` only puts `suite` on the venv's `PATH`; outside that venv, and with zsh `AUTO_CD` enabled, a bare `suite` in the repo root is read as `cd suite/` instead of the command. A global `pipx` install avoids that.) The docs use the `suite <command>` spelling throughout; substitute `python -m suite <command>` if you skip the pipx install.

Every operator action is a `suite` verb (ADR-037); `make` is now only CI/dev shorthand (lint, the test harnesses, low-level helmfile/ssh helpers). `make install` is kept as a one-line alias for `suite install`.

```
suite deps                         Install Python tooling + Ansible collections
suite bootstrap                    Provision a bare server into a single-node K3s cluster
suite check                        Dry-run the bootstrap (--check --diff); applies nothing
suite install                      Guided install: bare server + domain → HTTPS
suite dns                          Print the DNS records and write the BIND zone file (no install)
suite user add|passwd|disable      Manage Keycloak users (one identity, all apps via JIT)
suite status                       Read-only health summary (node, DB, certs, backup, apps)
suite upgrade                      Apply pending chart/image upgrades (backup-gated)
suite sync                         Apply ONE release/app with the upgrade rails (targeted)
suite restore                      Restore a CLEAN cluster from off-site backups
```

## Common conventions

Most subcommands share the same connection and configuration flags:

| Flag              | Default                             | Meaning                                                                                                     |
| ----------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `--env-file PATH` | `.env`                              | Where non-secret `OWNSUITE_*` config is read from.                                                          |
| `--ssh user@host` | from `.env` (`OWNSUITE_SERVER_SSH`) | Server SSH target, used to open the tunnel.                                                                 |
| `--no-tunnel`     | off                                 | Skip the tunnel and use the ambient `KUBECONFIG` (a tunnel is already open, or you have direct API access). |

**The secret seed.** `suite user`, `suite upgrade` and `suite restore` need `OWNSUITE_SECRET_SEED` exported — the first to re-derive the Keycloak admin password, the others to render the deployment. `suite install` generates the seed on a first run (and prints it once); `suite status` does **not** need it. Load your config and seed before running:

```
set -a && source .env && set +a       # OWNSUITE_SERVER_SSH and other OWNSUITE_* config
export OWNSUITE_SECRET_SEED=...        # from your password manager (never written to .env)
```

See the [configuration reference](https://corentingiraud.github.io/ownsuite/reference/configuration/index.md) for every `OWNSUITE_*` variable.

## `suite deps`

One-time workstation setup: installs the CLI's runtime dependency and the Ansible collections the bootstrap needs (`pip install -r requirements.txt`, `pip install -r requirements-dev.txt`, and the pinned `ansible-galaxy` collections). Run it from a fresh checkout with `python -m suite` — `suite` is pure standard library, so nothing needs to be installed first. Takes no flags. (This installs the tooling, not the short `suite` command itself — for that, `pipx install --editable .`; see the [top of this page](#suite-cli-reference).)

```
python -m suite deps
```

### Shell autocomplete

`suite deps` does not touch your shell config. To get tab-completion for the subcommands and flags, source the completion for your shell from your rc file (hand-maintained scripts, no extra dependency):

```
# ~/.zshrc — the source line MUST come after `compinit`, or `compdef` isn't defined yet
# and completion silently does nothing:
#   autoload -Uz compinit; compinit
source /path/to/ownsuite/completions/suite.zsh
# ~/.bashrc
source /path/to/ownsuite/completions/suite.bash
```

Open a new shell (or `exec zsh`), then `suite <TAB>` lists the commands and `suite user <TAB>` lists `add passwd disable`. To confirm it registered in zsh, `echo $_comps[suite]` should print `_suite`.

## `suite bootstrap`

Provisions a bare Debian server into a ready **single-node K3s** cluster via the Ansible playbook (`common` → `security` → `k3s`), then fetches the kubeconfig back to you. The server is read from the Ansible inventory (`ansible/inventory/hosts.yml`); takes no flags. Full walkthrough: [Server bootstrap](https://corentingiraud.github.io/ownsuite/get-started/bootstrap/index.md).

```
suite bootstrap
```

## `suite check`

Dry-runs the bootstrap (`ansible-playbook --check --diff`): shows what would change and **applies nothing**. Use it before `suite bootstrap` to review the plan. Takes no flags.

```
suite check
```

## `suite install`

Takes a bare server + a domain to all-in-HTTPS, end to end. Idempotent — re-run it to resume after fixing anything. Full walkthrough: [Guided install](https://corentingiraud.github.io/ownsuite/get-started/install/index.md).

```
suite install                          # or `make install`, a one-line alias
suite install --tls-mode staging       # with flags
```

| Flag                                   | Default                                | Meaning                                                                                                                                     |
| -------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `--domain DOMAIN`                      | prompted / `.env`                      | Base domain (each app is `<name>.{domain}`).                                                                                                |
| `--ssh user@host`                      | prompted / `.env`                      | Server SSH target (bootstrap, public-IP detection, tunnel).                                                                                 |
| `--public-ip IPV4`                     | detected over SSH                      | Override the detected server public IPv4 in the DNS records.                                                                                |
| `--tls-mode selfsigned\|staging\|prod` | `prod`                                 | `prod` issues Let's Encrypt staging then production; `staging` stops at staging (untrusted leaf); `selfsigned` skips DNS/ACME (CI / local). |
| `--non-interactive`                    | off                                    | No prompts — read config from `.env` + flags (CI).                                                                                          |
| `--skip-bootstrap`                     | off                                    | Don't run the Ansible bootstrap (server already provisioned).                                                                               |
| `--skip-dns`                           | off                                    | Don't print/handle DNS records.                                                                                                             |
| `--skip-propagation`                   | off                                    | Don't wait for DNS to propagate before ACME.                                                                                                |
| `--env-file`, `--no-tunnel`            | see [conventions](#common-conventions) |                                                                                                                                             |

## `suite dns`

Prints the DNS records for your domain and writes a **BIND zone file** (`<domain>.zone`, `$ORIGIN`/`$TTL` + records, no SOA/NS) you can import at your registrar — the same records `suite install` emits, but on demand and without touching the cluster. Useful to regenerate the zone after a server IP change, or to prepare DNS before installing. If the mailbox is enabled it also includes the mail records. Needs no `OWNSUITE_SECRET_SEED`.

```
suite dns --domain assoc.example.org --public-ip 203.0.113.10
suite dns --ssh root@server --out /tmp/assoc.zone     # detect the IP over SSH
```

| Flag                  | Default                                | Meaning                                      |
| --------------------- | -------------------------------------- | -------------------------------------------- |
| `--domain DOMAIN`     | `.env` (`OWNSUITE_DOMAIN`)             | Base domain (each app is `<name>.{domain}`). |
| `--public-ip IPV4`    | detected over SSH / prompted           | Server public IPv4 for the address records.  |
| `--out PATH`          | `<domain>.zone`                        | Where to write the BIND zone file.           |
| `--env-file`, `--ssh` | see [conventions](#common-conventions) |                                              |

## `suite user`

Provisions Keycloak identities. Creating a user **once** grants access to every enabled app on first login (just-in-time — no per-app step). Guide: [Users](https://corentingiraud.github.io/ownsuite/operate/users/index.md).

```
suite user add alice@assoc.org        # create (or update) + show a one-time password
suite user passwd alice@assoc.org     # reset the password
suite user disable alice@assoc.org    # deactivate (revokes access to all apps at once)
```

| Flag                                 | Applies to      | Default                                | Meaning                                       |
| ------------------------------------ | --------------- | -------------------------------------- | --------------------------------------------- |
| `email` (positional)                 | all             | —                                      | The user's email, also their username.        |
| `--password PW`                      | `add`, `passwd` | generated                              | Set this password instead of a generated one. |
| `--permanent`                        | `add`, `passwd` | off (temporary)                        | Don't force a password change at next login.  |
| `--first-name NAME`                  | `add`           | email local part                       | First name (Keycloak's profile requires one). |
| `--last-name NAME`                   | `add`           | email local part                       | Last name.                                    |
| `--local-port PORT`                  | all             | `8081`                                 | Local port for the Keycloak port-forward.     |
| `--env-file`, `--ssh`, `--no-tunnel` | all             | see [conventions](#common-conventions) |                                               |

Generated passwords are shown **once** — hand them over securely.

## `suite status`

A read-only, point-in-time health summary, printed `OK`/`FAIL` per check: node, the PostgreSQL cluster (and last successful backup), every certificate, the off-site backup job, and each **enabled** app's pods. Nothing runs on the server; safe to run any time. Guide: [Status & monitoring](https://corentingiraud.github.io/ownsuite/operate/status/index.md).

```
suite status
```

| Flag                                 | Default                                | Meaning |
| ------------------------------------ | -------------------------------------- | ------- |
| `--env-file`, `--ssh`, `--no-tunnel` | see [conventions](#common-conventions) |         |

Does **not** need `OWNSUITE_SECRET_SEED`.

## `suite upgrade`

The safe apply path for the version bumps Renovate proposes: it refuses unless backups are on, takes a fresh pre-upgrade snapshot, shows the diff and asks to confirm, applies, health-checks single sign-on and each enabled app, and rolls back any release that fails. Guide: [Upgrading safely](https://corentingiraud.github.io/ownsuite/operate/upgrade/index.md).

```
suite upgrade            # interactive: shows the diff and asks before applying
suite upgrade --yes      # skip the confirmation (unattended)
```

| Flag                                 | Default                                | Meaning                            |
| ------------------------------------ | -------------------------------------- | ---------------------------------- |
| `--yes`                              | off                                    | Skip the diff confirmation prompt. |
| `--env-file`, `--ssh`, `--no-tunnel` | see [conventions](#common-conventions) |                                    |

Needs `OWNSUITE_SECRET_SEED` exported (to render the deployment).

## `suite sync`

A **targeted** apply for a surgical change to one component (e.g. one media proxy), with the same rails as `upgrade` but scoped to the releases you name: it takes a pre-sync snapshot, shows a diff limited to those releases, `helmfile sync`s only them (never a full-tree reconcile), then health-checks and rolls back **only** the affected app(s). It always injects the live TLS issuer, so a targeted sync can never silently downgrade your certificates to `selfsigned`. Guide: [Upgrading safely](https://corentingiraud.github.io/ownsuite/operate/upgrade/#surgical-change-to-one-component).

```
suite sync --app drive              # the whole drive release group (ingress + app + media proxy)
suite sync -l drive-media-proxy     # a single release by name (repeatable)
suite sync -l drive-media-proxy --no-snapshot   # config-only change, no data at risk
```

| Flag                                 | Default                                | Meaning                                                                                                  |
| ------------------------------------ | -------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `--app NAME`                         | —                                      | Sync a whole app's release group (`docs`, `drive`, `grist`, `projects`, `messages`, `meet`). Repeatable. |
| `-l`, `--selector RELEASE`           | —                                      | Sync a single release by name. Repeatable; combines with `--app`.                                        |
| `--no-snapshot`                      | off                                    | Skip the pre-sync backup (only for a config-only change with no data risk; also skips the backups gate). |
| `--yes`                              | off                                    | Skip the diff confirmation prompt.                                                                       |
| `--env-file`, `--ssh`, `--no-tunnel` | see [conventions](#common-conventions) |                                                                                                          |

At least one `--app` or `-l` is required. Needs `OWNSUITE_SECRET_SEED` exported (to render the deployment).

## `suite restore`

Disaster recovery: rebuilds an instance from the off-site backups in restore mode (CNPG recovery + the object/PVC restore Jobs). It refuses unless backups are configured (there must be a source to restore from) and **refuses on a cluster that is not clean** — an existing CNPG cluster or bound app PVCs means live data that restore would clobber. On a non-clean cluster it asks for an explicit typed confirmation (`--yes` overrides it). After the sync it verifies single sign-on and each enabled app over HTTPS. `make restore` is the underlying low-level mechanism this wraps. Guide: [Backups & restore](https://corentingiraud.github.io/ownsuite/operate/backups/index.md).

```
suite restore            # restore onto a fresh cluster, then verify
suite restore --yes      # skip the not-clean safety confirmation (unattended)
```

| Flag                                 | Default                                | Meaning                                                   |
| ------------------------------------ | -------------------------------------- | --------------------------------------------------------- |
| `--yes`                              | off                                    | Skip the not-clean safety confirmation (non-interactive). |
| `--env-file`, `--ssh`, `--no-tunnel` | see [conventions](#common-conventions) |                                                           |

Needs `OWNSUITE_SECRET_SEED` exported (to render the deployment) and off-site backups configured (`OWNSUITE_BACKUP_ENABLED=true` + a target store).
