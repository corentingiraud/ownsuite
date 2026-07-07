"""Unit tests for the Terraform layer (suite.provision) — pure helpers plus the
ensure_infra drift detection. No terraform, no TTY: the subprocess boundary and
prompts are mocked."""

from types import SimpleNamespace

from conftest import make_spec

from suite import provision, spec, state


def _out(value, sensitive=False):
    return {"value": value, "type": "string", "sensitive": sensitive}


def test_hcl_serialization_by_type():
    assert provision._hcl("mon-assoc") == '"mon-assoc"'
    assert provision._hcl(True) == "true"
    assert provision._hcl(False) == "false"
    assert provision._hcl(["a", "b"]) == '["a", "b"]'
    assert provision._hcl([]) == "[]"


def test_tfvars_text_renders_strings_lists_and_bools():
    text = provision._tfvars_text({
        "name": "mon-assoc",
        "bucket_names": ["mon-assoc-media"],
        "enable_mailbox": False,
    })
    assert 'name = "mon-assoc"' in text
    assert 'bucket_names = ["mon-assoc-media"]' in text
    assert "enable_mailbox = false" in text


def test_env_from_outputs_maps_object_storage_only():
    outputs = {
        "ssh_target": _out("root@203.0.113.10"),
        "env_object_storage": _out(
            "OWNSUITE_S3_ENDPOINT=https://s3.fr-par.scw.cloud\n"
            "OWNSUITE_S3_REGION=fr-par\n"
            "OWNSUITE_S3_BUCKET=mon-assoc-media\n"
        ),
        "s3_access_key": _out("SCWXXXX", sensitive=True),
        "s3_secret_key": _out("secret", sensitive=True),
    }
    env = provision._env_from_outputs(outputs)
    assert env["OWNSUITE_S3_ENDPOINT"] == "https://s3.fr-par.scw.cloud"
    assert env["OWNSUITE_S3_BUCKET"] == "mon-assoc-media"
    # The ssh target goes to the state's own key, not the env map.
    assert "OWNSUITE_SERVER_SSH" not in env
    # _env_from_outputs stays non-secret; secrets come from _secrets_from_outputs.
    assert "OWNSUITE_S3_ACCESS_KEY" not in env
    assert "OWNSUITE_S3_SECRET_KEY" not in env


def test_secrets_from_outputs_maps_s3_and_relay():
    outputs = {
        "s3_access_key": _out("SCWXXXX", sensitive=True),
        "s3_secret_key": _out("secret", sensitive=True),
        "mta_relay_username": _out("relay-user", sensitive=True),
        "mta_relay_password": _out("relay-pass", sensitive=True),
    }
    env = provision._secrets_from_outputs(outputs)
    assert env["OWNSUITE_S3_ACCESS_KEY"] == "SCWXXXX"
    assert env["OWNSUITE_S3_SECRET_KEY"] == "secret"
    assert env["OWNSUITE_MTA_RELAY_USERNAME"] == "relay-user"
    assert env["OWNSUITE_MTA_RELAY_PASSWORD"] == "relay-pass"
    assert env["OWNSUITE_MTA_RELAY_HOST"] == provision.TEM_RELAY_HOST


def test_env_from_outputs_maps_backup_snippet():
    outputs = {"env_backup": _out(
        "OWNSUITE_BACKUP_S3_ENDPOINT=https://s3.nl-ams.scw.cloud\n"
        "OWNSUITE_BACKUP_S3_REGION=nl-ams\n"
        "OWNSUITE_BACKUP_S3_BUCKET=ownsuite-test-backups\n"
    )}
    env = provision._env_from_outputs(outputs)
    assert env["OWNSUITE_BACKUP_S3_ENDPOINT"] == "https://s3.nl-ams.scw.cloud"
    assert env["OWNSUITE_BACKUP_S3_BUCKET"] == "ownsuite-test-backups"


def test_env_from_outputs_skips_empty_backup_snippet():
    # No backup bucket -> env_backup is "" -> nothing written.
    assert provision._env_from_outputs({"env_backup": _out("")}) == {}


def test_secrets_from_outputs_maps_backup_keys():
    outputs = {
        "s3_access_key": _out("SCWXXXX", sensitive=True),
        "s3_secret_key": _out("secret", sensitive=True),
        "backup_s3_access_key": _out("SCWBAK", sensitive=True),
        "backup_s3_secret_key": _out("baksecret", sensitive=True),
    }
    env = provision._secrets_from_outputs(outputs)
    assert env["OWNSUITE_BACKUP_S3_ACCESS_KEY"] == "SCWBAK"
    assert env["OWNSUITE_BACKUP_S3_SECRET_KEY"] == "baksecret"


