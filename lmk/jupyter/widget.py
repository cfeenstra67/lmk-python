import asyncio
import atexit
import contextlib
import enum
import logging
import io
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Union

from ipywidgets import DOMWidget
from traitlets import Unicode, Int, List, Dict, UseEnum

from lmk import exc
from lmk.generated.api.app_api import AppApi
from lmk.generated.exceptions import ApiException
from lmk.instance import (
    Instance,
    default_instance_changed,
    default_channel_changed,
    access_token_changed,
    get_instance,
)
from lmk.jupyter.constants import MODULE_NAME, MODULE_VERSION
from lmk.jupyter.history import (
    IPythonHistory,
    jupyter_cell_state_changed,
    jupyter_state_changed,
    IPythonShellState,
)
from lmk.jupyter.notebook_info import NotebookInfoWatcher, notebook_name_changed
from lmk.jupyter.utils import background_ctx


def truncate_stream(stream: io.StringIO, max_size: int) -> None:
    value = stream.getvalue()
    if len(value) <= max_size:
        return
    new_size = int(max_size * 0.8)
    stream.truncate(0)
    stream.seek(0)
    stream.write(value[-new_size:])


def ts_millis() -> int:
    return int(datetime.now().timestamp() * 1000)


class LMKWidgetState(str, enum.Enum):
    NeedsAuth = "needs-auth"
    AuthInProgress = "auth-in-progress"
    AuthError = "auth-error"
    Authenticated = "authenticated"


class LMKChannelsState(str, enum.Enum):
    None_ = "none"
    Loading = "loading"
    Forbidden = "forbidden"
    Loaded = "loaded"
    Error = "error"


class IPythonCellStateType(str, enum.Enum):
    None_ = "none"
    Running = "running"
    Error = "error"
    Success = "success"
    Cancelled = "cancelled"


class IPythonMonitoringState(str, enum.Enum):
    None_ = "none"
    Error = "error"
    Stop = "stop"


class LMKWidget(DOMWidget):
    _model_name = Unicode("LMKModel").tag(sync=True)
    _model_module = Unicode(MODULE_NAME).tag(sync=True)
    _model_module_version = Unicode(MODULE_VERSION).tag(sync=True)
    _view_name = Unicode("LMKView").tag(sync=True)
    _view_module = Unicode(MODULE_NAME).tag(sync=True)
    _view_module_version = Unicode(MODULE_VERSION).tag(sync=True)

    url = Unicode("").tag(sync=True)
    notebook_name = Unicode("").tag(sync=True)
    auth_url = Unicode("").tag(sync=True)
    state = UseEnum(LMKWidgetState, default_value=LMKWidgetState.NeedsAuth).tag(
        sync=True
    )
    auth_error = Unicode("").tag(sync=True)
    jupyter_state = UseEnum(
        IPythonShellState, default_value=IPythonShellState.Idle
    ).tag(sync=True)
    jupyter_execution_num = Int(-1).tag(sync=True)
    jupyter_cell_state = UseEnum(
        IPythonCellStateType, default_value=IPythonCellStateType.None_
    ).tag(sync=True)
    jupyter_cell_started_at = Int(-1).tag(sync=True)
    jupyter_cell_finished_at = Int(-1).tag(sync=True)
    jupyter_cell_error = Unicode("").tag(sync=True)
    monitoring_state = Unicode(IPythonMonitoringState.None_.value).tag(sync=True)
    notify_min_execution = Int(-1).tag(sync=True)
    notify_min_time = Int(-1).tag(sync=True)
    selected_channel = Unicode("default").tag(sync=True)
    channels_state = UseEnum(
        LMKChannelsState, default_value=LMKChannelsState.None_
    ).tag(sync=True)
    channels = List(Dict()).tag(sync=True)
    log_level = Int(logging.INFO).tag(sync=True)
    sent_notifications = List(Dict()).tag(sync=True)

    def __init__(self) -> None:
        super().__init__()
        self.thread = LMKWidgetThread(self)
        self.thread.start()

    def set_monitoring_state(
        self,
        state: Union[IPythonMonitoringState, str],
        immediate: bool = False,
    ) -> None:
        if isinstance(state, str):
            state = IPythonMonitoringState(state)
        if state.value == self.monitoring_state:
            return
        self.monitoring_state = state.value
        min_time = ts_millis()
        min_execution = self.jupyter_execution_num
        if not immediate:
            min_time += 2000
            min_execution += 1

        self.notify_min_execution = min_execution
        self.notify_min_time = min_time

    def set_log_level(self, level: Union[int, str]) -> None:
        if isinstance(level, str):
            level = getattr(logging, level.upper())
        self.log_level = level

    def shutdown(self) -> None:
        self.thread.shutdown()


