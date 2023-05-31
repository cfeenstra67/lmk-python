
lmk() {
    setopt local_options BASH_REMATCH

    declare -a lines

    SHELL_JOBS=$(jobs -l) python -m lmk.shell_cli $@ | while IFS= read -r line || [[ -n $line ]]; do
        lines+=("$line")
    done

    for line in ${lines[@]}; do
        if [[ "$line" =~ "DISOWN (.+)" ]]; then
            job_id="%${BASH_REMATCH[2]}"
            disown $job_id &> /dev/null
        elif [[ "$line" =~ "CMD (.+)" ]]; then
            eval "python -m lmk ${BASH_REMATCH[2]}" || return $?
        fi
    done
}
