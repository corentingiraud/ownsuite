"""Unit tests for the seed helpers (suite.config) — generation, derivation, and
the prompt-don't-fail acquisition with its wrong-seed fingerprint guard."""

import pytest

from suite import config
from suite.errors import SuiteError


def test_generate_seed_format():
    s = config.generate_seed()
    assert len(s) == 48 and all(c in "0123456789abcdef" for c in s)


def test_derive_secret_matches_chart_shape():
    # sha256("<seed>:<id>") truncated — must stay in lockstep with the Helm helper.
    out = config.derive_secret("seed", "keycloak-admin")
    assert len(out) == 32 and all(c in "0123456789abcdef" for c in out)
    assert out == config.derive_secret("seed", "keycloak-admin")  # deterministic
    assert out != config.derive_secret("seed", "other-id")


def test_require_seed_uses_exported_env(monkeypatch):
    monkeypatch.setenv("OWNSUITE_SECRET_SEED", "abc")
    st = {}
    assert config.require_seed(st) == "abc"
    assert st["seed_check"] == config.seed_fingerprint("abc")


def test_require_seed_missing_and_non_interactive_errors(monkeypatch):
    monkeypatch.delenv("OWNSUITE_SECRET_SEED", raising=False)
    with pytest.raises(SuiteError, match="OWNSUITE_SECRET_SEED must be exported"):
        config.require_seed({}, interactive=False)


def test_require_seed_refuses_wrong_seed(monkeypatch):
    """A wrong seed would silently re-derive (rotate) every credential."""
    monkeypatch.setenv("OWNSUITE_SECRET_SEED", "not-the-original")
    st = {"seed_check": config.seed_fingerprint("the-original")}
    with pytest.raises(SuiteError, match="NOT the seed"):
        config.require_seed(st)


def test_require_seed_exports_for_subprocesses(monkeypatch):
    monkeypatch.delenv("OWNSUITE_SECRET_SEED", raising=False)
    monkeypatch.setattr(config, "generate_seed", lambda: "fresh")
    monkeypatch.setattr(config, "seed_banner", lambda s: None)

    class _Prompt:
        @staticmethod
        def confirm(msg, default=False):
            return True  # "generate a NEW seed?"

    monkeypatch.setattr("suite.prompt.confirm", _Prompt.confirm)
    seed = config.require_seed({}, interactive=True)
    assert seed == "fresh"
    import os
    assert os.environ["OWNSUITE_SECRET_SEED"] == "fresh"
