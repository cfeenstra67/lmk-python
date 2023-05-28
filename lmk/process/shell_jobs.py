import argparse
import dataclasses as dc
import os
import re
import shlex
import sys
from typing import List, Tuple

import click


@dc.dataclass(frozen=True)
class ShellJob:
    command: str
    pid: int
    job_id: int
    state: str


def parse_jobs_output(output: str) -> List[ShellJob]:
    lines = output.strip().split("\n")
    pattern = re.compile(r"\[(\d+)\]\s+[\+\-]?\s+(\d+)\s+(\w+)\s+(.+)$")
    out = []

    for line in lines:
        match = pattern.match(line.strip())
        if not match:
            continue
        job_id = int(match.group(1))
        pid = int(match.group(2))
        state = match.group(3)
        command = match.group(4)
        out.append(ShellJob(command, pid, job_id, state))
    
    return out


def resolve_pid(pid: str) -> Tuple[int, int]:
    if pid.isdigit():
        return int(pid), None

    if not pid.startswith("%"):
        click.secho(f"Invalid pid: {pid}", fg="red", bold=True)
        raise click.Abort

    job_id = int(pid[1:])

    shell_jobs = os.getenv("SHELL_JOBS")
    if shell_jobs is None:
        click.secho(
            "Cannot use bash job syntax without the shell plugin;"
            "install the shell plugin using `lmk shell-plugin >> ~/.zshrc`"
        )
        raise click.Abort
    
    jobs = parse_jobs_output(shell_jobs)
    match = None
    for job in jobs:
        if job.job_id == job_id:
            match = job
            break
    
    if match is None:
        raise RuntimeError(f"No job found with ID {job_id}")
    
    return match.pid, match.job_id


def main(argv: List[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")

    args, others = parser.parse_known_args(argv)

    pid, job_id = resolve_pid(args.job_id)
    if job_id is not None:
        print("JOB", job_id)
    
    print("ARGS", shlex.join([str(pid)] + others))


if __name__ == "__main__":
    main(sys.argv[1:])
