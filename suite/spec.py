"""`suite.yaml` — the single human-owned description of the suite (ADR-042).

One file says what the deployment should be (provider, domain, TLS, apps + their
options); `suite apply` reconciles reality to it. Presence of an app under `apps:`
is the ONLY enable switch — the OWNSUITE_APP_* env toggles are derived from it,
never read. Everything else the helmfile reads stays an env var at subprocess
time, assembled here with one precedence rule:

    ambient os.environ  >  suite.yaml  >  machine state  >  helmfile defaults

(ambient wins so CI/debug overrides keep working; values omitted from suite.yaml
fall through to the helmfile's own documented defaults). Secrets never live here:
the seed stays exported-only (ADR-012), provider-minted credentials live in the
machine state (`suite/state.py`).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import manifest, state
from .errors import SuiteError

PROVIDERS = ("scaleway", "infomaniak")
TLS_MODES = ("selfsigned", "staging", "prod")
# suite.yaml speaks admin ("prod"); the helmfile speaks cert-manager issuer names.
ISSUER_BY_TLS = {
    "selfsigned": "selfsigned",
    "staging": "letsencrypt-staging",
    "prod": "letsencrypt-http01",
}

TOP_KEYS = {"provider", "domain", "admin_email", "tls", "server",
            "object_storage", "backup", "postgres", "apps"}
# (section, key) -> env var the helmfile reads. Emitted only when set in suite.yaml.
SECTION_VARS = {
    ("object_storage", "mode"): "OWNSUITE_OBJECT_STORAGE_MODE",
    ("object_storage", "endpoint"): "OWNSUITE_S3_ENDPOINT",
    ("object_storage", "region"): "OWNSUITE_S3_REGION",
    ("backup", "enabled"): "OWNSUITE_BACKUP_ENABLED",
    ("backup", "schedule"): "OWNSUITE_BACKUP_SCHEDULE",
    ("backup", "retention"): "OWNSUITE_BACKUP_RETENTION",
    ("backup", "target"): "OWNSUITE_BACKUP_S3_TARGET",
    ("backup", "endpoint"): "OWNSUITE_BACKUP_S3_ENDPOINT",
    ("backup", "region"): "OWNSUITE_BACKUP_S3_REGION",
    ("backup", "bucket"): "OWNSUITE_BACKUP_S3_BUCKET",
    ("postgres", "storage"): "OWNSUITE_PG_STORAGE",
}
# Section keys that are valid in suite.yaml but not helmfile env vars (so absent
# from SECTION_VARS). `backup.provision` is a Terraform-only toggle (see tfvars_for).
NON_ENV_KEYS = {"backup": {"provision"}}
CHOICES = {
    ("tls",): TLS_MODES,
    ("provider",): PROVIDERS,
    ("object_storage", "mode"): ("external", "garage"),
    ("backup", "target"): ("external", "in-cluster"),
}


def config_path() -> Path:
    """Override via OWNSUITE_CONFIG so e2e/tests never touch a real suite.yaml."""
    return Path(os.environ.get("OWNSUITE_CONFIG", "suite.yaml"))


def _env_str(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass(frozen=True)
class Spec:
    data: dict
    path: Path

    @property
    def domain(self) -> str:
        return self.data["domain"]

    @property
    def admin_email(self) -> str:
        return self.data.get("admin_email") or f"admin@{self.domain}"

    @property
    def tls(self) -> str:
        return self.data["tls"]

    @property
    def provider(self) -> str | None:
        return self.data.get("provider")

    @property
    def ssh(self) -> str:
        return (self.data.get("server") or {}).get("ssh") or ""

    def enabled_apps(self) -> list[str]:
        """Manifest order — deterministic regardless of suite.yaml ordering."""
        present = self.data.get("apps") or {}
        return [name for name in manifest.APPS if name in present]

    def app_options(self, name) -> dict:
        return (self.data.get("apps") or {}).get(name) or {}

    def section(self, name) -> dict:
        return self.data.get(name) or {}


@dataclass(frozen=True)
class Context:
    """Shared verb prologue: everything a command needs to act on the suite."""
    spec: Spec
    state: dict
    env: dict      # pass to process.run(env=...) for helmfile/kubectl/helm
    view: dict     # the effective OWNSUITE_* a subprocess will see (for decisions)
    ssh: str


def load(path=None) -> Spec:
    p = Path(path) if path else config_path()
    if not p.exists():
        raise SuiteError(
            f"{p} not found — run `suite init` to create it "
            "(or copy suite.yaml.example)."
        )
    try:
        import yaml  # lazy: `suite deps` installs it (requirements.txt)
    except ImportError as exc:
        raise SuiteError(
            "PyYAML is required — run `suite deps` (or `pip install PyYAML`)."
        ) from exc
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:
        raise SuiteError(f"{p}: invalid YAML — {exc}") from exc
    _validate(data, p)
    return Spec(data, p)


def load_context() -> Context:
    spec = load()
    st = state.load()
    env = assemble_env(spec, st)
    view = {k: v for k, v in {**os.environ, **env}.items() if k.startswith("OWNSUITE_")}
    return Context(spec, st, env, view, spec.ssh or st.get("ssh", ""))


def _validate(data, p):
    def bad(msg):
        raise SuiteError(f"{p}: {msg}")

    if not isinstance(data, dict):
        bad("top level must be a mapping (see suite.yaml.example)")
    unknown = set(data) - TOP_KEYS
    if unknown:
        bad(f"unknown key(s): {', '.join(sorted(unknown))} "
            f"(valid: {', '.join(sorted(TOP_KEYS))})")
    if not data.get("domain"):
        bad("`domain` is required")
    if data.get("tls") not in TLS_MODES:
        bad(f"`tls` must be one of {', '.join(TLS_MODES)} (got {data.get('tls')!r})")

    server = data.get("server") or {}
    if not isinstance(server, dict) or set(server) - {"ssh"}:
        bad("`server` supports only `ssh: user@host`")

    for section in ("object_storage", "backup", "postgres"):
        sec = data.get(section)
        if sec is None:
            continue
        if not isinstance(sec, dict):
            bad(f"`{section}` must be a mapping")
        valid = {key for (s, key) in SECTION_VARS if s == section}
        valid |= NON_ENV_KEYS.get(section, set())
        unknown = set(sec) - valid
        if unknown:
            bad(f"{section}: unknown key(s) {', '.join(sorted(unknown))} "
                f"(valid: {', '.join(sorted(valid))})")

    for path_, choices in CHOICES.items():
        node = data
        for part in path_:
            node = (node or {}).get(part) if isinstance(node, dict) else None
        if node is not None and node not in choices:
            bad(f"{'.'.join(path_)} must be one of {', '.join(choices)} (got {node!r})")

    apps = data.get("apps")
    if apps is None:
        apps = {}
    if not isinstance(apps, dict):
        bad("`apps` must be a mapping of app name -> options (`docs: {}` enables docs)")
    for name, opts in apps.items():
        if name not in manifest.APPS:
            bad(f"unknown app '{name}' (available: {', '.join(manifest.APPS)})")
        if opts is None:
            continue
        if not isinstance(opts, dict):
            bad(f"apps.{name} must be a mapping (use `{name}: {{}}`)")
        valid = set(manifest.APPS[name].options)
        unknown = set(opts) - valid
        if unknown:
            bad(f"apps.{name}: unknown option(s) {', '.join(sorted(unknown))} "
                f"(valid: {', '.join(sorted(valid)) or 'none'})")


def assemble_env(spec: Spec, st: dict) -> dict:
    """Env to pass helmfile/kubectl subprocesses (process.run merges it OVER
    os.environ). Ambient env wins for every derived key EXCEPT the app toggles,
    which always come from suite.yaml — the single source of the app set."""
    merged = {**st.get("env", {}), **_derived(spec)}
    env = {k: v for k, v in merged.items() if k not in os.environ}
    enabled = set(spec.enabled_apps())
    for app in manifest.APPS.values():
        env[app.env_key] = "true" if app.name in enabled else "false"
    return env


def _derived(spec: Spec) -> dict:
    d = {
        "OWNSUITE_DOMAIN": spec.domain,
        "OWNSUITE_ADMIN_EMAIL": spec.admin_email,
        "OWNSUITE_ACME_EMAIL": spec.admin_email,
    }
    for (section, key), var in SECTION_VARS.items():
        val = spec.section(section).get(key)
        if val is not None:
            d[var] = _env_str(val)
    for name in spec.enabled_apps():
        for key, (var, _default) in manifest.APPS[name].options.items():
            val = spec.app_options(name).get(key)
            if val is not None:
                d[var] = _env_str(val)
    return d


def tfvars_for(spec: Spec) -> dict:
    """Terraform inputs derived from suite.yaml (written to suite.auto.tfvars):
    the app set drives the firewall flags and the bucket list, so enabling Meet
    or the Mailbox opens its ports without hand-editing tfvars. Provider params
    (project ids, ssh key) stay in terraform.tfvars."""
    apps = spec.enabled_apps()
    external_storage = spec.section("object_storage").get("mode", "external") != "garage"
    buckets = []
    if external_storage:
        for name in apps:
            opt = manifest.APPS[name].options.get("s3_bucket")
            if opt:
                buckets.append(_env_str(spec.app_options(name).get("s3_bucket", opt[1])))
    backup = spec.section("backup")
    # A backup bucket is provisioned only when off-site backups are on, external,
    # and `backup.provision` is true. Provisioning is decoupled from endpoint
    # presence (issue #86): endpoint/region say *where* the store lives regardless
    # of who owns it. `provision` defaults to whether a provider is set (a provider
    # can mint the bucket); `provision: false` is the BYO/real-DR path (ADR-006).
    provision = _env_str(backup.get("provision", spec.provider is not None)) == "true"
    provision_backup = (
        _env_str(backup.get("enabled", False)) == "true"
        and backup.get("target") == "external"
        and provision
    )
    turn = _env_str(spec.app_options("meet").get("turn", False)) == "true"
    return {
        "domain": spec.domain,
        "enable_mailbox": "messages" in apps,
        "enable_meet": "meet" in apps,
        "enable_meet_turn": "meet" in apps and turn,
        "bucket_names": buckets,
        "backup_bucket_name": _env_str(backup.get("bucket", "ownsuite-backups"))
        if provision_backup else "",
    }


def infra_flags(spec: Spec) -> dict:
    """The firewall booleans shared by Terraform (cloud SG) and Ansible (host ufw)."""
    tf = tfvars_for(spec)
    return {k: tf[k] for k in ("enable_mailbox", "enable_meet", "enable_meet_turn")}


# --- suite init -------------------------------------------------------------------

def run_init(args):
    p = config_path()
    if p.exists():
        raise SuiteError(f"{p} already exists — edit it and run `suite apply`.")
    if not sys.stdin.isatty():
        raise SuiteError(
            "suite init is interactive — in CI, write suite.yaml directly "
            "(see suite.yaml.example)."
        )
    from . import prompt

    domain = prompt.text("Base domain (e.g. assoc.example.org)",
                         validate=lambda t: bool(t.strip()) or "This value is required.")
    admin_email = prompt.text("Admin email", default=f"admin@{domain}")
    source = prompt.select(
        "Where does the server come from?",
        ["scaleway — provision it with Terraform (recommended)",
         "infomaniak — provision it with Terraform",
         "byo — I already have a Debian server"],
    )
    provider = source.split(" ", 1)[0]
    ssh = ""
    if provider == "byo":
        provider = None
        ssh = prompt.text("Server SSH target (user@host, blank to fill in later)")
    tls = prompt.select("TLS certificates", list(TLS_MODES), default="prod")
    storage = prompt.select("Object storage", ["external", "garage"], default="external")
    backups = prompt.confirm("Enable off-site backups?", default=True)
    labels = {a.label: a.name for a in manifest.APPS.values()}
    picked = prompt.checkbox("Enable apps (space to toggle, enter to confirm)",
                             choices=list(labels))
    apps = [labels[label] for label in picked]

    p.write_text(render(domain=domain, admin_email=admin_email, provider=provider,
                        ssh=ssh, tls=tls, storage=storage, backups=backups, apps=apps))
    load(p)  # self-check: init must never write a file apply refuses
    print(f"\n==> Wrote {p}.")
    print("    This file is the one place you describe your suite — edit it any time.")
    print("    Next: `suite plan` to preview, then `suite apply` to make it real.")


def render(*, domain, admin_email, provider, ssh, tls, storage, backups, apps) -> str:
    """Hand-rendered (not yaml.dump) so the file keeps its guiding comments."""
    lines = [
        "# suite.yaml — the single human-owned description of your OwnSuite (ADR-042).",
        "# Edit, then `suite apply`. Secrets NEVER go here (the seed stays exported).",
        "",
    ]
    if provider:
        lines.append(f"provider: {provider}")
    lines += [
        f"domain: {domain}",
        f"admin_email: {admin_email}",
        f"tls: {tls}                # selfsigned | staging | prod",
    ]
    if ssh:
        lines += ["", f"server: {{ssh: {ssh}}}"]
    lines += [
        "",
        f"object_storage: {{mode: {storage}}}",
        "",
        "backup:",
        f"  enabled: {'true' if backups else 'false'}",
        "  target: external        # external (prod) | in-cluster (CI)",
        "",
        "# Presence under apps: enables an app; remove the line (+ apply) to uninstall",
        "# it — data is kept. Per-app options: docs/reference/configuration.md.",
        "apps:" if apps else "apps: {}",
    ]
    lines += [f"  {name}: {{}}" for name in apps]
    return "\n".join(lines) + "\n"
