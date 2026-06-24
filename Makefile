# OwnSuite — developer & operator entrypoints.
# `make bootstrap` is the Phase 0 definition of done.

ANSIBLE_DIR := ansible
PLAYBOOK    := $(ANSIBLE_DIR)/bootstrap.yml
INVENTORY   := $(ANSIBLE_DIR)/inventory/hosts.yml

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
lint: ## Static checks: yamllint + ansible-lint + syntax-check
	yamllint .
	ansible-lint $(PLAYBOOK)
	cd $(ANSIBLE_DIR) && ansible-playbook bootstrap.yml --syntax-check

.PHONY: test
test: ## Fast container tests (Molecule default scenario)
	molecule test

.PHONY: test-full
test-full: ## Full bootstrap incl. real K3s (Molecule full scenario)
	molecule test -s full
