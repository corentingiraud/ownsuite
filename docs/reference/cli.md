# `suite` CLI reference

`suite` is the single command an operator uses: **`suite.yaml` describes the suite you
want, `suite apply` makes it real** (ADR-042). Every subcommand runs from **your
workstation** and reaches the cluster over a self-managed SSH tunnel (the Kubernetes
API is never exposed); commands open and close their own tunnel.

Two ways to invoke it (ADR-040):

- **`python -m suite <command>`** — always works from the repo checkout, no install
  step. This is what runs the first `suite deps`.
- **`suite <command>`** — the short form, once you install the CLI on your `PATH`:

  ```bash
  pipx install --editable .    # global `suite` command, available in any shell
  pipx ensurepath              # once, if pipx's bin dir isn't on your PATH yet
  ```

  `pipx` keeps the CLI in its own isolated environment yet on `PATH` everywhere — so
  `suite` works whether or not a project virtualenv is active. (A plain
  `pip install -e .` only puts `suite` on the venv's `PATH`; outside that venv, and with
  zsh `AUTO_CD` enabled, a bare `suite` in the repo root is read as `cd suite/` instead of
  the command. A global `pipx` install avoids that.) The docs use the `suite <command>`
  spelling throughout; substitute `python -m suite <command>` if you skip the pipx install.

Every operator action is a `suite` verb (ADR-037); `make` is only CI/dev shorthand
(lint, the test harnesses, low-level helmfile/ssh helpers). `make install` is kept as a
one-line alias for `suite apply`.

```text
suite init                         Questionnaire -> writes suite.yaml
suite plan                         Preview what apply would change (read-only)
suite apply                        Reconcile everything to suite.yaml -> print the URLs
suite apps                         App catalog: available / enabled / installed / healthy / URL
suite info                         URLs, admin credentials, DNS records
suite logs <app>                   Show an app's pod logs
suite user add|passwd|disable      Manage Keycloak users (one identity, all apps via JIT)
suite status                       Read-only health summary (node, DB, certs, backup, apps)
suite upgrade                      Apply pending chart/image upgrades (backup-gated)
suite backup                       Take a backup now and wait for it to complete
suite restore                      Restore a CLEAN cluster from off-site backups
suite destroy                      Uninstall the whole suite from the cluster (data kept)
suite deps                         Install Python tooling + Ansible collections
```

## Common conventions

**The files.** `suite.yaml` is the only file you edit — the full schema is in the
[configuration reference](configuration.md). The CLI maintains a machine state file
next to it (`.suite-state.json`: provisioned SSH target, provider-minted credentials,
change-detection inputs) — never edit it. Both are git-ignored.

**The connection.** The server SSH target comes from `suite.yaml` (`server.ssh`, for a
bring-your-own server) or from the machine state (written by provisioning). Commands
that talk to the cluster accept:

| Flag | Default | Meaning |
|---|---|---|
| `--no-tunnel` | off | Skip the tunnel and use the ambient `KUBECONFIG` (a tunnel is already open, or you have direct API access — e.g. CI on k3d). |

**The secret seed.** Every credential derives from `OWNSUITE_SECRET_SEED` (ADR-012); it
is never stored anywhere. Commands that need it use the exported value, or **prompt for
it** when you're at a terminal — a first `suite apply` offers to generate one and shows
it once (store it in your password manager). A fingerprint in the machine state makes
apply refuse a *wrong* seed instead of silently rotating every credential.

```bash
export OWNSUITE_SECRET_SEED=...        # from your password manager
```

`suite status`, `suite apps` and `suite logs` don't need it.

## `suite init`

