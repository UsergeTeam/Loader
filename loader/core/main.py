__all__ = ['load']

import os
from contextlib import suppress
from importlib import import_module
from multiprocessing import Process, Pipe, connection
from shutil import which
from signal import signal, SIGINT, SIGTERM, SIGABRT
from typing import Set

from .checks import do_checks
from .methods import fetch_core, fetch_repos
from .types import Repos, RemovedPlugins, Sig, Requirements, Session, Tasks
from .utils import log, error, get_client_type, safe_url, grab_conflicts, clean_core, \
    clean_plugins, printLogo
from .. import __version__


def load_repos() -> None:
    log("Loading Repos ...")

    Repos.load()
    RemovedPlugins.load()


def init_core() -> None:
    log("Fetching Core ...")

    fetch_core()
    if Sig.core_exists():
        return

    log("Initializing Core ...")

    core = Repos.get_core()
    if core.failed:
        code, err = core.error
        error(f"error code: [{code}]\n{err}")

    core.checkout_version()

    Requirements.update(core.grab_req())
    clean_core()
    core.copy()

    core.checkout_branch()

    Sig.repos_remove()
    Sig.core_make()


def init_repos() -> None:
    log("Fetching Repos ...")

    fetch_repos()
    if not Repos.has_repos() or Sig.repos_exists():
        return

    log("Initializing Repos ...")

    repos = 0
    plugins = {}
    core_version = Repos.get_core().info.count
    client_type = get_client_type()

    for repo in Repos.iter_repos():
        if repo.failed:
            code, err = repo.error
            log(f"\tSkipping: {safe_url(repo.info.url)} code: [{code}] due to: {err}")
            continue

        repo.checkout_version()
        repo.load_plugins()

        ignored = 0
        overridden = 0

        for plg in repo.iter_plugins():
            conf = plg.config
            reason = None

            for _ in ' ':
                if not conf.available:
                    reason = "not available"
                    break

                if RemovedPlugins.contains(plg.name):
                    reason = "removed"
                    break

                if conf.min_core and conf.min_core > core_version:
                    reason = f"min core version {conf.min_core} required, current {core_version}"
                    break

                if conf.max_core and conf.max_core < core_version:
                    reason = f"max core version {conf.max_core} required, current {core_version}"
                    break

                if conf.client_type and conf.client_type.lower() != client_type:
                    c_type = conf.client_type.lower()
                    reason = f"client type {c_type} required, current: {client_type}"
                    break

                if conf.envs:
                    for env in conf.envs:
                        if not os.environ.get(env):
                            reason = f"env {env} required"
                            break

                    if reason:
                        break

                if conf.bins:
                    for bin_ in conf.bins:
                        if not which(bin_):
                            reason = f"bin {bin_} required"
                            break

                    if reason:
                        break

                old = plugins.get(plg.name)
                plugins[plg.name] = plg

                if old:
                    overridden += 1
                    log(f"\tPlugin: [{plg.cat}/{plg.name}] "
                        f"is overriding Repo: ({safe_url(old.repo_url)})")
            else:
                continue

            ignored += 1
            log(f"\tPlugin: [{plg.cat}/{plg.name}] was ignored due to: ({reason})")

        repos += 1
        log(f"\t\tRepo: {safe_url(repo.info.url)} ignored: {ignored} overridden: {overridden}")

    for c_plg in Repos.get_core().get_plugins():
        if c_plg in plugins:
            plg = plugins.pop(c_plg)

            log(f"\tPlugin: [{plg.cat}/{plg.name}] was removed due to: "
                f"matching builtin found")

    def resolve_depends() -> None:
        all_ok = False

        while plugins and not all_ok:
            all_ok = True

            for plg_ in tuple(plugins.values()):
                deps = plg_.config.depends
                if not deps:
                    continue

                for dep in deps:
                    if dep not in plugins:
                        all_ok = False
                        del plugins[plg_.name]

                        log(f"\tPlugin: [{plg_.cat}/{plg_.name}] was removed due to: "
                            f"plugin ({dep}) not found")

    def grab_requirements() -> Set[str]:
        data = set()

        for plg_ in plugins.values():
            packages_ = plg_.config.packages
            if packages_:
                data.update(packages_)

        return data

    resolve_depends()
    requirements = grab_requirements()

    if requirements:
        conflicts = grab_conflicts(requirements)

        if conflicts:
            for conflict in conflicts:
                for plg in tuple(plugins.values()):
                    packages = plg.config.packages

                    if packages and conflict in packages:
                        del plugins[plg.name]

                        log(f"\tPlugin: [{plg.cat}/{plg.name}] was removed due to: "
                            f"conflicting requirement ({conflict}) found")

            resolve_depends()
            requirements = grab_requirements()

        Requirements.update(requirements)

    clean_plugins()

    for plg in plugins.values():
        plg.copy()

    log(f"\tTotal plugins: {len(plugins)} from repos: {repos}")

    for repo in Repos.iter_repos():
        repo.checkout_branch()

    Sig.repos_make()


def install_req() -> None:
    pip = os.environ.get('CUSTOM_PIP_PACKAGES')
    if pip:
        Requirements.update(pip.split())

    if Requirements.has():
        log("Installing Requirements ...")

        code, err = Requirements.install()
        if code:
            error(f"error code: [{code}]\n{err}")


def run_loader() -> None:
    load_repos()
    init_core()
    init_repos()
    install_req()


def initialize() -> None:
    try:
        printLogo()
        do_checks()
        run_loader()
    except Exception as e:
        error(str(e))


def run_userge() -> None:
    log("Starting Userge ...")

    p_p, c_p = Pipe()
    p = Process(name="userge", target=_run_userge, args=(c_p,))
    Session.set_process(p)

    def handle(*_):
        p_p.close()
        p.terminate()

    for _ in (SIGINT, SIGTERM, SIGABRT):
        signal(_, handle)

    p.start()
    c_p.close()

    with suppress(EOFError, OSError):
        while p.is_alive() and not p_p.closed:
            p_p.send(Tasks.handle(*p_p.recv()))

    p_p.close()
    p.join()
    p.close()


def _run_userge(conn: connection.Connection) -> None:
    getattr(import_module("loader.userge.connection"), "_set")(conn)
    getattr(getattr(import_module("userge.main"), 'userge'), 'begin')()


def load() -> None:
    if Session.should_init():
        initialize()

    run_userge()
    if Session.should_restart():
        load()


log(f"Loader v{__version__}")
