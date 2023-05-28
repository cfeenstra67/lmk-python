import asyncio
import contextlib
import logging
import json
import multiprocessing
import os
import signal
from datetime import datetime
from functools import wraps
from typing import Optional, Callable

from aiohttp import web

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
        target_pid: int,
        monitor: ProcessMonitor,
        output_dir: str,
        notify_on: str = "none",
        channel_id: Optional[str] = None,
    ) -> None:
        self.target_pid = target_pid
        self.monitor = monitor
        self.notify_on = notify_on
        self.channel_id = channel_id
        self.output_dir = output_dir

        self.done_event = asyncio.Event()
        self.started_at: Optional[datetime] = None
        self.exit_code: Optional[int] = None
        self.process: Optional[MonitoredProcess] = None

    def _should_notify(self, exit_code: int) -> bool:
        if self.notify_on == "error":
            return exit_code != 0
        if self.notify_on == "stop":
            return True
        return False

    @route_handler
    async def _wait_websocket(self, request: web.Request) -> web.Response:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await self.done_event.wait()
        await ws.send_json({"exit_code": self.exit_code})
        await ws.close()
        return ws

    @route_handler
    async def _get_status(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "pid": self.target_pid,
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

        return web.json_response({"ok": True})

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
        output_path = os.path.join(self.output_dir, "output.log")

        exit_code = -1
        error = None
        try:
            self.process = await self.monitor.attach(self.target_pid, output_path, log_path)
            self.target_pid = self.process.pid
            exit_code = await self.process.wait()
        except Exception as err:
            error = f"{type(err).__name__}: {err}"
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
                LOGGER.exception("Failed to send notification.")
                notify_status = "failed"

        result_path = os.path.join(self.output_dir, "result.json")
        with open(result_path, "w+") as f:
            json.dump(
                {
                    "pid": self.target_pid,
                    "exit_code": exit_code,
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
