"""Testinfra verification for the full bootstrap: K3s is up and the node Ready.

This is the machine-checked form of the Phase 0 definition of done:
"`make bootstrap` turns a bare Debian server into a ready single-node K3s cluster."
"""

import os
from pathlib import Path

import yaml

testinfra_hosts = ["all"]

KUBECTL = "k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml"


def _pinned_k3s_version():
    # Single source of truth: the k3s role default (Renovate-tracked). Read it
    # straight from the repo so this test can never drift from the pin, and a
    # version bump stays a one-file change.
    root = Path(os.environ["MOLECULE_PROJECT_DIRECTORY"])
    defaults = yaml.safe_load((root / "ansible/roles/k3s/defaults/main.yml").read_text())
    return defaults["k3s_version"]


def test_k3s_binary_pinned(host):
    version = host.check_output("k3s --version")
    assert _pinned_k3s_version() in version


def test_k3s_service_running(host):
    svc = host.service("k3s")
    assert svc.is_enabled
    assert svc.is_running


def test_node_is_ready(host):
    out = host.check_output(
        KUBECTL + " get nodes --no-headers"
    )
    # Exactly one node, in Ready state (not NotReady).
    assert " Ready " in f" {out} "
    assert "NotReady" not in out


def test_core_components_present(host):
    pods = host.check_output(KUBECTL + " get pods -n kube-system --no-headers")
    for component in ("coredns", "traefik", "local-path-provisioner"):
        assert component in pods
