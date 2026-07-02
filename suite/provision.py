"""`suite provision` — the Terraform step (infra half of a deployment).

Wraps `terraform`/`tofu` in `terraform/environments/<provider>/`: generate the
tfvars from prompts, `init` -> `plan` -> `apply`, then wire the outputs into the
rest of the flow — the non-secret ones into `.env` and the Ansible inventory, the
secret ones printed once as `export` lines (they cannot be derived from the seed).

Terraform is optional (skip it if you already have a Debian server + S3), so it is
its own command; `suite install` offers to run it when no server is configured yet.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import config, prompt
from .errors import SuiteError
from .process import run

PROVIDERS = ("scaleway", "infomaniak")
ENV_ROOT = "terraform/environments"
INVENTORY = "ansible/inventory/hosts.yml"
TEM_RELAY_HOST = "smtp.tem.scaleway.com:2587"  # Scaleway blocks 25/465/587 (ADR-038)


def run_provision(args):
    provider = args.provider or prompt.select("Cloud provider", list(PROVIDERS))
    if provider not in PROVIDERS:
        raise SuiteError(f"unknown provider '{provider}' (choose: {', '.join(PROVIDERS)})")
    tf = _tf_bin()
    env_dir = f"{ENV_ROOT}/{provider}"
    cfg = config.load_env(args.env_file)

    tfvars = Path(env_dir) / "terraform.tfvars"
    if args.force_tfvars or not tfvars.exists():
        tfvars.write_text(_tfvars_text(_prompt_tfvars(provider, cfg)))
        print(f"\n==> Wrote {tfvars}")
    else:
        print(f"\n==> Using existing {tfvars} (pass --force-tfvars to regenerate)")

    _warn_missing_creds(provider)

    run([tf, f"-chdir={env_dir}", "init"], step="terraform init")
    run([tf, f"-chdir={env_dir}", "plan"], step="terraform plan")
    if not args.yes and not prompt.confirm("Apply this Terraform plan?", default=False):
        raise SuiteError("aborted before apply")
    run([tf, f"-chdir={env_dir}", "apply", "-auto-approve"], step="terraform apply")

    proc = run([tf, f"-chdir={env_dir}", "output", "-json"], capture=True,
               step="terraform output")
    outputs = json.loads(proc.stdout or "{}")

    env_updates = {**_env_from_outputs(outputs), **_secrets_from_outputs(outputs)}
    if env_updates:
        config.write_env(args.env_file, {**cfg, **env_updates})
        print(f"\n==> Wrote infra values to {args.env_file}: {', '.join(env_updates)}")
    ssh_target = _out(outputs, "ssh_target")
    if ssh_target:
        Path(INVENTORY).parent.mkdir(parents=True, exist_ok=True)
        Path(INVENTORY).write_text(_inventory_yaml(ssh_target))
        print(f"==> Wrote Ansible inventory to {INVENTORY} ({ssh_target})")

    _secret_banner(outputs)
    print("\n==> Provisioned. Next: `suite install`.")


# --- terraform.tfvars generation -------------------------------------------------

def _prompt_tfvars(provider, cfg):
    """Collect the required tfvars for `provider`. Other vars keep their
    variables.tf defaults (region/zone/type/image) — edit terraform.tfvars to
    override. Values are typed (str/list/bool) so the HCL serializer renders them."""
    domain = cfg.get("OWNSUITE_DOMAIN", "")
    common = [
        ("name", "Deployment name / slug (prefixes resources)", "text", ""),
        ("ssh_public_key", "SSH public key (OpenSSH)", "text", _default_ssh_key()),
        ("bucket_names", "Media bucket name(s), comma-separated (blank in garage mode)",
         "list", ""),
        ("enable_mailbox", "Enable the mailbox (opens SMTP)?", "confirm", False),
    ]
    if provider == "scaleway":
        spec = [
            ("project_id", "Scaleway project ID", "text", ""),
            ("organization_id", "Scaleway organization ID (IAM is org-scoped)", "text", ""),
            *common,
            ("domain", "Base domain (TEM sending domain when mailbox on)", "text", domain),
        ]
    else:  # infomaniak
        spec = [
            ("openstack_cloud", "clouds.yaml entry name", "text", "ownsuite"),
            *common,
        ]
    values = {}
    for key, label, kind, default in spec:
        if kind == "confirm":
            values[key] = prompt.confirm(label, default=default)
        elif kind == "list":
            raw = prompt.text(label, default=default)
            values[key] = [b.strip() for b in raw.split(",") if b.strip()]
        else:
            values[key] = prompt.text(label, default=default)
    return values


def _tfvars_text(values):
    return "".join(f"{k} = {_hcl(v)}\n" for k, v in values.items())


def _hcl(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_hcl(v) for v in value) + "]"
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace('"', '\\"') + '"'


# --- output wiring ---------------------------------------------------------------

def _out(outputs, key):
    o = outputs.get(key)
    return o.get("value") if o else None


def _env_from_outputs(outputs):
    """Non-secret infra values for `.env`. Reuses Terraform's own `env_object_storage`
    snippet (the exact OWNSUITE_S3_* lines) rather than re-deriving them, so they can
    never drift from the module. Secrets (S3 keys, relay password) are NOT included."""
    env = {}
    ssh_target = _out(outputs, "ssh_target")
    if ssh_target:
        env["OWNSUITE_SERVER_SSH"] = ssh_target
    snippet = _out(outputs, "env_object_storage")
    if snippet and "<no bucket" not in snippet:
        for line in snippet.splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _secrets_from_outputs(outputs):
    """External secrets (provider-minted S3 keys, relay account) that cannot be
    seed-derived, mapped to their OWNSUITE_* keys. Written to the git-ignored .env so
    `suite sync`/`upgrade` pick them up without a manual export (they read the seed and
    these from .env, ADR-012)."""
    env = {}
    ak, sk = _out(outputs, "s3_access_key"), _out(outputs, "s3_secret_key")
    if ak and sk:
        env["OWNSUITE_S3_ACCESS_KEY"] = ak
        env["OWNSUITE_S3_SECRET_KEY"] = sk
    ru, rp = _out(outputs, "mta_relay_username"), _out(outputs, "mta_relay_password")
    if ru and rp:
        env["OWNSUITE_MTA_RELAY_USERNAME"] = ru
        env["OWNSUITE_MTA_RELAY_PASSWORD"] = rp
        env["OWNSUITE_MTA_RELAY_HOST"] = TEM_RELAY_HOST
    return env


def _inventory_yaml(ssh_target):
    user, sep, host = ssh_target.partition("@")
    if not sep:  # bare host, no user@ prefix
        user, host = "root", ssh_target
    return (
        "---\n"
        "# Written by `suite provision`. Single-node K3s = one host in `ownsuite`.\n"
        "ownsuite:\n"
        "  hosts:\n"
        "    vps:\n"
        f'      ansible_host: "{host}"\n'
        f'      ansible_user: "{user}"\n'
    )


def _secret_banner(outputs):
    """The provider-minted secrets are written to the git-ignored .env (above); this
    only reminds the operator to (a) also stash them in a password manager — .env is
    disposable — and (b) publish the TEM email DNS records."""
    ak = _out(outputs, "s3_access_key")
    ru = _out(outputs, "mta_relay_username")
    if ak or ru:
        print(
            "\n" + "=" * 70 + "\n"
            "EXTERNAL SECRETS were written to .env (git-ignored) so `suite sync`/`upgrade`\n"
            "can read them. They cannot be derived from the seed — ALSO store them in your\n"
            "password manager, since .env is disposable.\n" + "=" * 70
        )
    tem_dns = _out(outputs, "tem_dns")
    if tem_dns:
        print("\n==> Also publish the TEM SPF/DKIM/DMARC records:\n" + str(tem_dns))


# --- helpers ---------------------------------------------------------------------

def _tf_bin():
    for cand in ("terraform", "tofu"):
        if shutil.which(cand):
            return cand
    raise SuiteError("neither `terraform` nor `tofu` found on PATH")


def _default_ssh_key():
    for name in ("id_ed25519.pub", "id_rsa.pub"):
        p = Path.home() / ".ssh" / name
        if p.exists():
            return p.read_text().strip()
    return ""


def _warn_missing_creds(provider):
    if provider == "scaleway":
        have_env = os.environ.get("SCW_ACCESS_KEY") and os.environ.get("SCW_SECRET_KEY")
        have_file = (Path.home() / ".config/scw/config.yaml").exists()
        if not (have_env or have_file):
            print("\nWARNING: SCW_ACCESS_KEY/SCW_SECRET_KEY not set and no "
                  "~/.config/scw/config.yaml — Terraform will fail to authenticate.")
    else:  # infomaniak
        have_file = (Path.home() / ".config/openstack/clouds.yaml").exists()
        if not (have_file or os.environ.get("OS_AUTH_URL")):
            print("\nWARNING: no ~/.config/openstack/clouds.yaml and no OS_* env — "
                  "Terraform will fail to authenticate.")
