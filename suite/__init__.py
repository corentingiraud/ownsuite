"""OwnSuite installer / control-plane package (Phase 4, ADR-018).

`suite` is the guided installer that takes a bare server + a domain to all-in-HTTPS:
it captures configuration, generates the DNS records, waits for propagation,
opens the SSH tunnel, runs the Helmfile stack, issues TLS certificates
(Let's Encrypt staging -> production) and verifies HTTPS per host. It orchestrates
the existing Ansible/Helmfile layers rather than reimplementing them, and
prefigures the Phase 5 ``suite`` CLI (ADR-007).
"""

__version__ = "0.1.0"
