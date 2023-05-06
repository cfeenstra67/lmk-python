import asyncio
import io
import json
import logging
import os
import signal
import sys

import aiohttp

from lmk.utils import wait_for_socket, shutdown_process, socket_exists


LOGGER = logging.getLogger(__name__)


async def wait_for_job(socket_path: str) -> int:
    connector = aiohttp.UnixConnector(path=socket_path)
    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            async with session.ws_connect("http://daemon/wait", timeout=.5) as ws:
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        response = json.loads(message.data)
                        return response["exit_code"]
                    elif message.type == aiohttp.WSMsgType.CLOSE:
                        break
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        break



class ProcessAttachment:

    def __init__(self, process: asyncio.subprocess.Process, job_dir: str):
        self.process = process
        self.job_dir = job_dir
        self.job_id = os.path.split(job_dir)[-1]
        self.socket_path = os.path.join(job_dir, "daemon.sock")
        self.result_path = os.path.join(self.job_dir, "result.json")
    
    def pause(self) -> None:
        self.process.send_signal(signal.SIGSTOP)
    
    def resume(self) -> None:
        self.process.send_signal(signal.SIGCONT)
    
    async def stop(self) -> None:
        await shutdown_process(self.process, 1, 1)
    
    async def wait(self) -> int:
        if socket_exists(self.socket_path):
            exit_code = await wait_for_job(self.socket_path)
        elif os.path.isfile(self.result_path):
            with open(self.result_path) as f:
                result = json.load(f)
                exit_code = result["exit_code"]
        else:
            raise RuntimeError(f"Job {self.job_id} exited unexpectedly, unable to retrieve result")

        LOGGER.info("Job %s exited with code %d", self.job_id, exit_code)
        await self.stop()
        return exit_code


async def attach(
    job_dir: str,
    stdout_stream: io.BytesIO = sys.stdout,
    stderr_stream: io.BytesIO = sys.stderr,
) -> ProcessAttachment:
    log_file = os.path.join(job_dir, "output.log")
    socket_path = os.path.join(job_dir, "daemon.sock")

    await wait_for_socket(socket_path, 3)

    tail = await asyncio.create_subprocess_exec(
        "tail", "-f", log_file,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=stdout_stream,
        stderr=stderr_stream,
        bufsize=0,
        start_new_session=True
    )

    return ProcessAttachment(tail, job_dir)


async def attach_simple(
    job_dir: str,
    stdout_stream: io.BytesIO = sys.stdout,
    stderr_stream: io.BytesIO = sys.stderr,
) -> int:
    attachment = await attach(job_dir, stdout_stream, stderr_stream)
    try:
        return await attachment.wait()
    except:
        await attachment.stop()
        raise
