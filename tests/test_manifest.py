"""Drift guard: the app manifest must mirror the helmfile exactly (issue #82).

The helmfile is the runtime truth (releases + `condition: apps.<x>.enabled`);
`suite/manifest.py` is the CLI's copy. These tests parse the gotmpl sources so
adding/renaming a release or an option env var without updating the manifest
(or vice versa) fails CI — the drift that left meet/tchap out of the upgrade
rollback map can no longer happen silently.
"""

import re
from pathlib import Path

from suite import manifest

ROOT = Path(__file__).resolve().parents[1]
HELMFILE = ROOT / "helmfile" / "helmfile.yaml.gotmpl"
ENVIRONMENT = ROOT / "helmfile" / "environments" / "default.yaml.gotmpl"


def helmfile_app_releases():
    """{app: [release, ...]} for every release gated on `apps.<app>.enabled`,
    in file order. Only the `releases:` section — repository entries also use
    `- name:` but carry no condition."""
    releases_section = HELMFILE.read_text().split("\nreleases:", 1)[1]
    apps = {}
    for block in re.split(r"\n  - name: ", releases_section)[1:]:
        release = block.split("\n", 1)[0].strip()
        cond = re.search(r"condition: apps\.(\w+)\.enabled", block)
        if cond:
            apps.setdefault(cond.group(1), []).append(release)
    return apps


def test_release_groups_match_helmfile_exactly():
    assert helmfile_app_releases() == {
        name: list(app.releases) for name, app in manifest.APPS.items()
    }


def test_release_to_app_covers_every_app_release():
    for name, app in manifest.APPS.items():
        for release in app.releases:
            assert manifest.RELEASE_TO_APP[release] == name


def test_host_releases_include_keycloak_and_all_apps():
    assert manifest.HOST_RELEASES["auth"] == ("keycloak",)
    for app in manifest.APPS.values():
        assert manifest.HOST_RELEASES[app.host] == app.releases


def test_option_env_vars_and_defaults_match_environment():
    env_text = ENVIRONMENT.read_text()
    for app in manifest.APPS.values():
        assert f'env "{app.env_key}"' in env_text
        for key, (env_var, default) in app.options.items():
            assert f'env "{env_var}"' in env_text, f"{app.name}.{key} -> {env_var}"
            declared = re.search(rf'env "{env_var}" \| default "([^"]*)"', env_text)
            if declared:
                assert declared.group(1) == default, f"{app.name}.{key} default"
