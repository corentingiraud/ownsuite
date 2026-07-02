#compdef suite
# zsh completion for the `suite` CLI.
# Enable it by sourcing this file from ~/.zshrc:
#     source /path/to/ownsuite/completions/suite.zsh
#
# ponytail: hand-maintained — keep the command/flag lists in sync with
# suite/cli.py (tests/test_completion.py guards the subcommand list).
_suite() {
    local -a commands common
    commands=(
        'deps:Install Python tooling + Ansible collections'
        'bootstrap:Provision a bare server into a single-node K3s cluster'
        'check:Dry-run the bootstrap (--check --diff)'
        'install:Guided install: bare server + domain -> HTTPS'
        'provision:Provision infra with Terraform (server + S3)'
        'dns:Print DNS records + write the BIND zone file'
        'user:Manage Keycloak users (one identity, all apps)'
        'status:Show a health summary'
        'upgrade:Apply pending chart/image upgrades (backup-gated)'
        'sync:Apply ONE release/app with the upgrade rails'
        'restore:Restore a CLEAN cluster from off-site backups'
    )
    common=(--env-file --ssh --no-tunnel)

    if (( CURRENT == 2 )); then
        _describe 'suite command' commands
        return
    fi

    case "${words[2]}" in
        user)
            if (( CURRENT == 3 )); then
                _values 'action' add passwd disable
            else
                _values 'flag' $common --local-port --password --permanent --first-name --last-name
            fi
            ;;
        install)
            _values 'flag' $common --domain --public-ip --tls-mode --non-interactive \
                --skip-provision --skip-bootstrap --skip-dns --skip-propagation \
                --provider --force-tfvars --yes ;;
        provision) _values 'flag' --env-file --provider --force-tfvars --yes ;;
        dns)       _values 'flag' $common --domain --public-ip --out ;;
        sync)      _values 'flag' $common --app --selector --no-snapshot --yes ;;
        upgrade|restore) _values 'flag' $common --yes ;;
        status)    _values 'flag' $common ;;
    esac
}
compdef _suite suite
