import asyncio
import io
import os
import pty
from typing import List

from lmk.processmon.monitor import ProcessMonitor, MonitoredProcess


async def wait_for_fd(fd: int) -> None:
    loop = asyncio.get_running_loop()
    future = asyncio.Future()
    loop.add_reader(fd, future.set_result, None)
    future.add_done_callback(lambda f: loop.remove_reader(fd))
    await future


class MonitoredChildProcess(MonitoredProcess):
    
    def __init__(
        self,
        process: asyncio.subprocess.Process,
        output_fd: int,
        output_file: io.BytesIO,
    ) -> None:
        self.process = process
        self.output_fd = output_fd
        self.output_file = output_file

    @property
    def pid(self) -> int:
        return self.process.pid
    
    async def send_signal(self, signum: int) -> None:
        self.process.send_signal(signum)

    async def wait(self) -> int:
        output_ready = asyncio.create_task(wait_for_fd(self.output_fd))
        wait = asyncio.create_task(self.process.wait())

        while not wait.done():
            await asyncio.wait([output_ready, wait], return_when=asyncio.FIRST_COMPLETED)

            if output_ready.done():
                output = os.read(self.output_fd, 1000)
                self.output_file.write(output)
                output_ready = asyncio.create_task(wait_for_fd(self.output_fd))
        
        output_ready.cancel()

        return wait.result()


class ChildMonitor(ProcessMonitor):
    """
    """
    def __init__(self, argv: List[str]) -> None:
        if len(argv) < 1:
            raise ValueError("argv must have length >=1")
        self.argv = argv

    async def attach(self, pid: int, output_file: io.BytesIO) -> MonitoredChildProcess:
        read_output, write_output = pty.openpty()

        proc = await asyncio.create_subprocess_exec(
            *self.argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=write_output,
            stderr=write_output,
            bufsize=0,
            start_new_session=True
        )
        return MonitoredChildProcess(proc, read_output, output_file)
