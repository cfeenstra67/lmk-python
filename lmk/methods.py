from lmk.instance import Instance, get_instance


__all__ = [
    name
    for name in dir(Instance)
    if not name.startswith("_")
    if not isinstance(getattr(Instance, name), property)
]


def __getattr__(name: str):
    if (
        name.startswith("_")
        or not hasattr(Instance, name)
        or isinstance(getattr(Instance, name), property)
    ):
        raise AttributeError(name)
    instance = get_instance()
    return getattr(instance, name)
