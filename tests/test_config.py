from suite import config


def test_generate_seed_format():
    s = config.generate_seed()
    assert len(s) == 48 and all(c in "0123456789abcdef" for c in s)


def test_write_env_never_persists_the_seed(tmp_path):
    f = tmp_path / ".env"
    config.write_env(
        str(f), {"OWNSUITE_DOMAIN": "x.org", "OWNSUITE_SECRET_SEED": "super-secret"}
    )
    text = f.read_text()
    assert "super-secret" not in text  # the seed value is never written
    assert "OWNSUITE_SECRET_SEED=" not in text  # nor an assignment for it
    assert "OWNSUITE_DOMAIN=x.org" in text


def test_load_env_roundtrip(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comment\nOWNSUITE_DOMAIN=x.org\n\nOWNSUITE_BACKUP_ENABLED=true\n")
    assert config.load_env(str(f)) == {
        "OWNSUITE_DOMAIN": "x.org",
        "OWNSUITE_BACKUP_ENABLED": "true",
    }
