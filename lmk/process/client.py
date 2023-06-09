from typing import Union

import aiohttp


async def send_signal(socket_path: str, signal: Union[str, int]) -> None:
    connector = aiohttp.UnixConnector(path=socket_path)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(
            "http://daemon/signal", json={"signal": signal}
        ) as response:
            if response.status == 200:
                return
            raise ResponseError(response.status, await response.text())


async def set_notify_on(socket_path: str, notify_on: str) -> None:
    connector = aiohttp.UnixConnector(path=socket_path)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(
            "http://daemon/set-notify-on", json={"notify_on": notify_on}
        ) as response:
            if response.status == 200:
                return
            raise ResponseError(response.status, await response.text())


class ResponseError(Exception):
    """ """

    def __init__(self, status: int, data: str) -> None:
        self.status = status
        self.data = data
        super().__init__(f"Request failed with status {status}: {data}")