def test_secrets_from_outputs_no_backup_keys_when_null():
    # backup_* outputs are null when no backup bucket -> not written.
    outputs = {
        "s3_access_key": _out("SCWXXXX", sensitive=True),
        "s3_secret_key": _out("secret", sensitive=True),
        "backup_s3_access_key": _out(None, sensitive=True),
        "backup_s3_secret_key": _out(None, sensitive=True),
    }
    env = provision._secrets_from_outputs(outputs)
    assert "OWNSUITE_BACKUP_S3_ACCESS_KEY" not in env


def test_secrets_from_outputs_empty_when_absent():
    assert provision._secrets_from_outputs({}) == {}


def test_env_from_outputs_skips_placeholder_bucket_snippet():
    outputs = {"env_object_storage": _out(
        "OWNSUITE_S3_ENDPOINT=x\nOWNSUITE_S3_BUCKET=<no bucket: set bucket_names>\n"
    )}
    assert provision._env_from_outputs(outputs) == {}


def test_inventory_yaml_splits_user_and_host():
    yaml = provision._inventory_yaml("root@1.2.3.4")
    assert 'ansible_host: "1.2.3.4"' in yaml
    assert 'ansible_user: "root"' in yaml


def test_inventory_yaml_defaults_user_when_no_prefix():
    yaml = provision._inventory_yaml("1.2.3.4")
    assert 'ansible_host: "1.2.3.4"' in yaml
    assert 'ansible_user: "root"' in yaml


# --- ensure_infra drift detection ---------------------------------------------

def _wire_infra(monkeypatch, tmp_path, *, outputs=None):
    """A fake terraform env dir + recorded subprocess calls + silenced state IO."""
    calls = []
    env_dir = tmp_path / "terraform" / "environments" / "scaleway"
    env_dir.mkdir(parents=True)
    (env_dir / "terraform.tfvars").write_text('project_id = "p"\n')
    monkeypatch.setattr(provision, "ENV_ROOT", str(tmp_path / "terraform" / "environments"))
    monkeypatch.setattr(provision, "_tf_bin", lambda: "tofu")
    monkeypatch.setattr(provision, "_warn_missing_creds", lambda p: None)
    monkeypatch.setattr(provision, "write_inventory", lambda ssh: None)
    monkeypatch.setattr(state, "save", lambda st: None)

    import json

    def run(argv, **kw):
        calls.append(list(argv))
        out = json.dumps(outputs or {}) if "output" in argv else ""
        return SimpleNamespace(returncode=0, stdout=out)

    monkeypatch.setattr(provision, "run", run)
    return calls, env_dir


def test_ensure_infra_skips_when_inputs_unchanged(monkeypatch, tmp_path):
    sp = make_spec(provider="scaleway")
    calls, _ = _wire_infra(monkeypatch, tmp_path)
    st = {"provisioned": True, "provider": "scaleway", "tfvars": spec.tfvars_for(sp)}
    assert provision.ensure_infra(sp, st, assume_yes=True) is False
    assert calls == []


def test_ensure_infra_applies_on_drift_and_updates_state(monkeypatch, tmp_path):
    sp = make_spec(provider="scaleway", apps=("docs", "meet"))
    outputs = {"ssh_target": _out("root@203.0.113.10")}
    calls, env_dir = _wire_infra(monkeypatch, tmp_path, outputs=outputs)
    st = {"provisioned": True, "provider": "scaleway",
          "tfvars": spec.tfvars_for(make_spec(provider="scaleway", apps=("docs",)))}
    assert provision.ensure_infra(sp, st, assume_yes=True) is True
    assert [c[-1] for c in calls] == ["init", "plan", "-auto-approve", "-json"]
    # The derived inputs land in suite.auto.tfvars — enable_meet flips there.
    auto = (env_dir / "suite.auto.tfvars").read_text()
    assert "enable_meet = true" in auto
    assert st["ssh"] == "root@203.0.113.10"
    assert st["tfvars"] == spec.tfvars_for(sp)
    assert st["provisioned"] is True


def test_ensure_infra_plan_only_stops_after_plan(monkeypatch, tmp_path):
    sp = make_spec(provider="scaleway")
    calls, _ = _wire_infra(monkeypatch, tmp_path)
    assert provision.ensure_infra(sp, {}, assume_yes=True, plan_only=True) is False
    assert [c[-1] for c in calls] == ["init", "plan"]
