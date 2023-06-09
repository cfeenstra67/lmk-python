import asyncio
import io
import json
import logging
import os
from typing import List

from lmk.utils.asyncio import check_output
from lmk.process.monitor import ProcessMonitor, MonitoredProcess


LOGGER = logging.getLogger(__name__)

CURRENT_DIR = os.path.dirname(__file__)

MONITOR_SCRIPT_PATH = os.path.join(CURRENT_DIR, "lldb_monitor_script.py")


async def run_with_lldb(
    argv: List[str], log_file: io.BytesIO
) -> asyncio.subprocess.Process:
    """ """
    interpreter_info_str = await check_output(
        ["lldb", "--print-script-interpreter-info"]
    )
    interpreter_info = json.loads(interpreter_info_str)

    pythonpath_components = [interpreter_info["lldb-pythonpath"]]
    if os.getenv("PYTHONPATH"):
        pythonpath_components.append(os.environ["PYTHONPATH"])

    pythonpath = ":".join(pythonpath_components)

    process = await asyncio.create_subprocess_exec(
        interpreter_info["executable"],
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
        stderr=log_file,
        env={**os.environ, "PYTHONPATH": pythonpath},
    )

    return process


class LLDBMonitoredProcess(MonitoredProcess):
    """ """

    def __init__(
        self, process: asyncio.subprocess.Process, pid: int, log_file: io.BytesIO
    ) -> None:
        self.process = process
        self.pid = pid
        self.log_file = log_file

    async def send_signal(self, signum: int) -> None:
        message = json.dumps({"type": "send_signal", "signal": signum}) + "\n"
        self.process.stdin.write(message.encode())

    async def wait(self) -> int:
        try:
            stdout_line = asyncio.create_task(self.process.stdout.readline())
            wait_task = asyncio.create_task(self.process.wait())
            while True:
                await asyncio.wait(
                    [stdout_line, wait_task], return_when=asyncio.FIRST_COMPLETED
                )
                if stdout_line.done():
                    message = json.loads(stdout_line.result())
                    if message.get("type") == "exit":
                        return message["exit_code"]
                    LOGGER.warn(
                        "Unhandled message from monitor process: %s",
                        message.get("type"),
                    )
                    stdout_line = asyncio.create_task(self.process.stdout.readline())

                if wait_task.done():
                    exit_code = wait_task.result()
                    LOGGER.error("Monitor process exited with code: %s", exit_code)
                    return -1
        finally:
            self.log_file.close()


class LLDBProcessMonitor(ProcessMonitor):
    def __init__(self, log_level: str = "ERROR") -> None:
        self.log_level = log_level

    async def attach(
        self, pid: int, output_path: str, log_path: str
    ) -> MonitoredProcess:
        log_file = open(log_path, "ab+", buffering=0)

        with open(output_path, "wb+") as f:
            pass

        process = await run_with_lldb(
            [MONITOR_SCRIPT_PATH, "-l", self.log_level, str(pid), output_path],
            log_file,
        )
        wait_task = asyncio.create_task(process.wait())
        stdout_task = asyncio.create_task(process.stdout.readline())

        await asyncio.wait(
            [wait_task, stdout_task], return_when=asyncio.FIRST_COMPLETED
        )

        if wait_task.done():
            raise RuntimeError(
                "LLDB attach process exited with code %d", wait_task.result()
            )

        stdout_msg = json.loads(await stdout_task)
        if stdout_msg["type"] != "attached":
            process.kill()
            raise RuntimeError(
                "LLDB attach process gave unexpected response: %s", stdout_msg
            )

        LOGGER.info("Process attached")

        return LLDBMonitoredProcess(process, pid, log_file)
