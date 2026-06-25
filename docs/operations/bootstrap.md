# VPS bootstrap

Phase 0's deliverable: turn a **bare Debian VPS** into a ready **single-node K3s**
cluster with one command.

> **Definition of done:** `make bootstrap` turns a bare Debian VPS into a ready
> single-node K3s cluster.

This is implemented with **Ansible** (see
[ADR-002](../architecture/decisions.md#adr-002-ansible-for-the-host-not-nix)). The
playbook applies three roles in order: `common` → `security` → `k3s`.

## What it does

| Role | Actions |
|---|---|
| `common` | Swap file + `vm.swappiness`, sysctl tunables (inotify, `ip_forward`, bridge-nf), the `overlay`/`br_netfilter` modules, base packages, time sync, **unattended security upgrades**. |
| `security` | **ufw** (default-deny ingress; allow 22/80/443 + the K3s pod/service CIDRs), **fail2ban** (sshd jail), **SSH hardening** (no root password login, no password auth). |
| `k3s` | Install the **pinned** K3s release (bundled Traefik + ServiceLB kept), write `/etc/rancher/k3s/config.yaml`, wait for the node to be `Ready`, and fetch the kubeconfig back to you. |

## Requirements

- A VPS running **Debian 12 (bookworm)** or **13 (trixie)**, reachable over SSH.
- On your machine: Python 3.12+, then `make deps` (installs Ansible + collections).

## Run it

```bash
git clone https://github.com/corentingiraud/ownsuite.git && cd ownsuite
make deps                                   # one-time: tooling + collections
cp ansible/inventory/hosts.example.yml ansible/inventory/hosts.yml
$EDITOR ansible/inventory/hosts.yml         # set ansible_host / ansible_user
make check                                  # dry-run (--check --diff), applies nothing
make bootstrap                              # provision the host
```

When it finishes, a `kubeconfig` is fetched to the repo root:

```bash
KUBECONFIG=./kubeconfig kubectl get nodes   # the node should be Ready
```

**Next:** the [guided installer](install.md) (`make install`) wraps bootstrap and
everything after it — config, DNS records, the SSH tunnel, `helmfile sync`, and
staging→production certificates — so a bare VPS + a domain reaches HTTPS in one flow.

!!! note "Pinned versions"
    The K3s release and all collection versions are pinned in
    `ansible/group_vars/all.yml` and `ansible/requirements.yml`. Bumping a version is
    always an explicit, reviewable diff — never `latest` (see
    [AGENTS conventions](../contributing/for-ai-agents.md)).

## Caveats

!!! warning "SSH hardening can lock you out"
    `security` disables **password** authentication and root password login by default
    (`ssh_harden: true`). Make sure your **SSH key** is installed first. To bootstrap a
    password-only box, set `ssh_harden: false` in the inventory until your key is in
    place.

- **Firewall + K3s.** ufw is default-deny on ingress. The pod (`10.42.0.0/16`) and
  service (`10.43.0.0/16`) CIDRs are allowed explicitly — without that, CoreDNS and
  pod-to-pod traffic break. If you change K3s' CIDRs, update
  `firewall_allowed_tcp_ports`/CIDR vars to match.
- **Fetched kubeconfig** points at `https://127.0.0.1:6443`. You reach the cluster from
  your workstation through an SSH tunnel (`make tunnel`), so this address is used
  as-is and the K8s API is never exposed — see
  [shared infrastructure](platform.md) and
  [ADR-014](../architecture/decisions.md#adr-014-operator-control-plane-local-workstation-ssh-tunnel).

## Tests

The bootstrap is covered by an evolving, layered test harness
([ADR-010](../architecture/decisions.md#adr-010-testing-ci-strategy-a-layered-evolving-harness)):

```bash
make lint        # yamllint + ansible-lint + syntax-check
make test        # Molecule: converge host-prep roles, idempotence, Testinfra (Debian 12 & 13)
make test-full   # Molecule: full bootstrap incl. real K3s, assert the node is Ready
```

`make lint` and `make test` run on every pull request; `make test-full` runs nightly
and whenever the K3s role changes.
