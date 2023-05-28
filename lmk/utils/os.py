import contextlib
import os
import signal
import stat
from typing import Callable, ContextManager, List


def socket_exists(path: str) -> bool:
    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISSOCK(mode)


@contextlib.contextmanager
def signal_handler_ctx(
    signals: List[int],
    handler: Callable[[int], None],
) -> ContextManager[None]:
    def handle_signal(signum, _):
        handler(signum)

    prev_handlers = {}
    for signal_num in signals:
        prev_handlers[signal_num] = signal.signal(signal_num, handle_signal)

    try:
        yield
    finally:
        for signal_num, old_handler in prev_handlers.items():
            signal.signal(signal_num, old_handler)
