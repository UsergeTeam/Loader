from importlib import import_module

if __name__ == '__main__':
    getattr(import_module("loader.core.main"), 'load')()
