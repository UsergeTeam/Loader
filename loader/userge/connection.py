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


def _send(*_) -> None:
    if _poll():
        raise Exception("connection is being used!")
    _get().send(_)


def _recv():
    result = _get().recv()
    if isinstance(result, Exception):
        raise result
    return result


def _set(conn: connection.Connection) -> None:
    _Conn.set(conn)


def _get() -> connection.Connection:
    return _Conn.get()


def _poll() -> bool:
    return _get().poll()


def _close():
    _Conn.close()


atexit.register(_close)


class _Conn:
    _instance = None

    @classmethod
    def set(cls, conn: connection.Connection) -> None:
        if isinstance(cls._instance, connection.Connection):
            cls._instance.close()
        cls._instance = conn

    @classmethod
    def get(cls) -> connection.Connection:
        if not isinstance(cls._instance, connection.Connection):
            raise Exception("connection not found!")
        if cls._instance.closed:
            raise Exception("connection has been closed!")
        return cls._instance

    @classmethod
    def close(cls) -> None:
        if isinstance(cls._instance, connection.Connection):
            cls._instance.close()
            cls._instance = None
