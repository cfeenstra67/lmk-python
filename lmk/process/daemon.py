import asyncio
import contextlib
import logging
import json
import multiprocessing
import os
import shlex
import signal
import socket
from datetime import datetime
from functools import wraps
from typing import Optional, Callable, List

import aiohttp
from aiohttp import web

from lmk.generated.models.session_response import SessionResponse
from lmk.instance import get_instance
from lmk.process.monitor import ProcessMonitor, MonitoredProcess
from lmk.utils import setup_logging, socket_exists


LOGGER = logging.getLogger(__name__)


def route_handler(func: Callable) -> Callable:
    """ """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception:
            LOGGER.exception("Error running route handler")
            return web.json_response({"message": "Internal server error"}, status=500)

    return wrapper


@contextlib.contextmanager
def pid_ctx(pid_file: str, pid: int):
    with open(pid_file, "w+") as f:
        f.write(str(pid))
    try:
        yield
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)


class ProcessMonitorController:
    """ """

    def __init__(
        self,
        job_name: str,
        target_pid: int,
        monitor: ProcessMonitor,
        output_dir: str,
        notify_on: str = "none",
        channel_id: Optional[str] = None,
    ) -> None:
        self.job_name = job_name
        self.target_pid = target_pid
        self.monitor = monitor
        self.notify_on = notify_on
        self.channel_id = channel_id
        self.output_dir = output_dir

        self.done_event = asyncio.Event()
        self.attached_event = asyncio.Event()
        self.update_event = asyncio.Event()
        self.error: Optional[Exception] = None
        self.started_at: Optional[datetime] = None
        self.exit_code: Optional[int] = None
        self.session: Optional[SessionResponse] = None
        self.target_command: Optional[List[str]] = None
        self.process: Optional[MonitoredProcess] = None

    def _should_notify(self, exit_code: int) -> bool:
        if self.notify_on == "error":
            return exit_code != 0
        if self.notify_on == "stop":
            return True
        return False

    @route_handler
    async def _wait_websocket(self, request: web.Request) -> web.Response:
        wait_for = request.query.get("wait_for") or "run"
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        attached_set = self.attached_event.is_set()
        if not attached_set:
            await self.attached_event.wait()

            if self.error is not None:
                await ws.send_json({
                    "ok": False,
                    "stage": "attach",
                    "error_type": type(self.error).__name__,
                    "error": str(self.error)
                })
                await ws.close()
                return ws

        if wait_for == "attach":
            await ws.send_json({
                "ok": True,
                "stage": "attach"
            })
            await ws.close()
            return ws

        await self.done_event.wait()

        if self.error is not None:
            await ws.send_json({
                "ok": False,
                "stage": "run",
                "error_type": type(self.error).__name__,
                "error": str(self.error)
            })
            await ws.close()
            return ws

        await ws.send_json({
            "ok": True,
            "stage": "run",
            "exit_code": self.exit_code
        })
        await ws.close()
        return ws

    @route_handler
    async def _get_status(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "job_name": self.job_name,
                "pid": self.target_pid,
                "command": self.target_command,
                "notify_on": self.notify_on,
                "channel_id": self.channel_id,
                "started_at": self.started_at.isoformat(),
            }
        )

    @route_handler
    async def _send_signal(self, request: web.Request) -> web.Response:
        body = await request.json()
        signum = body["signal"]
        if isinstance(signum, str):
            signum = getattr(signal.Signals, signum).value

        await self.send_signal(signum)

        return web.json_response({"ok": True})

    @route_handler
    async def _set_notify_on(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.notify_on = body["notify_on"]
        self.update_event.set()

        return web.json_response({"ok": True})

    @contextlib.asynccontextmanager
    async def _session_ctx(self) -> None:
        instance = get_instance()
        self.session = await instance.create_session(
            self.job_name,
            "process",
            {
                "hostname": socket.gethostname(),
                "command": shlex.join(self.target_command),
                "pid": self.target_pid,
                "notifyOn": self.notify_on,
                "notifyChannel": self.channel_id,
            },
            async_req=True
        )
        async with instance.session_connect(self.session.session_id, False) as ws:
            async def handle_updates():
                while not self.done_event.is_set():
                    update_task = asyncio.create_task(self.update_event.wait())
                    done_task = asyncio.create_task(self.done_event.wait())
                    await asyncio.wait([update_task, done_task], return_when=asyncio.FIRST_COMPLETED)

                    if update_task.done():
                        self.update_event.clear()
                        await ws.send_json({
                            "notifyOn": self.notify_on,
                            "notifyChannel": self.channel_id,
                        })

                    if done_task.done():
                        await ws.send_json({
                            "notifyOn": self.notify_on,
                            "notifyChannel": self.channel_id,
                            "exitCode": self.exit_code
                        })
                        await ws.close()

            async def handle_messages():
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        response = json.loads(message.data)
                        if not response["ok"]:
                            LOGGER.error("Error in websocket: %s", response)
                            continue
                        msg_type = response["message"]["type"]
                        if msg_type == "update":
                            self.notify_on = response["message"]["session"]["state"]["notifyOn"]
                            self.channel_id = response["message"]["session"]["state"].get("notifyChannel")
                        elif msg_type == "action":
                            LOGGER.info("Action: %s", response)
                        else:
                            LOGGER.warn("Unhandled ws message type: %s", msg_type)
                    elif message.type == aiohttp.WSMsgType.CLOSE:
                        break
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        LOGGER.error("Web socket error: %s", message.data)
                        break

            updates_task = asyncio.create_task(handle_updates())
            messages_task = asyncio.create_task(handle_messages())
            try:
                yield
            finally:
                await asyncio.wait([updates_task, messages_task])
                await instance.end_session(
                    self.session.session_id,
                    async_req=True
                )

                updates_task.result()
                messages_task.result()


    async def _run_server(self) -> None:
        socket_path = os.path.join(self.output_dir, "daemon.sock")

        app = web.Application()

        app.add_routes(
            [
                web.get("/status", self._get_status),
                web.get("/wait", self._wait_websocket),
                web.post("/signal", self._send_signal),
                web.post("/set-notify-on", self._set_notify_on),
            ]
        )

        runner = web.AppRunner(app)
        await runner.setup()

        site = web.UnixSite(runner, socket_path)
        await site.start()

        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await runner.cleanup()
                if socket_exists(socket_path):
                    os.remove(socket_path)
                raise

    async def _run_command(self, log_path: str) -> None:
        async with contextlib.AsyncExitStack() as stack:
            output_path = os.path.join(self.output_dir, "output.log")

            exit_code = -1
            error_type, error = None, None
            try:
                # Create the output file
                with open(output_path, "wb+") as f:
                    pass

                self.process = await self.monitor.attach(
                    self.target_pid, output_path, log_path
                )
                self.target_pid = self.process.pid
                self.target_command = self.process.command
                self.attached_event.set()

                await stack.enter_async_context(self._session_ctx())

                exit_code = await self.process.wait()
            except Exception as err:
                self.error = err
                if not self.attached_event.is_set():
                    self.attached_event.set()

                error_type = type(err).__name__
                error = str(err)
                LOGGER.exception(
                    "%d: %s monitor raised exception",
                    self.target_pid,
                    type(self.monitor).__name__,
                )
                should_notify = self._should_notify(exit_code)
            else:
                LOGGER.info("%d: exited with code %d", self.target_pid, exit_code)
                should_notify = self._should_notify(exit_code)

            ended_at = datetime.utcnow()
            self.exit_code = exit_code
            self.process = None
            self.done_event.set()

            notify_status = "none"
            if not should_notify:
                LOGGER.info(
                    "Not sending notification. Current notify on: %s", self.notify_on
                )
            else:
                LOGGER.info(
                    "Sending notification to channel %s. Current notify on: %s",
                    self.channel_id or "default",
                    self.notify_on,
                )
                instance = get_instance()
                try:
                    await instance.send_notification(
                        f"Process exited with code **{exit_code}**",
                        notification_channels=[self.channel_id]
                        if self.channel_id
                        else None,
                        async_req=True,
                    )
                    notify_status = "success"
                except Exception:
                    LOGGER.exception(
                        "Failed to send notification to channel %s.",
                        self.channel_id
                    )
                    notify_status = "failed"

            result_path = os.path.join(self.output_dir, "result.json")
            with open(result_path, "w+") as f:
                json.dump(
                    {
                        "job_name": self.job_name,
                        "pid": self.target_pid,
                        "command": self.target_command,
                        "exit_code": exit_code,
                        "error_type": error_type,
                        "error": error,
                        "notify_status": notify_status,
                        "notify_on": self.notify_on,
                        "channel_id": self.channel_id,
                        "started_at": self.started_at.isoformat(),
                        "ended_at": ended_at.isoformat(),
                    },
                    f,
                )

    async def send_signal(self, signum: int) -> None:
        if self.process is None:
            raise ProcessNotAttached
        await self.process.send_signal(signum)

    async def run(self, log_path: str) -> None:
        self.started_at = datetime.utcnow()

        tasks = []
        tasks.append(asyncio.create_task(self._run_server()))

        LOGGER.info("Running main process")
        try:
            await self._run_command(log_path)
        except Exception:
            LOGGER.exception("Error running command")
            raise
        finally:
            for task in reversed(tasks):
                task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait(tasks)


class ProcessMonitorDaemon(multiprocessing.Process):
    """ """

    def __init__(
        self,
        controller: ProcessMonitorController,
        pid_file: str,
    ) -> None:
        super().__init__(daemon=False)
        self.controller = controller
        self.pid_file = pid_file

    def run(self) -> None:
        # Double fork so the process continues to run
        if os.fork() != 0:
            return

        # Detach this process from the parent so we don't share
        # signals
        os.setsid()

        log_path = os.path.join(self.controller.output_dir, "lmk.log")
        setup_logging(log_file=log_path)

        with pid_ctx(self.pid_file, self.pid):
            loop = asyncio.new_event_loop()

            try:
                loop.run_until_complete(self.controller.run(log_path))
            finally:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()


class ProcessNotAttached(Exception):
    """ """
