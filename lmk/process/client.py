import json
from typing import Union, Any

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


async def wait_for_job(socket_path: str, wait_for: str = "run") -> Any:
    connector = aiohttp.UnixConnector(path=socket_path)
    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            async with session.ws_connect(
                f"http://daemon/wait?wait_for={wait_for}",
                timeout=0.5
            ) as ws:
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        response = json.loads(message.data)
                        if not response["ok"]:
                            raise Exception(f"{response['error_type']}: {response['error']}")
                        return response
                    elif message.type == aiohttp.WSMsgType.CLOSE:
                        break
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        break


class ResponseError(Exception):
    """ """

    def __init__(self, status: int, data: str) -> None:
        self.status = status
        self.data = data
        super().__init__(f"Request failed with status {status}: {data}")
