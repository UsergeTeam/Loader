from importlib import import_module


def run(conn) -> None:
    getattr(import_module("loader.userge.connection"), '_set')(conn)
    getattr(getattr(import_module("userge.main"), 'userge'), 'begin')()
