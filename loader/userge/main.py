from importlib import import_module
from multiprocessing.connection import Connection


def run(conn: Connection) -> None:
    _conn = import_module("loader.userge.connection")
    getattr(_conn, '_set')(conn)
    getattr(_conn, '_get')()

    getattr(getattr(import_module("userge.main"), 'userge'), 'begin')()
