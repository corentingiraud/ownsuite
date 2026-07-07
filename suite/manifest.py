"""The single per-app manifest (ADR-042, issue #82).

One record per app drives everything app-shaped in the CLI: the `suite.yaml`
schema (which apps + which options are valid), the init checkbox, the apps
catalog, health checks, upgrade/apply rollback groups, prune sets, and the
terraform/ansible firewall flags. Before this file an app was declared in ~7
parallel places that drifted (upgrade's rollback map was missing meet/tchap).

The helmfile stays the runtime truth for *what* each release deploys; this
manifest must mirror its release groups exactly — `tests/test_manifest.py`
regex-parses `helmfile.yaml.gotmpl` and fails on any drift, both directions.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class App:
    name: str                       # yaml key under `apps:`, subdomain, condition key
    label: str                      # human line for `suite init` / `suite apps`
    releases: tuple[str, ...]       # helm releases, helmfile order
    # Per-app knobs: suite.yaml key -> (env var the helmfile reads, code default).
    options: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Terraform/ansible firewall flags this app needs (cloud SG + host ufw).
    tf_flags: tuple[str, ...] = ()

    @property
    def env_key(self) -> str:
        return f"OWNSUITE_APP_{self.name.upper()}"

    @property
    def host(self) -> str:
        return self.name  # every app answers at https://<name>.<domain>/


APPS: dict[str, App] = {
    a.name: a
    for a in (
        App(
            "docs", "Docs (collaborative documents)",
            ("docs-ingress", "docs", "docs-media-proxy"),
            options={"s3_bucket": ("OWNSUITE_S3_BUCKET", "docs-media-storage")},
        ),
        App(
            "drive", "Drive (file storage)",
            ("drive-ingress", "drive", "drive-media-proxy"),
            options={"s3_bucket": ("OWNSUITE_DRIVE_S3_BUCKET", "drive-media-storage")},
        ),
        App(
            "grist", "Grist (spreadsheets/tables)",
            ("grist",),
            options={
                "storage": ("OWNSUITE_GRIST_STORAGE", "5Gi"),
                "org": ("OWNSUITE_GRIST_ORG", "ownsuite"),
                "sandbox": ("OWNSUITE_GRIST_SANDBOX", "unsandboxed"),
            },
        ),
        App(
            "projects", "Projects (kanban)",
            ("projects",),
            options={"s3_bucket": ("OWNSUITE_PROJECTS_S3_BUCKET", "projects-media-storage")},
        ),
        App(
            "messages", "Mailbox (email — needs extra DNS/relay setup)",
            ("messages",),
            options={
                "s3_bucket": ("OWNSUITE_MESSAGES_S3_BUCKET", "messages-media-storage"),
                "relay_host": ("OWNSUITE_MTA_RELAY_HOST", "mail.infomaniak.com:587"),
                "spf_include": ("OWNSUITE_MTA_SPF_INCLUDE", "spf.infomaniak.ch"),
                "dkim_selector": ("OWNSUITE_MTA_DKIM_SELECTOR", "ownsuite"),
                "dmarc_rua": ("OWNSUITE_MTA_DMARC_RUA", ""),
            },
            tf_flags=("enable_mailbox",),  # inbound SMTP port 25 (ADR-027)
        ),
        App(
            "meet", "Meet (video conferencing)",
            ("meet", "meet-media-proxy", "livekit", "livekit-egress"),
            options={
                "s3_bucket": ("OWNSUITE_MEET_S3_BUCKET", "meet-recordings"),
                "turn": ("OWNSUITE_MEET_TURN", "false"),
            },
            # LiveKit media ports 7881/tcp + 7882/udp; TURN 5349/tcp when turn: true
            # (ADR-039). `enable_meet_turn` is derived from the `turn` option.
            tf_flags=("enable_meet", "enable_meet_turn"),
        ),
        App(
            "tchap", "Tchap (Matrix/Element chat — text-only, SSO via Keycloak)",
            ("tchap",),
            options={"s3_bucket": ("OWNSUITE_TCHAP_S3_BUCKET", "tchap-media")},
        ),
    )
}

# Release -> owning app (app releases only; platform releases are absent).
RELEASE_TO_APP: dict[str, str] = {r: a.name for a in APPS.values() for r in a.releases}

# Health-check host -> releases to roll back when it fails. Keycloak answers at
# `auth` and underpins every app's SSO, so it is always checked alongside apps.
HOST_RELEASES: dict[str, tuple[str, ...]] = {
    **{a.host: a.releases for a in APPS.values()},
    "auth": ("keycloak",),
}
