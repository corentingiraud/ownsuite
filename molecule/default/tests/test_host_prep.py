"""Testinfra verification for the host-preparation roles (common + security).

These assertions are the machine-checked contract of Phase 0's host prep. New
phases add their own test modules alongside this one rather than editing it.
"""

import pytest

testinfra_hosts = ["all"]


# --- common role -------------------------------------------------------------

def test_base_packages_installed(host):
    for pkg in ("curl", "ca-certificates", "gnupg"):
        assert host.package(pkg).is_installed


def test_sysctl_drop_in_present(host):
    f = host.file("/etc/sysctl.d/90-ownsuite.conf")
    assert f.exists
    assert f.contains("vm.swappiness")
    assert f.contains("fs.inotify.max_user_instances")


def test_kernel_modules_persisted(host):
    f = host.file("/etc/modules-load.d/ownsuite-k3s.conf")
    assert f.exists
    assert f.contains("br_netfilter")


def test_unattended_upgrades(host):
    assert host.package("unattended-upgrades").is_installed
    assert host.file("/etc/apt/apt.conf.d/20auto-upgrades").contains(
        'APT::Periodic::Unattended-Upgrade "1"'
    )


# --- security role -----------------------------------------------------------

def test_firewall_installed(host):
    assert host.package("ufw").is_installed


def test_fail2ban_jail_configured(host):
    assert host.package("fail2ban").is_installed
    jail = host.file("/etc/fail2ban/jail.d/ownsuite.local")
    assert jail.exists
    assert jail.contains(r"\[sshd\]")
    # An ignoreip allowlist must be present so the operator's IP can be exempted.
    assert jail.contains(r"ignoreip")


def test_ssh_hardening_drop_in(host):
    f = host.file("/etc/ssh/sshd_config.d/90-ownsuite.conf")
    assert f.exists
    assert f.contains("PasswordAuthentication no")
    assert f.contains("PermitRootLogin prohibit-password")


@pytest.mark.parametrize("port", [22, 80, 443])
def test_ufw_allows_public_ports(host, port):
    # ufw stores its committed rules under /etc/ufw/user.rules.
    rules = host.file("/etc/ufw/user.rules")
    assert rules.contains(str(port))


def test_ufw_allows_k3s_cidrs(host):
    rules = host.file("/etc/ufw/user.rules")
    assert rules.contains("10.42.0.0/16")
    assert rules.contains("10.43.0.0/16")
