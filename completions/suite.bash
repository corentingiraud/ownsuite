# bash completion for the `suite` CLI.
# Enable it by sourcing this file from ~/.bashrc:
#     source /path/to/ownsuite/completions/suite.bash
#
# ponytail: hand-maintained — keep the command/flag lists in sync with
# suite/cli.py (tests/test_completion.py guards the subcommand list).
_suite() {
    local cur prev words cword
    _init_completion 2>/dev/null || {
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev="${COMP_WORDS[COMP_CWORD-1]}"
    }

    local commands="deps bootstrap check install provision dns user status upgrade sync restore"
    local common="--env-file --ssh --no-tunnel"

    # Top-level command.
    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "$commands --help" -- "$cur") )
        return
    fi

    local cmd="${COMP_WORDS[1]}"
    case "$cmd" in
        user)
            if [[ $COMP_CWORD -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "add passwd disable" -- "$cur") )
            else
                COMPREPLY=( $(compgen -W "$common --local-port --password --permanent --first-name --last-name" -- "$cur") )
            fi
            ;;
        install)
            COMPREPLY=( $(compgen -W "$common --domain --public-ip --tls-mode --non-interactive --skip-provision --skip-bootstrap --skip-dns --skip-propagation --provider --force-tfvars --yes" -- "$cur") )
            ;;
        provision)
            COMPREPLY=( $(compgen -W "--env-file --provider --force-tfvars --yes" -- "$cur") )
            ;;
        dns)
            COMPREPLY=( $(compgen -W "$common --domain --public-ip --out" -- "$cur") )
            ;;
        sync)
            COMPREPLY=( $(compgen -W "$common --app --selector --no-snapshot --yes" -- "$cur") )
            ;;
        upgrade|restore)
            COMPREPLY=( $(compgen -W "$common --yes" -- "$cur") )
            ;;
        status)
            COMPREPLY=( $(compgen -W "$common" -- "$cur") )
            ;;
        *)
            COMPREPLY=( $(compgen -W "--help" -- "$cur") )
            ;;
    esac
}
complete -F _suite suite
complete -F _suite "python -m suite" 2>/dev/null
