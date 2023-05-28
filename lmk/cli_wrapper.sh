
lmk() {
    set -eo pipefail

    setopt local_options BASH_REMATCH

    CMD=$1
    shift
    
    case $CMD in
        monitor)
            args=""
            SHELL_JOBS=$(jobs -l) python -m lmk.process.shell_jobs $@ | \
            while IFS="" read -r line || [ -n "$line" ]
            do
                if [[ "$line" =~ "JOB (.+)" ]]; then
                    disown %${BASH_REMATCH[2]} &> /dev/null
                elif [[ "$line" =~ "ARGS (.+)" ]]; then
                    args=${BASH_REMATCH[2]}
                else
                    printf '%s\n' "$line"
                fi
            done
            python -m lmk $CMD $args
            ;;
        *)
            python -m lmk $CMD $@
            ;;
    esac
}

# THIS SHOULD BE SOURCED, NOT EXECUTED
# E.g. . <(lmk shell-plugin)
# To add to your shell profile:
# Zshell: echo '. <(lmk shell-plugin)' >> ~/.zshrc
# Bash: echo '. <(lmk shell-plugin)' >> ~/.bashrc
