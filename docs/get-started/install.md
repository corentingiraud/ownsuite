# Guided install (`suite apply`)

Take a **bare cloud account (or server) + a domain to all-in-HTTPS by editing one file**.
`suite.yaml` describes the suite you want; `suite apply` makes it real (ADR-042) — it rolls
the whole sequence (provision → prepare → configure → deploy → get certificates → check)
into one command you can safely re-run.

> **What you get:** you answer `suite init`'s questionnaire, run `suite apply`, follow the
> "create these DNS records" screen, and every app ends up served over HTTPS with real
> Let's Encrypt certificates.

## Before you start

Everything runs from **your own computer** — nothing extra is installed on the server
beyond what the bootstrap phase sets up.

1. **Install these CLI tools** on your workstation (`suite apply` orchestrates them; its
   Python dependencies are installed by `suite deps`):

    | Tool | Used for | Get it |
    |---|---|---|
    | `helm` + `helmfile` | deploy the stack | [helm.sh](https://helm.sh/docs/intro/install/) · [helmfile releases](https://github.com/helmfile/helmfile/releases) |
    | `kubectl` | talk to the cluster | [kubernetes.io](https://kubernetes.io/docs/tasks/tools/) |
    | `terraform` **or** `tofu` | provision the server (only with a `provider`) | [opentofu.org](https://opentofu.org/) |
    | `dig` | DNS propagation check | `apt install dnsutils` (Debian/Ubuntu) · `brew install bind` (macOS) |
    | `ssh`, `python3` ≥ 3.10 | tunnel, the CLI | usually already present |

    Then clone the repo and install the CLI's own dependencies:

    ```bash
    git clone https://github.com/corentingiraud/ownsuite.git && cd ownsuite
    python3 -m suite deps        # one-time: Python tooling + Ansible collections + the helm-diff plugin
    ```

    `suite deps` also installs the pinned **helm-diff** plugin into helm's plugin
    dir — `helmfile apply`/`diff` shell out to `helm diff`, which helm has no
    built-in command for. (`suite apply` fails fast with a clear message if it is
    missing.)

    The docs write `suite <command>`; that short spelling comes from a one-time
    `pipx install --editable .` — or substitute `python3 -m suite <command>` throughout
    (see the [CLI reference](../reference/cli.md)).

2. **A domain** whose DNS records you can edit at your registrar.
3. **A size for the server.** OwnSuite runs on **one** machine, so which VPS you rent is a
   first decision — pick it against the apps you plan to enable **before** you provision.
   See [Server sizing](../operate/sizing.md): a common Docs + Drive start is **8 GB /
   2 vCPU / 40 GB**, stepping up for the Mailbox or Meet.
4. **Somewhere for the server to come from** — a [Scaleway](provision.md) account
   (`suite apply` provisions the server, buckets and firewall; export the provider
   credentials first), **or** your own Debian 12/13 server reachable over SSH (set
   `server: {ssh: user@host}` in `suite.yaml` and omit `provider`; read the SSH-key
   warning in [Server bootstrap](bootstrap.md#caveats) first).

## Describe the suite (`suite init`)

```bash
suite init
```

An interactive questionnaire writes `suite.yaml`: the domain, admin email, where the
server comes from, TLS mode, object-storage mode, backups (yes/no), and **which apps to
enable** (a checkbox — every app is off by default). From then on you edit the file
directly — it is the **one** human-owned file (git-ignored; commented template:
[`suite.yaml.example`](https://github.com/corentingiraud/ownsuite/blob/main/suite.yaml.example),
full schema: [Configuration reference](../reference/configuration.md)):

```yaml
provider: scaleway
domain: assoc.example.org
admin_email: admin@assoc.example.org
tls: prod
backup: {enabled: true, target: external}
apps:
  docs: {}
  drive: {}
```

## Preview (`suite plan`)

```bash
suite plan
```

Read-only: the Terraform plan when the infra inputs changed, the DNS records (and their
propagation status), any pending prune, and the full `helmfile diff`. Run it whenever —
it changes nothing anywhere.

## Make it real (`suite apply`)

```bash
suite apply
```

A first run offers to generate the secret seed and shows it **once**.

!!! danger "Store the seed now"
    `OWNSUITE_SECRET_SEED` is never written anywhere. Every password and key is derived
    from it. Save it in your password manager. To resume later, re-export it
    (`export OWNSUITE_SECRET_SEED=...`) — or let the command prompt you for it.

!!! tip "`.env` is auto-loaded — no `source .env`"
    The CLI reads a git-ignored `.env` in the repo root at startup, so any `OWNSUITE_*`
    you keep there — the seed, or external S3/backup/relay credentials when you bring your
    own storage — is picked up on every `suite` command. An already-exported variable still
    wins over the file.

`apply` then reconciles every layer, touching only what changed; if anything stops you,
fix it and re-run `suite apply` to resume:

1. **Provision** *(only with a `provider`)* — Terraform creates/updates the server,
   buckets and firewall. The firewall ports follow the app set (enabling Meet opens its
   media ports, the Mailbox opens SMTP). See [Provision the server](provision.md).
2. **Bootstrap** — Ansible turns the bare server into a hardened single-node K3s cluster;
   re-run only when needed. See [Server bootstrap](bootstrap.md).
3. **DNS records** — detects the server public IP and prints the exact records to create
   at your registrar:

    | Name | Type | Value | TTL |
    |---|---|---|---|
    | `{domain}` | A | _your server IPv4_ | 300 |
    | `*.{domain}` | CNAME | `{domain}.` | 300 |
    | `{domain}` | CAA | `0 issue "letsencrypt.org"` | 300 |

    The apex holds the address once; the wildcard **CNAME → apex** covers every subdomain
    (`auth.`, `docs.`, and future apps), so if the IP changes you edit a single record. An
    `AAAA` row is added at the apex when the server has public IPv6 (the CNAME follows it —
    no second wildcard needed). A wildcard record is not a wildcard *certificate* —
    certificates are still issued per host.

    A **BIND zone file** (`./{domain}.zone`) is also written with these records
    (`$ORIGIN`/`$TTL` + records, no SOA/NS) so you can import them in one step if your
    registrar supports zone-file import.

    !!! note "CAA tag"
        **CAA tag** is `issue` — in registrar UIs that ask for a tag this is usually
        labelled *"Only allow specific hostnames"*. Do **not** use `issuewild`: OwnSuite
        issues per-host certificates via HTTP-01, not a wildcard certificate.

4. **Propagation gate** — polls public resolvers until a majority return your server IP,
   **before** triggering ACME (so a typo never burns Let's Encrypt's production rate
   limits).
5. **Deploy** — takes a pre-change snapshot (on a live cluster), shows the diff and asks
   to confirm, then runs one `helmfile apply` with the TLS issuer **pinned from
   `suite.yaml`**. Apps removed from `suite.yaml` are uninstalled — their data is kept.
6. **Certificates (staging → production)** — the first issuance proves HTTP-01 against
   **Let's Encrypt staging**, then promotes to **production**, waiting for each
   certificate to go Ready.
7. **Verify & report** — fetches the public host of **Keycloak always, plus each enabled
   app** (e.g. `https://auth.{domain}`, and `https://docs.{domain}` only when Docs is
   enabled), checks the served certificate is publicly trusted, rolls back a failing
   app, and prints the URLs.

## TLS modes

The `tls:` key in `suite.yaml` selects how far the certificate steps go:

| Mode | What | When |
|---|---|---|
| `prod` | staging, then production | Real install |
| `staging` | Let's Encrypt staging only (untrusted leaf) | Dry-run the ACME path |
| `selfsigned` | self-signed issuer, no DNS/ACME | CI / local, no public DNS |

## First user

```bash
suite user add alice@assoc.org        # create + show a one-time password
```

One identity reaches every enabled app on first login — see [Users](../operate/users.md).

## Where to go next

- **Add your people** — one [`suite user add`](../operate/users.md) per person.
- **Add another app** — one line under `apps:` in `suite.yaml`, then `suite apply`
  ([the app catalog](../reference/configuration.md#choosing-which-apps-to-deploy)).
- **Check on it** — [`suite status`](../operate/status.md) any time; `suite info` re-prints
  the URLs, credentials and DNS records.
- **Sleep well** — [backups & tested restore](../operate/backups.md), and
  [`suite upgrade`](../operate/upgrade.md) when version bumps arrive.

## Non-interactive (CI / scripted)

Skip `suite init` and write `suite.yaml` yourself, export the seed, then:

```bash
suite apply --yes --no-tunnel         # e.g. tls: selfsigned against a k3d cluster
```

This is exactly the path the automated test suite drives against a throwaway cluster:
`suite apply` brings the platform up — provision-less, deploy → certificates →
HTTPS-verify — provisions a user with `suite user`, then the same run exercises the full
backup → destroy → restore cycle, all self-contained, without public DNS or real
Let's Encrypt. (Each app's boot is checked separately; see
[Under the hood → Tests](../understand/platform.md#tests).)

## Real-ACME acceptance (off-CI)

CI cannot exercise Let's Encrypt (no public DNS). Validate real issuance on a server + domain:

1. Set `tls: staging` in `suite.yaml` and `suite apply` → confirm the staging certificates
   are issued (browser shows an untrusted `(STAGING) Let's Encrypt` leaf). No production
   rate limits are touched.
2. Flip to `tls: prod` and re-apply (the default ladder does staging first anyway) →
   confirm `auth.{domain}` (and `docs.{domain}` when Docs is enabled) serves a
   **publicly trusted** certificate.

## Manual fallback

`suite apply` wraps the raw helmfile flow; the hand-run dev/debug path is documented in
[Under the hood → Run it](../understand/platform.md#run-it-manual-fallback).

## Troubleshooting

- **Propagation never completes** — DNS changes can take minutes to hours; re-run
  `suite apply` once the records resolve (`dig +short '*.{domain}'`).
- **Certificate stuck not-Ready** — `kubectl -n ownsuite describe certificate keycloak-tls`;
  for HTTP-01, port 80 must reach the server and the host must resolve to it.
- **`helmfile`/`kubectl` say "cluster unreachable" or hit `localhost:8080`** — `KUBECONFIG`
  is unset or relative. `suite` commands set it for you; for ad-hoc commands
  `export KUBECONFIG="$PWD/ansible/kubeconfig"` (absolute — helmfile changes cwd).
- **SSH `Too many authentication failures`** — a multi-key agent (e.g. 1Password) is
  offering every key; pin yours with `IdentitiesOnly=yes` (see
  [Server bootstrap → Caveats](bootstrap.md#caveats)).
- **Self-signed certificates after a hand-run sync** — `suite apply` pins the issuer from
  `suite.yaml`, so this cannot happen on the operator path. It only exists on the raw
  dev path (a hand-run `helmfile sync` without `OWNSUITE_TLS_ISSUER` exported) — see
  [Under the hood → Run it](../understand/platform.md#run-it-manual-fallback).
- **Lost the seed** — there is no recovery; rotate by re-running with a new seed (this
  re-derives every credential) on a clean install.
