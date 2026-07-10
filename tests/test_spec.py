"""Unit tests for suite.yaml loading/validation and the env/tfvars derivation
(suite.spec) — the declarative core of ADR-042."""

from pathlib import Path

import pytest
from conftest import make_spec

from suite import spec
from suite.errors import SuiteError

P = Path("suite.yaml")


def _load(tmp_path, text):
    f = tmp_path / "suite.yaml"
    f.write_text(text)
    return spec.load(f)


# --- validation ---------------------------------------------------------------

def test_minimal_valid_file(tmp_path):
    sp = _load(tmp_path, "domain: x.org\ntls: selfsigned\napps:\n  docs: {}\n")
    assert sp.domain == "x.org"
    assert sp.enabled_apps() == ["docs"]
    assert sp.admin_email == "admin@x.org"  # derived default


def test_missing_file_points_at_init(tmp_path):
    with pytest.raises(SuiteError, match="suite init"):
        spec.load(tmp_path / "suite.yaml")


def test_domain_required(tmp_path):
    with pytest.raises(SuiteError, match="`domain` is required"):
        _load(tmp_path, "tls: prod\n")


def test_tls_choices_enforced(tmp_path):
    with pytest.raises(SuiteError, match="selfsigned, staging, prod"):
        _load(tmp_path, "domain: x.org\ntls: production\n")


def test_unknown_top_key_rejected(tmp_path):
    with pytest.raises(SuiteError, match="unknown key.*tsl"):
        _load(tmp_path, "domain: x.org\ntls: prod\ntsl: prod\n")


def test_unknown_app_lists_available(tmp_path):
    with pytest.raises(SuiteError, match="unknown app 'wiki'.*docs"):
        _load(tmp_path, "domain: x.org\ntls: prod\napps:\n  wiki: {}\n")


def test_unknown_app_option_lists_valid(tmp_path):
    with pytest.raises(SuiteError, match="apps.tchap: unknown option.*s3_bucket"):
        _load(tmp_path, "domain: x.org\ntls: prod\napps:\n  tchap: {bucket: b}\n")


def test_bare_app_entry_means_enabled(tmp_path):
    sp = _load(tmp_path, "domain: x.org\ntls: prod\napps:\n  tchap:\n")
    assert sp.enabled_apps() == ["tchap"]


def test_provider_choices(tmp_path):
    with pytest.raises(SuiteError, match="provider must be one of"):
        _load(tmp_path, "provider: aws\ndomain: x.org\ntls: prod\n")


def test_infomaniak_provider_rejected(tmp_path):
    with pytest.raises(SuiteError, match="provider must be one of"):
        _load(tmp_path, "provider: infomaniak\ndomain: x.org\ntls: prod\n")


def test_backup_target_choices(tmp_path):
    with pytest.raises(SuiteError, match="backup.target"):
        _load(tmp_path, "domain: x.org\ntls: prod\nbackup: {target: offsite}\n")


def test_unknown_backup_key(tmp_path):
    with pytest.raises(SuiteError, match="backup: unknown key"):
        _load(tmp_path, "domain: x.org\ntls: prod\nbackup: {buckets: b}\n")


def test_calendars_sharing_level_choices(tmp_path):
    with pytest.raises(SuiteError, match="apps.calendars.sharing_level"):
        _load(tmp_path, "domain: x.org\ntls: prod\napps:\n  calendars: {sharing_level: public}\n")


def test_calendars_sharing_level_valid(tmp_path):
    sp = _load(tmp_path, "domain: x.org\ntls: prod\napps:\n  calendars: {sharing_level: read}\n")
    assert sp.app_options("calendars")["sharing_level"] == "read"


# --- env assembly ---------------------------------------------------------------

def test_assemble_env_forces_app_toggles(monkeypatch):
    # Even an exported OWNSUITE_APP_* must lose: suite.yaml is the only app switch.
    monkeypatch.setenv("OWNSUITE_APP_TCHAP", "true")
    env = spec.assemble_env(make_spec(apps=("docs",)), {})
    assert env["OWNSUITE_APP_DOCS"] == "true"
    assert env["OWNSUITE_APP_TCHAP"] == "false"


def test_assemble_env_ambient_wins_for_other_keys(monkeypatch):
    monkeypatch.setenv("OWNSUITE_DOMAIN", "ci-override.org")
    env = spec.assemble_env(make_spec(), {})
    # Left out of the dict so process.run's os.environ merge keeps the override.
    assert "OWNSUITE_DOMAIN" not in env


def test_assemble_env_spec_beats_state(monkeypatch):
    monkeypatch.delenv("OWNSUITE_S3_REGION", raising=False)
    sp = make_spec(object_storage={"mode": "external", "region": "fr-par"})
    st = {"env": {"OWNSUITE_S3_REGION": "nl-ams", "OWNSUITE_S3_ACCESS_KEY": "k"}}
    env = spec.assemble_env(sp, st)
    assert env["OWNSUITE_S3_REGION"] == "fr-par"     # suite.yaml wins over state
    assert env["OWNSUITE_S3_ACCESS_KEY"] == "k"      # state-only keys flow through


def test_assemble_env_emits_only_set_keys(monkeypatch):
    monkeypatch.delenv("OWNSUITE_PG_STORAGE", raising=False)
    env = spec.assemble_env(make_spec(), {})
    # Omitted in suite.yaml -> omitted here -> helmfile default applies.
    assert "OWNSUITE_PG_STORAGE" not in env