Interactive questionnaire → writes `suite.yaml`: domain, admin email, where the server
comes from (Scaleway or bring-your-own), TLS mode, object storage, backups, and which apps
to enable. Refuses to overwrite an existing file — from then on you edit
`suite.yaml` directly. In CI, skip init and write the file yourself (see
[suite.yaml.example](https://github.com/corentingiraud/ownsuite/blob/main/suite.yaml.example)).

```bash
suite init      # then: suite plan / suite apply
```

## `suite plan`

Everything `apply` would do, **read-only**: the Terraform plan when the infra inputs
changed, the DNS records (+ per-resolver propagation status), the pending prune
(apps removed from `suite.yaml`), the snapshot posture, and the full `helmfile diff`.
Safe to run any time; changes nothing anywhere.

```bash
suite plan
```

## `suite apply`

Reconciles every layer to `suite.yaml`, touching only what changed:

1. **Infra** *(only when `provider` is set)* — Terraform provisions/updates the server,
   buckets and firewall. The app set drives the ports: enabling Meet opens its media
   ports, the Mailbox opens SMTP — no tfvars to edit.
2. **Bootstrap** — Ansible turns the bare server into a single-node K3s cluster; re-runs
   only when needed (never bootstrapped, or the firewall flags changed).
3. **DNS** *(skipped for `tls: selfsigned`)* — prints the records, writes the BIND zone
   file, and waits for propagation before triggering ACME.
4. **Apps** — one `helmfile apply` with the rails always on: the TLS issuer is pinned
   from `suite.yaml` (first production issuance proves HTTP-01 on Let's Encrypt
   *staging* before burning prod rate limits — ADR-019), a snapshot is taken before
   any change to a live cluster, the diff is shown and confirmed, apps removed from
   `suite.yaml` are uninstalled (**their databases, volumes and buckets are kept**),
   and every enabled app is health-checked over HTTPS — a failing app's releases are
   rolled back.
5. **Report** — the URLs, and where to go next.

Idempotent: `apply` on an unchanged `suite.yaml` is a no-op; re-run it to resume after
fixing anything.

```bash
$EDITOR suite.yaml       # e.g. add `tchap: {}` under apps:
suite apply              # plan -> confirm -> deploy -> "https://tchap.<domain>/"
```

| Flag | Default | Meaning |
|---|---|---|
| `--yes` | off | Skip every confirmation (unattended/CI). |
| `--no-snapshot` | off | Skip the pre-change backup (config-only change, no data at risk). |
| `--no-tunnel` | off | See [conventions](#common-conventions). |

## `suite apps`

The catalog: every available app, whether `suite.yaml` enables it, whether it is
actually installed, its pod health, and its URL. The fastest way to see what a
`suite apply` would add or remove.

```bash
suite apps
```

## `suite info`

Everything you need to hand out or file away: the URLs, the Keycloak admin credentials
(re-derived from the seed — nothing is read from the cluster), and the DNS records for
your domain. Needs the seed exported to show credentials; prints URLs without it.

```bash
suite info
```

## `suite logs`

Shows an app's pod logs over the managed tunnel — no `kubectl` incantations, no
hand-opened tunnel.

```bash
suite logs tchap
suite logs meet --tail 500
```

| Flag | Default | Meaning |
|---|---|---|
| `app` (positional) | — | One of the app names from `suite apps`. |
| `--tail N` | `100` | Lines per pod. |
| `--no-tunnel` | off | See [conventions](#common-conventions). |

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
| `--no-tunnel` | all | off | See [conventions](#common-conventions). |

Generated passwords are shown **once** — hand them over securely.

## `suite status`

A read-only, point-in-time health summary, printed `OK`/`FAIL` per check: node, the
PostgreSQL cluster (and last successful backup), every certificate, the off-site backup
job, and each **enabled** app's pods. Nothing runs on the server; safe to run any time.
Guide: [Status & monitoring](../operate/status.md).

```bash
suite status
```

## `suite upgrade`

The safe apply path for the version bumps Renovate proposes: it refuses unless backups
are on, takes a fresh pre-upgrade snapshot, shows the diff and asks to confirm, applies,
health-checks single sign-on and each enabled app, and **rolls back every release of an
app that fails**. Deliberately a separate verb from `apply` — version bumps are a
different risk profile (ADR-007/034). Guide: [Upgrading safely](../operate/upgrade.md).

```bash
suite upgrade            # interactive: shows the diff and asks before applying
suite upgrade --yes      # skip the confirmation (unattended)
```

| Flag | Default | Meaning |
|---|---|---|
| `--yes` | off | Skip the diff confirmation prompt. |
| `--no-tunnel` | off | See [conventions](#common-conventions). |

## `suite backup`

Takes a backup **now** — a PostgreSQL base backup plus the off-site object copy — and
waits for both to complete. The same snapshot `apply` and `upgrade` take before any
change, promoted to a verb for "before I try something" moments.
Guide: [Backups & restore](../operate/backups.md).

```bash
suite backup
```

## `suite restore`

Disaster recovery: rebuilds an instance from the off-site backups in restore mode (CNPG
recovery + the object/PVC restore Jobs). It refuses unless backups are configured (there
must be a source to restore from) and **refuses on a cluster that is not clean** — an
existing CNPG cluster or bound app PVCs means live data that restore would clobber. On a
non-clean cluster it asks for an explicit typed confirmation (`--yes` overrides it). After
the sync it verifies single sign-on and each enabled app over HTTPS.
Guide: [Backups & restore](../operate/backups.md).

```bash
suite restore            # restore onto a fresh cluster, then verify
suite restore --yes      # skip the not-clean safety confirmation (unattended)
```

| Flag | Default | Meaning |
|---|---|---|
| `--yes` | off | Skip the not-clean safety confirmation (non-interactive). |
| `--no-tunnel` | off | See [conventions](#common-conventions). |

Needs off-site backups configured in `suite.yaml` (`backup.enabled: true` + a target store).

## `suite destroy`

Uninstalls **every release** of the suite from the cluster, after a typed confirmation.
Data survives it: volumes, buckets and databases are kept (so is the server — tearing
that down is a separate `tofu destroy`). `suite apply` rebuilds from what was kept.

```bash
suite destroy
suite destroy --yes      # skip the typed confirmation (unattended)
```

## `suite deps`

One-time workstation setup: installs the CLI's runtime dependencies and the Ansible
collections the bootstrap needs (`pip install -r requirements.txt`,
`pip install -r requirements-dev.txt`, and the pinned `ansible-galaxy` collections). Run it
from a fresh checkout with `python -m suite` — the CLI needs nothing installed first.
Takes no flags. (This installs the tooling, not the short `suite` command itself — for
that, `pipx install --editable .`; see the [top of this page](#suite-cli-reference).)

```bash
python -m suite deps
```

### Shell autocomplete

`suite deps` does not touch your shell config. To get tab-completion for the subcommands
and flags, source the completion for your shell from your rc file (hand-maintained scripts,
no extra dependency):

```bash
# ~/.zshrc — the source line MUST come after `compinit`, or `compdef` isn't defined yet
# and completion silently does nothing:
#   autoload -Uz compinit; compinit
source /path/to/ownsuite/completions/suite.zsh
# ~/.bashrc
source /path/to/ownsuite/completions/suite.bash
```

Open a new shell (or `exec zsh`), then `suite <TAB>` lists the commands and
`suite user <TAB>` lists `add passwd disable`. To confirm it registered in zsh,
`echo $_comps[suite]` should print `_suite`.
