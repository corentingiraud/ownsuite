# Server bootstrap

Turn a **bare Debian server** into a ready **single-node K3s** cluster with one
command — the first step before installing OwnSuite.

> **What you get:** `suite bootstrap` turns a bare Debian server into a ready
> single-node K3s cluster.

This step is handled by **Ansible**, which applies three sets of changes in order:
`common` → `security` → `k3s`.

## What it does

| Role | Actions |
|---|---|
| `common` | Swap file + `vm.swappiness`, sysctl tunables (inotify, `ip_forward`, bridge-nf), the `overlay`/`br_netfilter` modules, base packages, time sync, **unattended security upgrades**. |
| `security` | **ufw** (default-deny ingress; allow 22/80/443 + the K3s pod/service CIDRs), **fail2ban** (sshd jail), **SSH hardening** (no root password login, no password auth). |
| `k3s` | Install the **pinned** K3s release (bundled Traefik + ServiceLB kept), write `/etc/rancher/k3s/config.yaml`, wait for the node to be `Ready`, and fetch the kubeconfig back to you. |

## Requirements

- A server running **Debian 12 (bookworm)** or **13 (trixie)**, reachable over SSH.
- On your machine: Python 3.10+, then `python3 -m suite deps` (installs Ansible + collections).

## Run it

```bash
git clone https://github.com/corentingiraud/ownsuite.git && cd ownsuite
python3 -m suite deps                       # one-time: tooling + collections
cp ansible/inventory/hosts.example.yml ansible/inventory/hosts.yml
$EDITOR ansible/inventory/hosts.yml         # set ansible_host / ansible_user
python3 -m suite check                      # dry-run (--check --diff), applies nothing
python3 -m suite bootstrap                  # provision the host
```

When it finishes, a `kubeconfig` is fetched to the repo root:

```bash
KUBECONFIG=./kubeconfig kubectl get nodes   # the node should be Ready
```

**Next:** the [guided installer](install.md) (`suite install`) wraps bootstrap and
everything after it — config, DNS records, the SSH tunnel, `helmfile sync`, and
staging→production certificates — so a bare server + a domain reaches HTTPS in one flow.

!!! note "Pinned versions"
    The K3s release and all collection versions are pinned in
    `ansible/group_vars/all.yml` and `ansible/requirements.yml`. Bumping a version is
    always an explicit, reviewable diff — never `latest` (see
    [AGENTS conventions](../project/for-ai-agents.md)).

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
  as-is and the Kubernetes API is never exposed to the internet — see
  [how it works](../understand/platform.md).

## Tests

The bootstrap is covered by a layered, automated test suite:

```bash
make lint        # yamllint + ansible-lint + syntax-check
make test        # Molecule: converge host-prep roles, idempotence, Testinfra (Debian 12 & 13)
make test-full   # Molecule: full bootstrap incl. real K3s, assert the node is Ready
```

`make lint` and `make test` run on every pull request; `make test-full` runs nightly
and whenever the K3s role changes.