class LMKWidgetThread(threading.Thread):
    def __init__(self, widget: LMKWidget) -> None:
        super().__init__()
        self.widget = widget
        self.shutdown_event = threading.Event()
        self.stdout = io.StringIO()
        self.logger = self._logger()
        self.history = IPythonHistory(logger=self.logger)
        self.info_watcher = NotebookInfoWatcher(logger=self.logger)
        self._register_shutdown_hook()

    def _logger(self) -> logging.Logger:
        logger = logging.getLogger(__name__ + ":thread")
        handler = logging.StreamHandler(self.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s - %(levelname)s] %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(self.widget.log_level)
        return logger

    def _register_shutdown_hook(self) -> None:
        atexit.register(self.shutdown)

    def shutdown(self) -> None:
        self.shutdown_event.set()
        self.join()

    async def handle_event(self, event):
        if event["name"] == "log_level":
            self.logger.setLevel(event["new"])

    async def initiate_auth(self, payload, instance):
        if self.widget.state == LMKWidgetState.AuthInProgress:
            self.logger.info(f"Skipping auth because it is in progress")
            return

        timeout = 300.0
        poll_interval = 1.0
        start = time.time()

        try:
            self.widget.state = LMKWidgetState.AuthInProgress
            session = await instance.initiate_auth(async_req=True)
            self.widget.auth_url = session.authorize_url

            while time.time() - start < timeout:
                try:
                    response = await instance.retrieve_auth_token(
                        session_id=session.session_id, async_req=True
                    )
                except exc.AuthSessionNotComplete:
                    await asyncio.sleep(poll_interval)
                    continue
                else:
                    instance.set_access_token(
                        response.access_token,
                        response.refresh_token,
                        datetime.now() + timedelta(seconds=response.expires_in),
                    )
                    self.widget.state = LMKWidgetState.Authenticated
                    return

            self.widget.state = LMKWidgetState.AuthError
            self.widget.auth_error = "Authenticated timed out"
        except Exception as err:
            self.widget.state = LMKWidgetState.AuthError
            self.widget.auth_error = f"{type(err).__name__}: {err}"
            raise

    async def refresh_channels(self, payload, instance):
        if self.widget.channels_state == LMKChannelsState.Loading:
            self.logger.info(f"Skipping channel fetch because it is in progress")
            return

        try:
            self.widget.channels_state = LMKChannelsState.Loading
            channels = await instance.list_notification_channels(async_req=True)
            self.widget.channels = [channel.to_dict() for channel in channels]
            selected = "default"
            if channels:
                selected = channels[0].notification_channel_id
            self.widget.selected_channel = selected
            self.widget.channels_state = LMKChannelsState.Loaded
        except ApiException as err:
            if err.status == 403:
                self.widget.channels_state = LMKChannelsState.Forbidden
                self.widget.channels = []
                self.widget.selected_channel = "default"
                return
            self.widget.channels_state = LMKChannelsState.Error
            raise
        except Exception as err:
            self.widget.channels_state = LMKChannelsState.Error
            raise

    async def _handle_request_inner(self, request):
        method = request["method"]
        payload = request["payload"]
        instance = get_instance()
        if method == "initiate-auth":
            return await self.initiate_auth(payload, instance)
        if method == "refresh-channels":
            return await self.refresh_channels(payload, instance)
        raise ValueError(f"Invalid method {method}")

    async def handle_request(self, request):
        try:
            response = await self._handle_request_inner(request)
            return {
                "request_id": request["request_id"],
                "success": True,
                "payload": response,
            }
        except ApiException as err:
            self.logger.error(
                "API Request failed with status %d %s: %s",
                err.status,
                err.reason,
                err.body,
            )
            return {
                "request_id": request["request_id"],
                "success": False,
                "error": str(err),
            }
        except Exception as err:
            self.logger.exception("Error occurred when handling request")
            if not isinstance(request, dict):
                return {
                    "request_id": "<unknown>",
                    "success": False,
                    "error": "Invalid payload",
                }
            return {
                "request_id": request.get("request_id", "<unknown>"),
                "success": False,
                "error": str(err),
            }

    async def _monitor_stream(self) -> None:
        while True:
            truncate_stream(self.stdout, 256 * 1024)
            await asyncio.sleep(5)

    def _handle_done_future(self, future):
        try:
            future.result()
        except Exception:
            self.logger.exception("Error in callback")

    def _observe_widget(self, loop: asyncio.AbstractEventLoop) -> Callable[[], None]:
        def observe(info):
            async def handle():
                with background_ctx(self.logger, type(self).__name__):
                    await self.handle_event(info)

            task = loop.create_task(handle())
            task.add_done_callback(self._handle_done_future)

        self.widget.observe(observe)

        def observe_msg(widget, content, buffers):
            async def handle():
                with background_ctx(self.logger, type(self).__name__):
                    response = await self.handle_request(content)
                    self.widget.send(response)

            task = loop.create_task(handle())
            task.add_done_callback(self._handle_done_future)

        self.widget.on_msg(observe_msg)

        def unobserve():
            self.widget.unobserve(observe)
            self.widget.on_msg(observe_msg, remove=True)

        return unobserve

    async def _send_notification(self) -> None:
        with background_ctx(self.logger, type(self).__name__):
            instance = get_instance()

            kws = {}
            if self.widget.selected_channel != "default":
                kws["notification_channels"] = [self.widget.selected_channel]

            if self.widget.jupyter_cell_state == IPythonCellStateType.Error:
                message = (
                    f"Notebook **{self.widget.notebook_name}** failed during execution "
                    f"**{self.widget.jupyter_execution_num}** with error:\n"
                    f"```\n{self.widget.jupyter_cell_error}\n```"
                    f"\n\n[notebook link]({self.widget.url})"
                )
            else:
                message = (
                    f"Notebook **{self.widget.notebook_name}** stopped after execution "
                    f"{self.widget.jupyter_execution_num}"
                    f"\n\n[notebook link]({self.widget.url})"
                )

            response = await instance.send_notification(
                message=message, async_req=True, **kws
            )
            self.logger.info("Notification sent. Response: %s", response.to_dict())
            self.widget.sent_notifications = (
                self.widget.sent_notifications + [response.to_dict()]
            )[-10:]

    def _observe_jupyter(self, loop: asyncio.AbstractEventLoop) -> Callable[[], None]:
        def handle_jupyter_state_change(_, old_state, new_state):
            with background_ctx(self.logger, type(self).__name__):
                self.widget.jupyter_state = new_state
                if (
                    new_state != IPythonShellState.Idle
                    or self.widget.monitoring_state == IPythonMonitoringState.None_
                ):
                    return
                now = ts_millis()
                if (
                    self.widget.jupyter_execution_num < self.widget.notify_min_execution
                    and now < self.widget.notify_min_time
                ):
                    return

                if (
                    self.widget.monitoring_state == IPythonMonitoringState.Error
                    and self.widget.jupyter_cell_state == IPythonCellStateType.Error
                ):
                    task = loop.create_task(self._send_notification())
                    task.add_done_callback(self._handle_done_future)
                elif self.widget.monitoring_state == IPythonMonitoringState.Stop:
                    task = loop.create_task(self._send_notification())
                    task.add_done_callback(self._handle_done_future)
                self.widget.monitoring_state = IPythonMonitoringState.None_

        jupyter_state_changed.connect(handle_jupyter_state_change, sender=self.history)

        def handle_jupyter_cell_state_change(_, old_state, new_state):
            with background_ctx(self.logger, type(self).__name__):
                self.logger.debug("State change %s %s", old_state, new_state)
                self.widget.jupyter_execution_num = new_state.execution_count
                state = IPythonCellStateType.Running
                error = ""
                if new_state.result and new_state.error():
                    error_obj = new_state.error()
                    if isinstance(error_obj, KeyboardInterrupt):
                        state = IPythonCellStateType.Cancelled
                    else:
                        state = IPythonCellStateType.Error
                        error = f"{type(new_state.error()).__name__}: {str(new_state.error())}"
                elif new_state.result:
                    state = IPythonCellStateType.Success
                self.widget.jupyter_cell_state = state
                self.widget.jupyter_cell_started_at = int(
                    new_state.started_at.timestamp() * 1000
                )
                finished_at = -1
                if new_state.finished_at:
                    finished_at = int(new_state.finished_at.timestamp() * 1000)
                self.widget.jupyter_cell_finished_at = finished_at
                self.widget.jupyter_cell_error = error

        jupyter_cell_state_changed.connect(
            handle_jupyter_cell_state_change, sender=self.history
        )

        self.history.connect()

        def unobserve():
            self.history.disconnect()
            jupyter_state_changed.disconnect(
                handle_jupyter_state_change, sender=self.history
            )
            jupyter_cell_state_changed.disconnect(
                handle_jupyter_cell_state_change, sender=self.history
            )

        return unobserve

    def _observe_instance(self, loop: asyncio.AbstractEventLoop) -> Callable[[], None]:
        disconnected = False
        instance = get_instance()

        def connect(instance: Instance) -> None:
            self.widget.selected_channel = instance.default_channel or "default"
            self.widget.auth_url = ""
            state = LMKWidgetState.NeedsAuth
            if instance.access_token:
                state = LMKWidgetState.Authenticated

            self.widget.state = state
            self.widget.channels_state = LMKChannelsState.None_
            self.widget.channels = []

        connect(instance)

        @default_channel_changed.connect
        def on_channel_changed(sender, old_value, new_value):
            nonlocal instance
            if sender is not instance:
                return
            with background_ctx(self.logger, type(self).__name__):
                self.widget.selected_channel = new_value or "default"

        @access_token_changed.connect
        def on_access_token_changed(sender, old_value, new_value):
            nonlocal instance
            if sender is not instance:
                return

            with background_ctx(self.logger, type(self).__name__):
                if old_value == new_value:
                    return
                self.widget.state = (
                    LMKWidgetState.Authenticated
                    if new_value
                    else LMKWidgetState.NeedsAuth
                )
                self.widget.channels_state = LMKChannelsState.None_
                self.widget.channels = []
                self.widget.selected_channel = "default"
                self.widget.auth_url = ""
                if new_value:
                    self.logger.info("Initiating channel fetch")
                    task = loop.create_task(self.refresh_channels({}, instance))
                    task.add_done_callback(self._handle_done_future)

        @default_instance_changed.connect
        def on_default_instance_changed(sender, old_instance, new_instance):
            nonlocal instance
            if instance is new_instance:
                return
            instance = new_instance
            with background_ctx(self.logger, type(self).__name__):
                connect(instance)

        def unbind():
            nonlocal disconnected
            if disconnected:
                return
            default_channel_changed.disconnect(on_channel_changed)
            access_token_changed.disconnect(on_access_token_changed)
            default_instance_changed.disconnect(on_default_instance_changed)
            disconnected = True

        return unbind

    def _observe_notebook(self) -> Callable[[], None]:
        @notebook_name_changed.connect_via(self.info_watcher)
        def handle_name_change(sender, old_value, new_value):
            self.widget.notebook_name = new_value or "<unknown>"

        def unobserve():
            notebook_name_changed.disconnect(handle_name_change, self.info_watcher)

        return unobserve

    async def _observe_auth(self) -> None:
        while True:
            instance = get_instance()
            api = AppApi(instance.client)
            access_token = await instance._get_access_token_async()
            if access_token:
                try:
                    await api.get_current_app(
                        async_req=True,
                        _headers={"Authorization": f"Bearer {access_token}"},
                    )
                except ApiException as err:
                    if 400 <= err.status < 500:
                        instance.logout()
            elif self.widget.state == LMKWidgetState.Authenticated:
                instance.logout()

            await asyncio.sleep(10)

    async def main_loop(self) -> None:
        while not self.shutdown_event.is_set():
            await asyncio.sleep(0.1)

    def run(self) -> None:
        with background_ctx(self.logger, type(self).__name__):
            loop = asyncio.new_event_loop()

            unobserve_instance = self._observe_instance(loop)
            unobserve_widget = self._observe_widget(loop)
            unobserve_jupyter = self._observe_jupyter(loop)
            unobserve_notebook = self._observe_notebook()

            tasks = []
            tasks.append(loop.create_task(self._monitor_stream()))
            tasks.append(loop.create_task(self.history.main_loop()))
            tasks.append(loop.create_task(self.info_watcher.main_loop()))
            tasks.append(loop.create_task(self._observe_auth()))

            try:
                loop.run_until_complete(self.main_loop())
            finally:
                for task in reversed(tasks):
                    with contextlib.suppress(asyncio.CancelledError):
                        task.cancel()
                unobserve_notebook()
                unobserve_jupyter()
                unobserve_widget()
                unobserve_instance()
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()


DEFAULT_WIDGET = None

DEFAULT_WIDGET_LOCK = threading.RLock()


def get_widget() -> LMKWidget:
    global DEFAULT_WIDGET
    with DEFAULT_WIDGET_LOCK:
        if DEFAULT_WIDGET is None:
            DEFAULT_WIDGET = LMKWidget()
        return DEFAULT_WIDGET


def set_widget(widget: LMKWidget) -> None:
    global DEFAULT_WIDGET
    with DEFAULT_WIDGET_LOCK:
        if widget is DEFAULT_WIDGET:
            return
        if DEFAULT_WIDGET is not None:
            DEFAULT_WIDGET.shutdown()
        DEFAULT_WIDGET = widget
