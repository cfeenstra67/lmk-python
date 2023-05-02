import asyncio
import contextlib
import io
import signal
import tempfile
import textwrap
from typing import AsyncContextManager


def gdb_remap_script(path: str, mode: int, descriptor: int) -> str:
    return textwrap.dedent(f"""
    set $fd=open("{path}", {mode})
    set $xd=dup({descriptor})
    call dup2($fd, {descriptor})
    call close($fd)
    call close($xd)
    """)


def gdb_monitor_script(
    pid: int,
    stdout_path: str,
    stderr_path: str
) -> str:
    parts = [f"attach {pid}"]
    parts.append(gdb_remap_script(stdout_path, 0o600, 1))
    parts.append(gdb_remap_script(stderr_path, 0o600, 2))
    return "\n".join(parts)


async def graceful_shutdown(
    proc: asyncio.subprocess.Process,
    soft_timeout: float,
    hard_timeout: float,
) -> int:
    wait_coro = asyncio.shield(proc.wait())
    # Is the process already finished?
    try:
        return await asyncio.wait_for(wait_coro, 0)
    except TimeoutError:
        pass
    
    # Send SIGINT, wait for soft_timeout
    proc.send_signal(signal.SIGINT)
    try:
        return await asyncio.wait_for(wait_coro, soft_timeout)
    except TimeoutError:
        pass

    # Send SIGTERM, wait for hard_timeout
    proc.terminate()
    try:
        return await asyncio.wait_for(wait_coro, hard_timeout)
    except TimeoutError:
        pass
    
    # Send SIGKILL, wait until process exits
    proc.kill()
    return await wait_coro


@contextlib.asynccontextmanager
async def gdb_monitor_process(
    pid: int,
    stdout_path: str,
    stderr_path: str,
) -> AsyncContextManager[asyncio.subprocess.Process]:
    input_script = gdb_monitor_script(pid, stdout_path, stderr_path)
    with tempfile.NamedTemporaryFile(mode="w+") as input_file:
        input_file.write(input_script)
        input_file.flush()
        input_file.seek(0)

        proc = await asyncio.create_subprocess_exec(
            "gdb", "-batch", "-n", "-x", "/dev/stdin",
            stdin=input_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            yield proc
        finally:
            await graceful_shutdown(proc, .2, .5)
