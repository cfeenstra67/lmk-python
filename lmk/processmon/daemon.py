import asyncio
import contextlib
import logging
import json
import multiprocessing
import os
from datetime import datetime
from typing import Optional

from aiohttp import web

from lmk.instance import get_instance
from lmk.processmon.monitor import ProcessMonitor
from lmk.utils import setup_logging


LOGGER = logging.getLogger(__name__)


class ProcessMonitorDaemon(multiprocessing.Process):
    """
    """
    def __init__(
        self,
        target_pid: int,
        monitor: ProcessMonitor,
        output_dir: str,
        pid_file: str,
        notify_on: str = "none",
        channel_id: Optional[str] = None,
    ) -> None:
        super().__init__(daemon=False)
        self.target_pid = target_pid
        self.monitor = monitor
        self.notify_on = notify_on
        self.channel_id = channel_id
        self.output_dir = output_dir
        self.pid_file = pid_file
        self.started_at = None
    
    def _should_notify(self, exit_code: int) -> bool:
        if self.notify_on == "error":
            return exit_code != 0
        if self.notify_on == "stop":
            return True
        return False

    async def _get_status(self, request: web.Request) -> web.Response:
        return web.json_response({
            "pid": self.target_pid,
            "notify_on": self.notify_on,
            "channel_id": self.channel_id,
            "started_at": self.started_at.isoformat()
        })
    
    async def run_server(self) -> None:
        socket_path = os.path.join(self.output_dir, "daemon.sock")

        app =  web.Application()

        app.add_routes([
            web.get("/status", self._get_status)
        ])

        runner = web.AppRunner(app)
        await runner.setup()

        site = web.UnixSite(runner, socket_path)
        await site.start()

        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await runner.cleanup()
                await site.stop()
                if os.path.exists(socket_path):
                    os.remove(socket_path)

                raise

    async def _run_async(self) -> None:
        stdout_path = os.path.join(self.output_dir, "stdout.log")
        stderr_path = os.path.join(self.output_dir, "stderr.log")

        exit_code = -1
        error = None
        try:
            with contextlib.ExitStack() as stack:
                stdout = stack.enter_context(open(stdout_path, "ab+"))
                stderr = stack.enter_context(open(stderr_path, "ab+"))
                process =  await self.monitor.attach(
                    self.target_pid,
                    stdout,
                    stderr
                )
                self.target_pid = process.pid
                exit_code = await process.wait()
        except Exception as err:
            error = f"{type(err).__name__}: {err}"
            LOGGER.exception("%d: %s monitor raised exception", self.target_pid, type(self.monitor).__name__)
            should_notify = self._should_notify(exit_code)
        else:
            LOGGER.info("%d: exited with code %d", self.target_pid, exit_code)
            should_notify = self._should_notify(exit_code)

        notify_status = "none"
        if not should_notify:
            LOGGER.info("Not sending notification. Current notify on: %s", self.notify_on)
        else:
            LOGGER.info("Sending notification to channel %s. Current notify on: %s", self.channel_id or "default", self.notify_on)
            instance = get_instance()
            try:
                await instance.send_notification(
                    f"Process exited with code **{exit_code}**",
                    notification_channels=[self.channel_id] if self.channel_id else None,
                    async_req=True
                )
                notify_status = "success"
            except Exception:
                LOGGER.exception("Failed to send notification.")
                notify_status = "failed"

        result_path = os.path.join(self.output_dir, "result.json")
        with open(result_path, "w+") as f:
            json.dump({
                "pid": self.target_pid,
                "exit_code": exit_code,
                "error": error,
                "notify_status": notify_status,
                "notify_on": self.notify_on,
                "channel_id": self.channel_id
            }, f)
    
    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        tasks = []
        tasks.append(loop.create_task(self.run_server()))

        LOGGER.info("Running main process")
        try:
            loop.run_until_complete(self._run_async())
        finally:
            for task in reversed(tasks):
                with contextlib.suppress(asyncio.CancelledError):
                    task.cancel()
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
    
    @contextlib.contextmanager
    def pid_ctx(self):
        with open(self.pid_file, "w+") as f:
            f.write(str(self.pid))
        try:
            yield
        finally:
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)

    def run(self) -> None:
        # Double fork so the process continues to run
        if os.fork() != 0:
            return
        self.started_at = datetime.utcnow()
        
        log_path = os.path.join(self.output_dir, "lmk.log")
        setup_logging(log_file=log_path)

        with self.pid_ctx():
            self._run()
