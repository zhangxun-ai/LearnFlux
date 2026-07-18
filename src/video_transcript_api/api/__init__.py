__all__ = ["app", "start_server"]


def __getattr__(name: str):
    if name in __all__:
        from .server import app, start_server

        values = {
            "app": app,
            "start_server": start_server,
        }
        return values[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
