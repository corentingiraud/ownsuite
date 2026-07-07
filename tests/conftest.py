"""Shared test helpers: build a real Spec/Context without touching disk."""

from pathlib import Path

from suite import spec


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
