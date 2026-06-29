"""Testinfra verification for the full bootstrap: K3s is up and the node Ready.

This is the machine-checked form of the Phase 0 definition of done:
"`make bootstrap` turns a bare Debian server into a ready single-node K3s cluster."
"""

testinfra_hosts = ["all"]

KUBECTL = "k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml"


def test_k3s_binary_pinned(host):
    # Read the pin from the single source of truth (group_vars/all.yml) instead
    # of duplicating the literal here, so a version bump is a one-file change.
    expected = host.ansible.get_variables()["k3s_version"]
    version = host.check_output("k3s --version")
    assert expected in version


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
