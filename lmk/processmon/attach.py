import asyncio
import io
import json
import logging
import os
import sys

import aiohttp


LOGGER = logging.getLogger(__name__)


async def wait_for_job(job_dir: str) -> int:
    socket_path = os.path.join(job_dir, "daemon.sock")
    connector = aiohttp.UnixConnector(path=socket_path)
    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            async with session.ws_connect("http://daemon/wait") as ws:
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        response = json.loads(message.data)
                        return response["exit_code"]
                    elif message.type == aiohttp.WSMsgType.CLOSE:
                        break
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        break


async def attach(
    job_dir: str,
    stdout_stream: io.BytesIO = sys.stdout,
    stderr_stream: io.BytesIO = sys.stderr,
) -> None:
    _, job_id = os.path.split(job_dir)
    log_file = os.path.join(job_dir, "output.log")

    tail = await asyncio.create_subprocess_exec(
        "tail", "-f", log_file,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=stdout_stream,
        stderr=stderr_stream,
        bufsize=0,
    )

    exit_code = await wait_for_job(job_dir)
    LOGGER.info("Job %s exited with code %s", job_id, exit_code)
    tail.terminate()

    await tail.wait()
