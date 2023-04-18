from lmk import jupyter, methods
from lmk.instance import get_instance, set_instance
from lmk.jupyter import (
    _jupyter_labextension_paths,
    _jupyter_nbextension_paths,
)

version_info = (0, 1, 0, "dev")

__version__ = ".".join(map(str, version_info))

__all__ = ["version_info", "__version__", "jupyter", "get_instance", "set_instance"]
__all__ += methods.__all__


def __getattr__(name: str):
    if name in globals():
        return globals()[name]
    if name in methods.__all__:
        return getattr(methods, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
