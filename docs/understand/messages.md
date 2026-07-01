# Mailbox application

The **optional, advanced** add-on: a mailbox (off by default).
**[suitenumerique/messages](https://github.com/suitenumerique/messages)** is La Suite's own mail
app — a full provider with its own Postfix MTA, a Django MDA that stores and indexes mail, and an
**integrated webmail**. It is federated to the same Keycloak, so a user provisioned once reaches it
on first login (JIT — no per-app step). **There is no IMAP/POP3 by design**: users read mail in the
messages web UI, not Thunderbird/Apple Mail.

!!! warning "Off by default — the hardest part to run"
    The mailbox ships **disabled** (`OWNSUITE_APP_MESSAGES`, default `false`). Mail is the hardest
    thing to run reliably on a server, so it is kept isolated and affects nothing else when off.
    It also needs an **external SMTP relay account** and **DNS + rDNS** you control — don't enable
    it unless you're ready for that.

Unlike Grist/Projects, messages **is** a `suitenumerique` Django sibling of Docs, so it reuses the
existing seam rather than a foreign one. Upstream ships container images
(`ghcr.io/suitenumerique/messages-{backend,frontend,mta-in,mta-out}`, pinned in
`versions.yaml`) but **no** Helm chart, so OwnSuite ships a thin local chart
(`helmfile/charts/messages`). It is gated on `apps.messages.enabled` and depends, via `needs:`, on:

| Needs | For |
|---|---|
| `platform-configuration` | Derived secrets (`messages-secrets`, `messages-db`) + the `messages` OIDC client in the realm |
| `postgres` | The dedicated `messages` database (mailboxes, threads, contacts) |
| `valkey` | Cache + Celery broker (Redis DBs **4**/**5**, distinct from Docs 0/1 and Drive 2/3) |
| `garage` | The per-app S3 bucket for mail blobs/attachments (pluggable seam) |
| `keycloak` | SSO — the `messages` OIDC client |
| `issuers` | The `messages-tls` certificate (cert-manager) for the webmail |

## How it is wired

- **OIDC by the external/internal split, like Docs.** messages is `mozilla-django-oidc`, so it takes
  per-endpoint `OIDC_OP_{AUTHORIZATION,TOKEN,USER,JWKS}_ENDPOINT` + `OIDC_RP_CLIENT_{ID,SECRET}`
  (not Grist/Projects single-issuer discovery): browser-facing endpoints at the public
  `auth.{domain}`, token/userinfo/jwks hairpinned to the in-cluster Keycloak service.
  The `messages` OIDC client is one more `keycloak.clients` entry; the realm-import + upsert Job need
  no template change.
- **Inbound on port 25, outbound relayed.** The Postfix **MTA-in** receives mail from the internet on
  **port 25**, exposed by a `LoadBalancer` Service that K3s' ServiceLB binds to the host port
. The
  **MTA-out** **never** sends directly from the VPS IP: `MTA_OUT_MODE=relay`,
  `MTA_OUT_SMTP_TLS_SECURITY_LEVEL=secure` to a reputable relay — Scaleway TEM by default (see
  [Outbound](#outbound-scaleway-tem-or-an-external-relay)). `THROTTLE_*_OUTBOUND_EXTERNAL_RECIPIENTS`
  are set below the relay's cap so it fails gracefully in-app.

## Outbound: Scaleway TEM or an external relay { #outbound-scaleway-tem-or-an-external-relay }

The MTA-out relays through an authenticated SMTP relay; you own the easy half (receiving) and rent
the hard half (deliverability). On the recommended Scaleway host, that relay is **Transactional
Email (TEM)**, provisioned by Terraform (`enable_mailbox = true`):

| `OWNSUITE_MTA_*` | Value |
|---|---|
| `RELAY_HOST` | `smtp.tem.scaleway.com:2587` |
| `RELAY_USERNAME` | your Scaleway **Project ID** (`terraform output mta_relay_username`) |
| `RELAY_PASSWORD` | the workload IAM key secret, carrying `TransactionalEmailFullAccess` (`= s3_secret_key`) |
| `SPF_INCLUDE` | `_spf.tem.scaleway.com` |

!!! warning "Use port 2587, not 587"
    **Scaleway Instances block outbound SMTP (25/465/587) by default** as an anti-spam measure. TEM
    exposes alternate ports **2587 (STARTTLS)** and **2465 (TLS)** for exactly this — the standard
    ports will time out from the server. TEM also needs **its own DNS records published** (SPF, DKIM,
    DMARC from `terraform output tem_dns`) before Scaleway validates the domain and outbound works,
    on top of OwnSuite's own DKIM below.

Any reputable EU SMTP relay works as an alternative (e.g. Infomaniak `mail.infomaniak.com:587`,
`SPF_INCLUDE=spf.infomaniak.ch`, cap 1440 msg/24h) — set the same three `RELAY_*` variables. See
[Configuration → Mailbox](../reference/configuration.md#mailbox-messages).
- **Reuse, per-app instances.** A dedicated CNPG `messages` database; the shared Valkey on DBs 4/5;
  a per-app S3 bucket for mail blobs. The Django `SECRET_KEY`, OIDC client secret and the internal
  `MDA_API_SECRET` (MTA↔MDA) are seed-derived
; the
  **relay credentials and the DKIM private key are external overrides**, captured by the installer
  and never committed.
- **OpenSearch deferred.** Full-text mail search (its heaviest dependency, ~1–2 GB RAM) is optional
  upstream and omitted in v1 to protect the single-VPS budget; mail still delivers and reads. It
  returns behind its own flag later.

## Provisioning

A maildomain with `oidc_autojoin=True` auto-creates a user's mailbox on **first OIDC login** — the
same JIT model the `suite` CLI already relies on, so **`suite user add` needs no mailbox-specific
step**. The one new piece is a one-time **maildomain seed Job** (mirrors `keycloak-config`) that
creates the domain, enables autojoin, and registers the supplied DKIM key.

## DNS (a manual step, like the rest of the DNS flow)

With the mailbox enabled, `suite install` prints the mail records to add at your registrar, on top
of the existing A/AAAA/CAA:

- **MX** → the server, so mail for `@{domain}` is delivered to your MTA-in.
- **SPF** (TXT) — must `include:` the relay so relayed mail is authorized.
- **DKIM** (TXT) — the public half of the installer-generated signing key.
- **DMARC** (TXT) — alignment policy.
- **rDNS / PTR** — set at the **provider/host** level (it cannot be set in-cluster); documented as a
  manual step. Confirm your provider also permits **inbound** port 25.

## Run it

```bash
set -a && source .env && set +a            # OWNSUITE_SECRET_SEED, OWNSUITE_DOMAIN, ...
export OWNSUITE_APP_MESSAGES=true           # opt in (off by default)
# External relay account + DKIM key — held in the env, never written to .env (like the
# seed). The installer generates the DKIM key the first time and prints it to re-export.
export OWNSUITE_MTA_RELAY_USERNAME=...      # Scaleway TEM (Project ID) or an EU relay account
export OWNSUITE_MTA_RELAY_PASSWORD=...      # TEM: the IAM key secret (= s3_secret_key)
export OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64=... # printed by `suite install` on first run
make tunnel                                 # in another terminal
make sync                                   # brings up the infra + enabled apps + messages
```

`suite install` does this for you: with the mailbox enabled it generates the DKIM key, prints
the MX/SPF/DKIM/DMARC records plus the rDNS/port-25 manual steps, then waits for propagation
before issuing certificates. Without the relay account exported, mta-out comes up **without** an
external relay (the hermetic path — local delivery only); set it to send to the internet. When it
finishes, the webmail answers at `https://messages.{domain}`; log in with a Keycloak user (e.g.
one created by `suite user add`), then send a test message to an external inbox.

## Tests

messages is **template/lint-validated** (`make lint-helm`: `helm lint` the chart standalone +
kubeconform the rendered manifests, in both relay states), and the installer's DNS/DKIM logic is
unit-tested (`tests/test_dns.py`, `tests/test_mail.py`). On top of that, the **hermetic mail
loopback runs nightly** on its own throwaway cluster — kept separate from Docs and Drive because
five pods would push the shared runner over its memory ceiling. Run it yourself with
`make test-app APP=messages`.

- **Hermetic loopback** (nightly): the five components converge, the webmail answers, and a message
  delivered to a local mailbox reads back via the API. The test injects a message over SMTP to the
  inbound MTA and confirms it lands in the recipient's mailbox — the real inbound path
  (MTA → delivery agent → mailbox), with no relay account, so nothing leaves the cluster.
- **Real external deliverability** (a human, on a real domain + relay account): publish the records,
  `suite user add`, send to an external inbox, and confirm it lands **not in spam** with SPF/DKIM/DMARC
  aligned. The `dns_check` management command verifies record alignment. This is the one check a
  CI cluster cannot stand in for — it needs a real domain, a real relay, and a real external inbox.

## Limits

- **No IMAP/POP3** — the web UI is the only client.
- **No full-text search** until OpenSearch is re-enabled.
- **No bulk/newsletter sending** — the relay is rate-capped; that is a separate product.