def test_assemble_env_app_options(monkeypatch):
    monkeypatch.delenv("OWNSUITE_TCHAP_S3_BUCKET", raising=False)
    sp = spec.Spec({"domain": "x.org", "tls": "prod",
                    "apps": {"tchap": {"s3_bucket": "my-bucket"}}}, P)
    assert spec.assemble_env(sp, {})["OWNSUITE_TCHAP_S3_BUCKET"] == "my-bucket"


def test_assemble_env_booleans_normalised(monkeypatch):
    monkeypatch.delenv("OWNSUITE_MEET_TURN", raising=False)
    sp = spec.Spec({"domain": "x.org", "tls": "prod",
                    "apps": {"meet": {"turn": True}}}, P)
    assert spec.assemble_env(sp, {})["OWNSUITE_MEET_TURN"] == "true"


def test_issuer_by_tls():
    assert spec.ISSUER_BY_TLS == {
        "selfsigned": "selfsigned",
        "staging": "letsencrypt-staging",
        "prod": "letsencrypt-http01",
    }


# --- terraform derivation ---------------------------------------------------------

def test_tfvars_app_flags_and_buckets():
    sp = spec.Spec({
        "domain": "x.org", "tls": "prod", "provider": "scaleway",
        "backup": {"enabled": True, "target": "external"},
        "apps": {"docs": {}, "meet": {"turn": True}, "messages": {},
                 "tchap": {"s3_bucket": "custom-tchap"}},
    }, P)
    tf = spec.tfvars_for(sp)
    assert tf["enable_mailbox"] is True
    assert tf["enable_meet"] is True
    assert tf["enable_meet_turn"] is True
    assert tf["domain"] == "x.org"
    # Manifest defaults fill unset buckets; per-app options override; grist (PVC)
    # would contribute none.
    assert tf["bucket_names"] == [
        "docs-media-storage", "messages-media-storage", "meet-recordings",
        "custom-tchap",
    ]
    assert tf["backup_bucket_name"] == "ownsuite-backups"


def test_tfvars_no_meet_no_ports():
    tf = spec.tfvars_for(make_spec(apps=("docs",)))
    assert tf["enable_meet"] is False and tf["enable_meet_turn"] is False
    assert tf["enable_mailbox"] is False


def test_tfvars_in_cluster_mode_has_no_buckets():
    sp = spec.Spec({"domain": "x.org", "tls": "prod",
                    "object_storage": {"mode": "in-cluster"},
                    "apps": {"docs": {}}}, P)
    assert spec.tfvars_for(sp)["bucket_names"] == []


def test_tfvars_endpoint_alone_still_provisions():
    # issue #86: setting endpoint/region no longer disables provisioning — the
    # bucket is still Terraform-owned (provision defaults on with a provider).
    sp = spec.Spec({"domain": "x.org", "tls": "prod", "provider": "scaleway",
                    "backup": {"enabled": True, "target": "external",
                               "endpoint": "https://s3.nl-ams.scw.cloud",
                               "region": "nl-ams", "bucket": "own-backups"},
                    "apps": {}}, P)
    assert spec.tfvars_for(sp)["backup_bucket_name"] == "own-backups"


def test_tfvars_byo_backup_store_not_provisioned():
    # BYO/real-DR off-site store (ADR-006): provision: false → no bucket minted.
    sp = spec.Spec({"domain": "x.org", "tls": "prod", "provider": "scaleway",
                    "backup": {"enabled": True, "target": "external",
                               "provision": False,
                               "endpoint": "https://elsewhere.example"},
                    "apps": {}}, P)
    assert spec.tfvars_for(sp)["backup_bucket_name"] == ""


def test_tfvars_no_provider_defaults_provision_off():
    # No provider = no cloud to mint the bucket; default provision off (BYO server).
    sp = spec.Spec({"domain": "x.org", "tls": "prod",
                    "backup": {"enabled": True, "target": "external"},
                    "apps": {}}, P)
    assert spec.tfvars_for(sp)["backup_bucket_name"] == ""


def test_tfvars_in_cluster_backup_not_provisioned():
    sp = spec.Spec({"domain": "x.org", "tls": "prod",
                    "backup": {"enabled": True, "target": "in-cluster"},
                    "apps": {}}, P)
    assert spec.tfvars_for(sp)["backup_bucket_name"] == ""


# --- init rendering ---------------------------------------------------------------

def test_render_roundtrips_through_the_validator(tmp_path):
    text = spec.render(domain="x.org", admin_email="a@x.org", provider="scaleway",
                       ssh="", tls="prod", storage="external", backups=True,
                       apps=["docs", "tchap"])
    sp = _load(tmp_path, text)
    assert sp.provider == "scaleway"
    assert sp.enabled_apps() == ["docs", "tchap"]
    assert sp.section("backup").get("enabled") is True


def test_render_byo_server(tmp_path):
    text = spec.render(domain="x.org", admin_email="a@x.org", provider=None,
                       ssh="root@1.2.3.4", tls="selfsigned", storage="in-cluster",
                       backups=False, apps=[])
    sp = _load(tmp_path, text)
    assert sp.provider is None
    assert sp.ssh == "root@1.2.3.4"
    assert sp.enabled_apps() == []
