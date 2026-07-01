# Meet application

An **advanced** optional app beyond the core (Docs + Drive). **Meet**
([suitenumerique/meet](https://github.com/suitenumerique/meet) — video conferencing
powered by [LiveKit](https://github.com/livekit/livekit)) is wired to the same shared
foundation, with Keycloak SSO so a user provisioned once reaches it on first login
(JIT — no per-app step).

!!! note "Off by default"
    Meet ships **disabled** (`OWNSUITE_APP_MEET`, default `false`). It is the only app
    that needs **non-HTTP ports** open on the server, so enabling it is a two-part
    switch: the app flag **and** the `enable_meet` firewall flag (below).

Like Docs/Drive, Meet is an official `suitenumerique` app with a published Helm chart,
so OwnSuite consumes it as an **upstream chart** (no local `charts/meet`). It comes as
**three releases**, all gated on `apps.meet.enabled`:

| Release | Chart | What it is |
|---|---|---|
| `meet` | `suitenumerique-meet/meet` | Django backend + React frontend + a Celery worker |
| `livekit` | `livekit/livekit-server` | The WebRTC media server (SFU) |
| `livekit-egress` | `livekit/egress` | Records rooms to S3 (headless Chrome) |

The `meet` release depends, via `needs:`, on a subset of the shared infrastructure:

| Needs | For |
|---|---|
| `platform-configuration` | Derived secrets (`meet-secrets`, `meet-db`) + the `meet` OIDC client in the realm |
| `postgres` | The dedicated `meet` database (rooms/participants/recording metadata) |
| `valkey` | Cache + Celery broker (DBs 6/7) |
| `keycloak` | SSO — the `meet` OIDC client |
| `livekit` | The media server the backend mints room tokens for |
| `issuers` | The `meet-tls` certificate (cert-manager) |

## Networking — the only app with non-HTTP ports

Everything else in OwnSuite is HTTP/HTTPS behind Traefik. Real-time media can't be: it
is UDP (with a TCP fallback). LiveKit is configured for the **smallest possible
footprint** on a single node:

- **One muxed UDP port `7882`** for all WebRTC media, plus **one TCP port `7881`** as a
  fallback for clients on UDP-hostile networks. No 10 000-port range, no dedicated TURN.
- LiveKit runs with **`hostNetwork`** and binds those ports directly on the node
  (`use_external_ip: true` so it advertises the server's public IP to clients).
- **Signaling** (the `wss://livekit.{domain}` WebSocket) is a normal Traefik ingress on
  443 — only the media ports are special.

These ports are opened with the **`enable_meet`** flag, mirroring the mailbox's port-25
seam ([ADR-027](decisions.md#adr-027-non-http-ingress-inbound-smtp-on-port-25-via-k3s-servicelb))
extended to UDP ([ADR-039](decisions.md#adr-039-meet-media-ports-single-udp-mux-tcp-fallback)):

- **Terraform** (cloud security group): `enable_meet = true` in your
  `terraform.tfvars` opens `7881/tcp` + `7882/udp` to the world.
- **Ansible** (host UFW): `enable_meet: true` in `group_vars/all.yml` adds the matching
  UFW rules.

Leave both `false` unless you deploy Meet.

## How it is wired

- **OIDC like Docs.** The `meet` backend is a Django/mozilla-django-oidc app, so it uses
  the same external/internal endpoint split — the browser hits Keycloak at
  `https://auth.{domain}`, the backend reaches it in-cluster over plain HTTP. The `meet`
  confidential client (secret derived from the seed id `meet-oidc`) reuses the shared
  client template verbatim; its `redirectUris: https://meet.{domain}/*` already covers
  the `/api/v1.0/callback/` redirect.
- **One shared LiveKit credential.** The API key/secret the backend, the LiveKit server
  and the egress recorder all authenticate with is seed-derived
  (`meet-livekit-key` / `meet-livekit-secret`) in `platform-configuration`. LiveKit and
  egress take it **inline** (their upstream charts render config into a ConfigMap and
  support no `secretKeyRef`), re-derived from the same seed ids so the three always
  agree ([ADR-012](decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)).
- **Recording to S3.** Egress writes room recordings to the **`meet-recordings`** bucket
  (its own bucket on the shared S3 seam — Garage in garage mode, external S3 otherwise).
  It shares LiveKit's Redis DB (Valkey DB 8) to receive recording jobs.

## What is disabled

Meet's upstream chart also ships AI/analytics components that are **out of scope** for a
single association VPS — they need GPU/Whisper/LLM endpoints. OwnSuite scales them to
**zero replicas**: the summary microservice, the transcription/summarize Celery queues,
and the LiveKit agents (metadata + subtitles). PostHog analytics and telephony (SIP) are
off too. Core video calls + recording are the shipped feature set.

## Enabling Meet

```bash
# 1. Open the media ports (pick your provider), then re-apply:
#    terraform.tfvars:  enable_meet = true
#    ansible group_vars/all.yml:  enable_meet: true
# 2. Turn the app on and sync:
export OWNSUITE_APP_MEET=true
make sync
```

In `garage` object-storage mode the `meet-recordings` bucket is created automatically;
on external S3, pre-create it (and, if your provider needs it, a CORS rule for
`https://*.{domain}`).

## Sizing

LiveKit and (during a recording) the headless-Chrome egress are the heavy parts — see
[Sizing](../operate/sizing.md). Media scales with concurrent participants and bandwidth;
plan Meet for **modest concurrency** on a single small server, and add capacity before
inviting large meetings.

## Known limitations

- **Recording download proxy deferred.** Recordings land in S3, but the authenticated
  `/media/` download path uses an nginx `auth_request` contract Traefik can't satisfy
  (the same limitation Docs solves with a media-proxy). A Traefik media-proxy for
  recording downloads is a follow-up.
- **No dedicated TURN.** UDP + TCP fallback covers association-scale networks; a client
  behind a firewall blocking both won't connect until embedded TURN/TLS is added.
