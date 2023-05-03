import abc
import io


class MonitoredProcess(abc.ABC):
    pid: int

    @abc.abstractmethod
    async def wait(self) -> int:
        raise NotImplementedError


class ProcessMonitor(abc.ABC):
    """
    """
    @abc.abstractmethod
    async def attach(
        self,
        pid: int,
        output_file: io.BytesIO,
    ) -> MonitoredProcess:
        """
        """
        raise NotImplementedError
