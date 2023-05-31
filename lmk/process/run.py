import asyncio
import os
import signal

from lmk.process.attach import attach_simple
from lmk.process.daemon import ProcessMonitorController, ProcessMonitorDaemon, pid_ctx
from lmk.process.manager import NewJob
from lmk.utils.asyncio import asyncio_create_task, async_signal_handler_ctx


async def run_foreground(
    job: NewJob, controller: ProcessMonitorController, attach: bool = True
) -> None:
    with pid_ctx(job.pid_file, os.getpid()):
        log_path = os.path.join(job.job_dir, "lmk.log")
        tasks = []
        tasks.append(asyncio_create_task(controller.run(log_path)))
        if attach:
            tasks.append(asyncio_create_task(attach_simple(job.job_dir)))

        async with async_signal_handler_ctx(
            [signal.SIGINT, signal.SIGTERM],
            lambda signum: controller.send_signal(signum),
        ):
            await asyncio.wait(tasks)


def run_daemon(job: NewJob, controller: ProcessMonitorController) -> None:
    process = ProcessMonitorDaemon(controller, job.pid_file)
    process.start()
