__all__ = ['send_and_wait', 'send_and_async_wait']

import asyncio
import atexit
from multiprocessing import connection
from threading import Lock


_LOCK = Lock()
_A_LOCK = asyncio.Lock()


def send_and_wait(*_):
    with _LOCK:
        _send(*_)
        return _recv()


async def send_and_async_wait(*_):
    async with _A_LOCK:
        with _LOCK:
            _send(*_)
            while not _poll():
                await asyncio.sleep(0.5)
            return _recv()


_CONN = None


def _set(conn: connection.Connection) -> None:
    global _CONN
    if not isinstance(conn, connection.Connection):
        raise ValueError(f"invalid connection type: {type(conn)}")
    if isinstance(_CONN, connection.Connection):
        _CONN.close()
    _CONN = conn


def _get() -> connection.Connection:
    if not isinstance(_CONN, connection.Connection):
        raise Exception("connection not found!")
    if _CONN.closed:
        raise Exception("connection has been closed!")
    return _CONN


def _poll() -> bool:
    return _get().poll()


def _send(*_) -> None:
    if _poll():
        raise Exception("connection is being used!")
    _get().send(_)


def _recv():
    result = _get().recv()
    if isinstance(result, Exception):
        raise result
    return result


def _close():
    global _CONN
    if isinstance(_CONN, connection.Connection):
        _CONN.close()
        _CONN = None


atexit.register(_close)
