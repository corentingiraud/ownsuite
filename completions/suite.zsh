#compdef suite
# zsh completion for the `suite` CLI.
# Enable it by sourcing this file from ~/.zshrc:
#     source /path/to/ownsuite/completions/suite.zsh
#
# ponytail: hand-maintained — keep the command/flag lists in sync with
# suite/cli.py (tests/test_completion.py guards the subcommand list).
_suite() {
    local -a commands apps
    commands=(
        'init:Interactive questionnaire -> writes suite.yaml'
        'plan:Preview what apply would change (read-only)'
        'apply:Reconcile everything to suite.yaml'
        'status:Show a health summary'
        'apps:App catalog: available / enabled / healthy / URL'
        'logs:Show an app'\''s pod logs'
        'info:URLs, admin credentials, DNS records'
        'tunnel:Hold the K8s API tunnel open for ad-hoc kubectl/k9s'
        'upgrade:Apply pending chart/image upgrades (backup-gated)'
        'backup:Take a backup now and wait for completion'
        'restore:Restore a CLEAN cluster from off-site backups'
        'destroy:Uninstall the whole suite (data kept)'
        'user:Manage Keycloak users (one identity, all apps)'
        'deps:Install Python tooling + Ansible collections'
    )
    apps=(docs drive grist projects messages meet tchap)

    if (( CURRENT == 2 )); then
        _describe 'suite command' commands
        return
    fi

    case "${words[2]}" in
        user)
            if (( CURRENT == 3 )); then
                _values 'action' add passwd disable
            else
                _values 'flag' --no-tunnel --local-port --password --permanent --first-name --last-name
            fi
            ;;
        logs)
            if (( CURRENT == 3 )); then
                _values 'app' $apps
            else
                _values 'flag' --no-tunnel --tail
            fi
            ;;
        apply)                   _values 'flag' --no-tunnel --no-snapshot --yes ;;
        upgrade|restore|destroy) _values 'flag' --no-tunnel --yes ;;
        plan|status|apps|backup) _values 'flag' --no-tunnel ;;
    esac
}
compdef _suite suite
