import asyncio
import contextlib
import logging
import signal
import time
from typing import Optional, Awaitable, Any, AsyncContextManager, List, Callable

from lmk.utils.os import signal_handler_ctx, socket_exists


LOGGER = logging.getLogger(__name__)


async def shutdown_loop(
    loop: asyncio.AbstractEventLoop,
    timeout: Optional[float] = None,
    cancel_running: bool = True,
) -> bool:
    current_task = asyncio.current_task()
    tasks = [
        task for task in asyncio.all_tasks(loop)
        if task is not current_task
    ]

    if not tasks:
        return True

    if cancel_running:
        for task in tasks:
            task.cancel()

    all_done_coro = asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
    if timeout is None:
        await all_done_coro
        return True

    try:
        await asyncio.wait_for(all_done_coro, timeout)
    except TimeoutError:
        return False

    return True


async def shutdown_process(
    process: asyncio.subprocess.Process,
    soft_timeout: Optional[float] = None,
    hard_timeout: Optional[float] = None,
) -> int:
    """
    """
    start = time.time()

    wait = asyncio.shield(process.wait())

    process.send_signal(signal.SIGINT)
    try:
        return await asyncio.wait_for(wait, soft_timeout)
    except (TimeoutError, asyncio.CancelledError):
        pass
    
    after_soft_timeout = time.time()
    hard_timeout_left = None
    if hard_timeout is not None:
        hard_timeout_left = hard_timeout - (after_soft_timeout - start)

    if hard_timeout_left is None or hard_timeout_left > 0:
        process.terminate()
        try:
            return await asyncio.wait_for(wait, hard_timeout_left)
        except (TimeoutError, asyncio.CancelledError):
            pass
    
    process.kill()


def asyncio_create_task(
    coro: Awaitable[Any],
    loop: Optional[asyncio.AbstractEventLoop] = None,
    logger: logging.Logger = LOGGER
) -> asyncio.Task:
    create = asyncio.create_task
    if loop is not None:
        create = loop.create_task

    async def wrapped():
        try:
            await coro
        except Exception:
            logger.exception("Error in %s", coro)
    
    return create(wrapped())


@contextlib.asynccontextmanager
async def async_signal_handler_ctx(
    signals: List[Any],
    handler: Callable[[int], Awaitable[None]],
) -> AsyncContextManager[None]:
    loop = asyncio.get_running_loop()
    tasks = []

    def handle_signal(signum):
        tasks.append(asyncio_create_task(
            handler(signum),
            loop
        ))
    
    with signal_handler_ctx(signals, handle_signal):
        try:
            yield
        finally:
            if tasks:
                await asyncio.wait(tasks)


async def wait_for_socket(
    socket_path: str,
    timeout: Optional[float] = None,
    poll_interval: float = .1,
) -> None:
    start = time.time()

    while (
        not socket_exists(socket_path)
        and (timeout is None or time.time() - start < timeout)
    ):
        await asyncio.sleep(poll_interval)
    
    if not socket_exists(socket_path):
        raise TimeoutError
