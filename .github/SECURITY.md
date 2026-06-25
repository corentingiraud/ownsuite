# Security Policy

## Supported versions

This project is under active development and has not cut a stable release yet.
Security fixes land on `main`; please track the latest commit.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private reporting instead:
[**Report a vulnerability**](https://github.com/corentingiraud/ownsuite/security/advisories/new).
This opens a private advisory visible only to the maintainers.

We aim to acknowledge a report within 7 days and to agree on a disclosure
timeline once the issue is confirmed.

## Scope

This repository ships the automation to self-host the suite (Ansible, Helmfile,
the installer). Vulnerabilities in the **upstream applications** it deploys
(Keycloak, the La Suite apps, operators) should be reported to those projects;
issues in **how this repo configures or exposes them** belong here.
