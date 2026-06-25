# OwnSuite — developer & operator entrypoints.
# `make bootstrap` is the Phase 0 definition of done.

ANSIBLE_DIR := ansible
PLAYBOOK    := $(ANSIBLE_DIR)/bootstrap.yml
INVENTORY   := $(ANSIBLE_DIR)/inventory/hosts.yml

# --- Helmfile (Phase 1 shared infrastructure) --------------------------------
HELMFILE := helmfile/helmfile.yaml.gotmpl
# Dummy seed so `helm template`/`lint` can render; the real seed is required only
# at `sync` time (helmfile/environments/default.yaml.gotmpl uses requiredEnv).
LINT_SEED := OWNSUITE_SECRET_SEED=lint-only-not-a-secret
# kubeconform schema sources: built-in Kubernetes schemas + the community CRD
# catalog (cert-manager, CloudNativePG, ...). Missing schemas are skipped.
KUBECONFORM_SCHEMAS := -schema-location default -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

# Everything runs from your workstation (ADR-014). helmfile/kubectl reach the
# cluster through the kubeconfig fetched by the bootstrap (server 127.0.0.1:6443),
# via an SSH tunnel to the VPS — the K8s API is never exposed (firewall keeps only
# 22/80/443). Open the tunnel with `make tunnel` before `make sync`.
KUBECONFIG ?= ./kubeconfig
export KUBECONFIG
# SSH target for the tunnel, e.g. OWNSUITE_VPS_SSH=root@203.0.113.10
OWNSUITE_VPS_SSH ?=

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: deps
deps: ## Install Python tooling and Ansible collections (app + test harness)
	pip install -r requirements-dev.txt
	ansible-galaxy collection install -r $(ANSIBLE_DIR)/requirements.yml
	ansible-galaxy collection install -r molecule/requirements.yml

.PHONY: bootstrap
bootstrap: ## Provision the VPS into a ready single-node K3s cluster
	cd $(ANSIBLE_DIR) && ansible-playbook bootstrap.yml

.PHONY: check
check: ## Dry-run the bootstrap (--check --diff), no changes applied
	cd $(ANSIBLE_DIR) && ansible-playbook bootstrap.yml --check --diff

.PHONY: lint
lint: lint-ansible lint-helm ## Static checks: Ansible + Helm/Helmfile

.PHONY: lint-ansible
lint-ansible: ## Ansible static checks: yamllint + ansible-lint + syntax-check
	yamllint .
	ansible-lint $(PLAYBOOK)
	cd $(ANSIBLE_DIR) && ansible-playbook bootstrap.yml --syntax-check

.PHONY: lint-helm
lint-helm: ## Helm/Helmfile static checks: helm lint + render + kubeconform
	helm lint helmfile/charts/*
	$(LINT_SEED) helmfile -f $(HELMFILE) template | \
		kubeconform -strict -ignore-missing-schemas -summary $(KUBECONFORM_SCHEMAS)

.PHONY: tunnel
tunnel: ## Open an SSH tunnel to the VPS K8s API on :6443 (set OWNSUITE_VPS_SSH=user@host)
	@test -n "$(OWNSUITE_VPS_SSH)" || { echo "Set OWNSUITE_VPS_SSH=user@host (your VPS)"; exit 1; }
	ssh -N -L 6443:127.0.0.1:6443 $(OWNSUITE_VPS_SSH)

.PHONY: sync
sync: ## Deploy/upgrade the shared infra (needs $$OWNSUITE_SECRET_SEED + an open `make tunnel`)
	helmfile -f $(HELMFILE) sync

.PHONY: diff
diff: ## Preview pending changes to the shared infrastructure
	helmfile -f $(HELMFILE) diff

.PHONY: destroy
destroy: ## Remove the shared infrastructure (CRDs are kept)
	helmfile -f $(HELMFILE) destroy

.PHONY: test
test: ## Fast container tests (Molecule default scenario)
	molecule test

.PHONY: test-full
test-full: ## Full bootstrap incl. real K3s (Molecule full scenario)
	molecule test -s full

.PHONY: test-platform
test-platform: ## Full Helmfile DoD on a throwaway k3d cluster (heavy)
	helmfile/tests/run-e2e.sh
