from importlib import import_module
from os.path import abspath
from sys import argv


def run(conn) -> None:
    argv[0] = abspath("alexa")
    getattr(import_module("loader.alexa.connection"), '_set')(conn)
    getattr(getattr(import_module("alexa.main"), 'alexa'), 'begin')()
