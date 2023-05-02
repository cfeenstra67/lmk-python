import asyncio
import io
from typing import List

from lmk.processmon.monitor import ProcessMonitor, MonitoredProcess


class MonitoredChildProcess(MonitoredProcess):
    
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
    
    @property
    def pid(self) -> int:
        return self.process.pid

    async def wait(self) -> int:
        return await self.process.wait()


class ChildMonitor(ProcessMonitor):
    """
    """
    def __init__(self, argv: List[str]) -> None:
        if len(argv) < 1:
            raise ValueError("argv must have length >=1")
        self.argv = argv

    async def attach(self, pid: int, stdout: io.BytesIO, stderr: io.BytesIO) -> MonitoredChildProcess:
        proc = await asyncio.create_subprocess_exec(
            *self.argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr
        )
        return MonitoredChildProcess(proc)
