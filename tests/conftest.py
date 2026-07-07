"""Shared test helpers: build a real Spec/Context without touching disk."""

import os
from pathlib import Path

import pytest

from suite import spec


@pytest.fixture(autouse=True)
def _isolate_environ():
    """Snapshot/restore os.environ around every test: code under test (e.g.
    config.load_env_file) writes the global environ, and monkeypatch.delenv of an
    absent key records nothing to restore — so those writes would leak between
    tests and flip ambient-wins branches (assemble_env drops keys already in
    os.environ)."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def make_spec(apps=("docs",), tls="prod", provider=None, ssh="", **extra):
    data = {"domain": "assoc.org", "tls": tls, "apps": {a: {} for a in apps}, **extra}
    if provider:
        data["provider"] = provider
    if ssh:
        data["server"] = {"ssh": ssh}
    return spec.Spec(data, Path("suite.yaml"))


def make_ctx(apps=("docs",), tls="prod", ssh="", state=None, view=None):
    """A Context with a hand-built env/view so ambient OWNSUITE_* never leaks in."""
    sp = make_spec(apps=apps, tls=tls, ssh=ssh)
    env = {"OWNSUITE_DOMAIN": "assoc.org"}
    v = {"OWNSUITE_DOMAIN": "assoc.org", "OWNSUITE_BACKUP_ENABLED": "true",
         **(view or {})}
    return spec.Context(sp, state if state is not None else {}, env, v, ssh)
