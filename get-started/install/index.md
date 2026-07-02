# Guided install (`suite install`)

Take a **bare server + a domain to all-in-HTTPS by following the screen**. The installer rolls the whole sequence (set up → configure → deploy → get certificates → check) into one command you can safely re-run.

> **What you get:** from a bare server + a domain, you run `make install`, follow the prompts and the "create these DNS records" screen, and every app ends up served over HTTPS with real Let's Encrypt certificates.

## Before you start

This is **step 2**. Everything runs from **your own computer** — nothing extra is installed on the server beyond the initial setup.

1. **Do [step 1 — Prepare the server](https://corentingiraud.github.io/ownsuite/get-started/bootstrap/index.md) first.** It clones the repo, runs `suite deps`, sets the inventory, and — importantly — installs your **SSH key before the hardening disables password login** (don't skip its warning, or you can lock yourself out). `suite install` *can* run the bootstrap for you, but read that page first.

1. **Install these CLI tools** on your workstation (the installer orchestrates them; its one Python dependency, `questionary` for the interactive prompts, is installed by `suite deps`):

   | Tool                            | Used for                           | Get it                                                                                                              |
   | ------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
   | `helm` + `helmfile`             | deploy the stack                   | [helm.sh](https://helm.sh/docs/intro/install/) · [helmfile releases](https://github.com/helmfile/helmfile/releases) |
   | `kubectl`                       | talk to the cluster                | [kubernetes.io](https://kubernetes.io/docs/tasks/tools/)                                                            |
   | `dig`                           | DNS propagation check              | `apt install dnsutils` (Debian/Ubuntu) · `brew install bind` (macOS)                                                |
   | `ssh`, `make`, `python3` ≥ 3.10 | tunnel, entrypoints, the installer | usually already present                                                                                             |

1. **A domain** whose DNS records you can edit at your registrar.

## Run it

```
make install              # python -m suite install
```

The installer walks these steps; each is **idempotent**, so if anything stops you, fix it and re-run `make install` to resume:

1. **Provision (optional).** If no server is configured yet (`OWNSUITE_SERVER_SSH` unset), the installer offers to run `suite provision` first — the Terraform step that creates the server and object storage. Decline it if you already have a server. See [Provision the server](https://corentingiraud.github.io/ownsuite/get-started/provision/index.md).

1. **Config.** Interactive prompts collect the domain, admin email, server SSH target, object-storage mode (arrow-key select), backups (yes/no), and **which apps to enable** (a checkbox — every app is off by default), and writes the non-secret values to a git-ignored `.env`. Every prompt — and many more optional knobs — maps to an `OWNSUITE_*` variable; the full list is the [Configuration reference](https://corentingiraud.github.io/ownsuite/reference/configuration/index.md).

1. **Secret seed.** Generates `OWNSUITE_SECRET_SEED` (`openssl rand -hex 24` equivalent) and prints it **once**.

   Store the seed now

   The seed is shown once and is **never written to the repo**. Every password and key is derived from it. Save it in your password manager. To resume later, re-export it: `export OWNSUITE_SECRET_SEED=...` before re-running.

1. **Bootstrap.** Runs the Ansible bootstrap (same as `suite bootstrap`) to provision the server into K3s, unless `--skip-bootstrap`.

1. **DNS records.** Detects the server public IP over SSH and prints the exact records to create at your registrar:

   | Name         | Type  | Value                       | TTL |
   | ------------ | ----- | --------------------------- | --- |
   | `{domain}`   | A     | *your server IPv4*          | 300 |
   | `*.{domain}` | CNAME | `{domain}.`                 | 300 |
   | `{domain}`   | CAA   | `0 issue "letsencrypt.org"` | 300 |

   The apex holds the address once; the wildcard **CNAME → apex** covers every subdomain (`auth.`, `docs.`, and future apps), so if the IP changes you edit a single record. An `AAAA` row is added at the apex when the server has public IPv6 (the CNAME follows it — no second wildcard needed). A wildcard record is not a wildcard *certificate* — certificates are still issued per host.

   The installer also writes a **BIND zone file** (`./{domain}.zone`) with these records (`$ORIGIN`/`$TTL` + records, no SOA/NS) so you can import them in one step if your registrar supports zone-file import.

   CAA tag

   **CAA tag** is `issue` — in registrar UIs that ask for a tag this is usually labelled *"Only allow specific hostnames"*. Do **not** use `issuewild`: OwnSuite issues per-host certificates via HTTP-01, not a wildcard certificate.

1. **Propagation gate.** Polls public resolvers until a majority return your server IP, **before** triggering ACME (so a typo never burns Let's Encrypt's production rate limits).

1. **Tunnel + sync.** Opens the SSH tunnel to the K8s API and runs `helmfile sync`.

1. **Certificates (staging → production).** Issues against **Let's Encrypt staging** first, then promotes to **production**, waiting for each certificate to go Ready.

1. **Verify.** Fetches the public host of **Keycloak always, plus each enabled app** (e.g. `https://auth.{domain}`, and `https://docs.{domain}` only when Docs is enabled) and checks the served certificate is publicly trusted.

## TLS modes

`--tls-mode` selects how far step 7 goes:

| Mode             | What                                        | When                      |
| ---------------- | ------------------------------------------- | ------------------------- |
| `prod` (default) | staging, then production                    | Real install              |
| `staging`        | Let's Encrypt staging only (untrusted leaf) | Dry-run the ACME path     |
| `selfsigned`     | self-signed issuer, no DNS/ACME             | CI / local, no public DNS |

## Non-interactive (CI / scripted)

```
python -m suite install --non-interactive --no-tunnel --skip-bootstrap \
  --skip-dns --skip-propagation --tls-mode selfsigned --domain ownsuite.localhost
```

This is exactly the path the automated test suite drives against a throwaway cluster: the installer brings the platform up — configure → deploy → certificates → HTTPS-verify — provisions a user with `suite user`, then the same run exercises the full backup → destroy → restore cycle, all self-contained, without public DNS or real Let's Encrypt. (Each app's boot is checked separately; see [Under the hood → Tests](https://corentingiraud.github.io/ownsuite/understand/platform/#tests).)

## Real-ACME acceptance (off-CI)

CI cannot exercise Let's Encrypt (no public DNS). Validate real issuance on a server + domain:

1. `python -m suite install --tls-mode staging` (or run `make install`, whose default `prod` mode does staging first) → confirm the staging certificates are issued (browser shows an untrusted `(STAGING) Let's Encrypt` leaf). No production rate limits are touched.
1. Let the installer promote to production → confirm `auth.{domain}` (and `docs.{domain}` when Docs is enabled) serves a **publicly trusted** certificate.

## Manual fallback

The installer wraps the manual flow; you can still run it by hand — see [Shared infrastructure → Run it](https://corentingiraud.github.io/ownsuite/understand/platform/#run-it-manual-fallback).

## Troubleshooting

- **Propagation never completes** — DNS changes can take minutes to hours; re-run `make install` once the records resolve (`dig +short '*.{domain}'`).
- **Certificate stuck not-Ready** — `kubectl -n ownsuite describe certificate keycloak-tls`; for HTTP-01, port 80 must reach the server and the host must resolve to it.
- **`helmfile`/`kubectl` say "cluster unreachable" or hit `localhost:8080`** — `KUBECONFIG` is unset or relative. `suite`/`make` set it for you; for ad-hoc commands `export KUBECONFIG="$PWD/ansible/kubeconfig"` (absolute — helmfile changes cwd).
- **SSH `Too many authentication failures`** — a multi-key agent (e.g. 1Password) is offering every key; pin yours with `IdentitiesOnly=yes` (see [Server bootstrap → Caveats](https://corentingiraud.github.io/ownsuite/get-started/bootstrap/#caveats)).
- **Manual `make sync` served self-signed certs** — you forgot `export OWNSUITE_TLS_ISSUER=letsencrypt-http01` before the sync (see [Configuration → TLS](https://corentingiraud.github.io/ownsuite/reference/configuration/#tls-certificates)).
- **Lost the seed** — there is no recovery; rotate by re-running with a new seed (this re-derives every credential) on a clean install.
