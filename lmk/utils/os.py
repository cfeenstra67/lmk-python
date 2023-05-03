import os
import stat


def socket_exists(path: str) -> bool:
    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISSOCK(mode)
