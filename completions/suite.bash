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

    local commands="init plan apply status apps logs info tunnel upgrade backup restore destroy user deps"
    local apps="docs drive grist projects messages meet tchap calendars"

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
                COMPREPLY=( $(compgen -W "--no-tunnel --local-port --password --permanent --first-name --last-name" -- "$cur") )
            fi
            ;;
        apply)
            COMPREPLY=( $(compgen -W "--no-tunnel --no-snapshot --yes" -- "$cur") )
            ;;
        logs)
            if [[ $COMP_CWORD -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$apps" -- "$cur") )
            else
                COMPREPLY=( $(compgen -W "--no-tunnel --tail" -- "$cur") )
            fi
            ;;
        upgrade|restore|destroy)
            COMPREPLY=( $(compgen -W "--no-tunnel --yes" -- "$cur") )
            ;;
        plan|status|apps|backup)
            COMPREPLY=( $(compgen -W "--no-tunnel" -- "$cur") )
            ;;
        *)
            COMPREPLY=( $(compgen -W "--help" -- "$cur") )
            ;;
    esac
}
complete -F _suite suite
complete -F _suite "python -m suite" 2>/dev/null
