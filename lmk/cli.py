import click
import os
import signal as signal_module
import sys
from typing import List, Optional

from lmk.instance import get_instance
from lmk.process.attach import attach_interactive
from lmk.process.child_monitor import ChildMonitor
from lmk.process.client import send_signal
from lmk.process.daemon import ProcessMonitorController
from lmk.process.lldb_monitor import LLDBProcessMonitor
from lmk.process.manager import JobManager
from lmk.process.run import run_foreground, run_daemon
from lmk.process.shell_jobs import resolve_pid
from lmk.utils.click import async_command
from lmk.utils.logging import setup_logging


PROJECT_DIR = os.path.dirname(__file__)


@click.group()
@click.option("-l", "--log-level", default="WARN", help="Log level")
@click.option("-b", "--base-path", default=os.path.expanduser("~/.lmk"))
@click.pass_context
def cli(ctx: click.Context, log_level: str, base_path: str):
    setup_logging(level=log_level)
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level
    ctx.obj["manager"] = JobManager(base_path)


@cli.command()
@click.option("-f", "--force", is_flag=True, default=False)
def login(force):
    instance = get_instance()
    instance.authenticate(force=force)


attach_option = click.option("--attach/--no-attach", default=True, help="Attach to the process")

name_option = click.option("-N", "--name", default=None)

notify_on_option = click.option("-n", "--notify", default="none", type=click.Choice(["stop", "error", "none"]))


@async_command(cli)
@click.option("--daemon/--no-daemon", default=True, help="Daemonize the process")
@attach_option
@name_option
@notify_on_option
@click.argument("command", nargs=-1)
@click.pass_context
async def run(ctx: click.Context, daemon: bool, command: List[str], attach: bool, name: Optional[str], notify: str):
    if name is None and command:
        name = command[0]

    manager = ctx.obj["manager"]
    job = manager.create_job(name)
    click.secho(f"Job ID: {job.job_id}", fg="green", bold=True)

    monitor = ChildMonitor(command)
    controller = ProcessMonitorController(
        -1,
        monitor,
        job.job_dir,
        notify
    )

    if daemon:
        run_daemon(job, controller)
        if attach:
            await attach_interactive(job.job_dir)
            return

    await run_foreground(job, controller, attach)


@async_command(cli)
@click.argument("pid")
@attach_option
@name_option
@notify_on_option
@click.pass_context
async def monitor(ctx: click.Context, pid: str, attach: bool, name: Optional[str], notify: str):
    manager = ctx.obj["manager"]
    job = manager.create_job(name)
    click.secho(f"Job ID: {job.job_id}", fg="green", bold=True)

    monitor = LLDBProcessMonitor(ctx.obj["log_level"])
    pid, _ = resolve_pid(pid)

    controller = ProcessMonitorController(
        pid,
        monitor,
        job.job_dir,
        notify
    )

    run_daemon(job, controller)

    if attach:
        exit_code = await attach_interactive(job.job_dir)
        sys.exit(exit_code)


@async_command(cli)
@click.argument("job_id")
@click.pass_context
async def attach(ctx: click.Context, job_id: str):
    manager = ctx.obj["manager"]
    job = await manager.get_job(job_id)

    await attach_interactive(job.job_dir)


def pad(value: str, length: int, character: str = " ") -> str:
    if len(value) > length:
        return value[:length - 3] + "..."
    return value + character * (length - len(value))


@async_command(cli)
@click.option("-a", "--all", is_flag=True, help="List all jobs")
@click.pass_context
async def jobs(ctx: click.Context, all: bool):
    manager = ctx.obj["manager"]
    if all:
        job_ids = manager.get_all_job_ids()
        jobs = manager.get_jobs(job_ids)
    else:
        jobs = manager.list_running_jobs()

    print(
        pad("id", 30),
        pad("pid", 10),
        pad("status", 12),
        pad("notify", 10),
        pad("started", 30),
    )
    async for job in jobs:
        print(
            pad(str(job.job_id), 30),
            pad(str(job.target_pid), 10),
            pad("running    " if job.running else "not-running", 12),
            pad(job.notify_on, 10),
            pad(job.started_at.isoformat(), 30),
        )


@async_command(cli)
@click.argument("job_id")
@click.option("-s", "--signal", default="SIGINT", help="Signal to send")
@click.pass_context
async def kill(ctx: click.Context, job_id: str, signal: str):
    manager = ctx.obj["manager"]
    job = await manager.get_job(job_id)

    if signal.isdigit():
        signal = int(signal)
    else:
        signal = getattr(signal_module, signal.upper())

    socket_path = os.path.join(job.job_dir, "daemon.sock")
    await send_signal(socket_path, signal)


@cli.command()
def shell_plugin() -> None:
    script_path = os.path.join(PROJECT_DIR, "cli_wrapper.sh")
    with open(script_path) as f:
        click.echo(f.read())
