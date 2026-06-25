# Guided install (`suite install`)

Phase 4's deliverable: take a **bare server + a domain to all-in-HTTPS by following the
screen**. The installer ([ADR-018](../understand/decisions.md#adr-018-phase-4-guided-installer-suite-install))
wraps what used to be a manual sequence (bootstrap → config → tunnel → sync → verify)
into one idempotent command.

> **Definition of done:** from a bare server + a domain, the operator runs `make install`,
> follows the prompts and the "create these DNS records" screen, and every host serves
> HTTPS with real Let's Encrypt certificates.

## Before you start

This is **step 2**. Everything runs from **your workstation** — nothing is installed on the
Server beyond the bootstrap ([ADR-014](../understand/decisions.md#adr-014-operator-control-plane-local-workstation-ssh-tunnel)).

1. **Do [step 1 — Prepare the server](bootstrap.md) first.** It clones the repo, runs
   `make deps`, sets the inventory, and — importantly — installs your **SSH key before the
   hardening disables password login** (don't skip its warning, or you can lock yourself
   out). `make install` *can* run `make bootstrap` for you, but read that page first.
2. **Install these CLI tools** on your workstation (the installer only orchestrates them and
   adds no Python dependencies of its own):

    | Tool | Used for | Get it |
    |---|---|---|
    | `helm` + `helmfile` | deploy the stack | [helm.sh](https://helm.sh/docs/intro/install/) · [helmfile releases](https://github.com/helmfile/helmfile/releases) |
    | `kubectl` | talk to the cluster | [kubernetes.io](https://kubernetes.io/docs/tasks/tools/) |
    | `dig` | DNS propagation check | `apt install dnsutils` (Debian/Ubuntu) · `brew install bind` (macOS) |
    | `ssh`, `make`, `python3` ≥ 3.10 | tunnel, entrypoints, the installer | usually already present |

3. **A domain** whose DNS records you can edit at your registrar.

## Run it

```bash
make install              # python -m suite install
```

The installer walks these steps; each is **idempotent**, so if anything stops you, fix
it and re-run `make install` to resume:

1. **Config.** Prompts for the domain, admin email, server SSH target, object-storage mode
   and backups, and writes the non-secret values to a git-ignored `.env`.
2. **Secret seed.** Generates `OWNSUITE_SECRET_SEED` (`openssl rand -hex 24` equivalent)
   and prints it **once**.

    !!! danger "Store the seed now"
        The seed is shown once and is **never written to the repo**. Every credential
        derives from it ([ADR-012](../understand/decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)).
        Save it in your password manager. To resume later, re-export it:
        `export OWNSUITE_SECRET_SEED=...` before re-running.

3. **Bootstrap.** Runs `make bootstrap` (Ansible) to provision the server into K3s, unless
   `--skip-bootstrap`.
4. **DNS records.** Detects the server public IP over SSH and prints the exact records to
   create at your registrar:

    | Name | Type | Value | TTL |
    |---|---|---|---|
    | `*.{domain}` | A | _your server IPv4_ | 300 |
    | `{domain}` | A | _your server IPv4_ | 300 |
    | `{domain}` | CAA | `0 issue "letsencrypt.org"` | 300 |

    The wildcard `A` covers every subdomain (`auth.`, `docs.`, and future apps); `AAAA`
    rows are added when the server has public IPv6. (A wildcard *A record* is not a wildcard
    *certificate* — certificates are issued per host; see
    [ADR-019](../understand/decisions.md#adr-019-phase-4-tls-staging-first-issuance-dns-01-deferred).)

5. **Propagation gate.** Polls public resolvers until a majority return your server IP,
   **before** triggering ACME (so a typo never burns Let's Encrypt's production rate
   limits).
6. **Tunnel + sync.** Opens the SSH tunnel to the K8s API and runs `helmfile sync`.
7. **Certificates (staging → production).** Issues against **Let's Encrypt staging**
   first, then promotes to **production**, waiting for each certificate to go Ready.
8. **Verify.** Fetches `https://auth.{domain}` and `https://docs.{domain}` and checks the
   served certificate is publicly trusted.

## TLS modes

`--tls-mode` selects how far step 7 goes:

| Mode | What | When |
|---|---|---|
| `prod` (default) | staging, then production | Real install |
| `staging` | Let's Encrypt staging only (untrusted leaf) | Dry-run the ACME path |
| `selfsigned` | self-signed issuer, no DNS/ACME | CI / local, no public DNS |

## Non-interactive (CI / scripted)

```bash
python -m suite install --non-interactive --no-tunnel --skip-bootstrap \
  --skip-dns --skip-propagation --tls-mode selfsigned --domain ownsuite.localhost
```

This is exactly what `make test-install` drives against a throwaway k3d cluster
(`helmfile/tests/run-install-e2e.sh`): config → sync → certificates Ready → HTTPS →
the SSO definition of done — proving the orchestration hermetically, without public DNS
or real ACME.

## Real-ACME acceptance (off-CI)

CI cannot exercise Let's Encrypt (no public DNS). Validate real issuance on a server + domain:

1. `make install --tls-mode staging` (or run `make install` and let it do staging first)
   → confirm the staging certificates are issued (browser shows an untrusted
   `(STAGING) Let's Encrypt` leaf). No production rate limits are touched.
2. Let the installer promote to production → confirm `auth.{domain}` and `docs.{domain}`
   serve a **publicly trusted** certificate.

## Manual fallback

The installer wraps the manual flow; you can still run it by hand — see
[Shared infrastructure → Run it](../understand/platform.md#run-it-manual-fallback).

## Troubleshooting

- **Propagation never completes** — DNS changes can take minutes to hours; re-run
  `make install` once the records resolve (`dig +short '*.{domain}'`).
- **Certificate stuck not-Ready** — `kubectl -n ownsuite describe certificate keycloak-tls`;
  for HTTP-01, port 80 must reach the server and the host must resolve to it.
- **Lost the seed** — there is no recovery; rotate by re-running with a new seed (this
  re-derives every credential) on a clean install.
