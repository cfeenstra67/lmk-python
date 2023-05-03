import asyncio
from typing import Optional


async def shutdown_loop(loop: asyncio.AbstractEventLoop, timeout: Optional[float] = None) -> bool:
    tasks = asyncio.all_tasks(loop)
    all_done_coro = asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
    if timeout is None:
        await all_done_coro
        return True

    try:
        await asyncio.wait_for(all_done_coro, timeout)
    except TimeoutError:
        return False

    return True
