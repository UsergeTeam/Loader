__all__ = ['load']

import os
import sys
from contextlib import suppress
from importlib import import_module
from multiprocessing import Process, Pipe, connection
from os.path import exists, isfile
from shutil import which
from signal import signal, SIGINT, SIGTERM, SIGABRT
from typing import Set

from dotenv import load_dotenv
from pymongo import MongoClient

from . import MIN_PY, MAX_PY, CONF_PATH, CONF_TMP_PATH
from .methods import fetch_core, fetch_repos
from .types import Database, Repos, RemovedPlugins, Sig, Requirements, Session, Tasks
from .utils import log, error, open_url, get_client_type, safe_url, grab_conflicts, clean_core, \
    clean_plugins


def check_git() -> None:
    log("Checking Git ...")

    if not which("git"):
        error(f"Required git !")


def check_py_version() -> None:
    log("Checking Python Version ...")

    py_ver = sys.version_info[0] + sys.version_info[1] / 10
    if py_ver < MIN_PY or py_ver > MAX_PY:
        error(f"You MUST have a python version of at least {MIN_PY}.0 !")

    log(f"\tFound PYTHON - v{py_ver}.{sys.version_info[2]} ...")


def load_config_file() -> None:
    log("Checking Config File ...")

    if isfile(CONF_PATH):
        log(f"\tConfig file found : {CONF_PATH}, Exporting ...")
        load_dotenv(CONF_PATH)

    if isfile(CONF_TMP_PATH):
        log(f"\tConfig file found : {CONF_TMP_PATH}, Exporting ...")
        load_dotenv(CONF_TMP_PATH, override=True)


def check_vars() -> None:
    log("Checking ENV Vars ...")

    env = os.environ

    for _ in ('API_ID', 'API_HASH', 'DATABASE_URL', 'LOG_CHANNEL_ID'):
        val = env.get(_)
        if not val:
            error(f"Required {_} var !")

    bot_token = env.get('BOT_TOKEN')
    if not env.get('SESSION_STRING') and not bot_token:
        error("Required SESSION_STRING or BOT_TOKEN var !")

    if bot_token and not env.get('OWNER_ID'):
        error("Required OWNER_ID var !")

    if not bot_token:
        log("\t[HINT] >>> BOT_TOKEN not found ! (Disabling Advanced Loggings)")

    _vars = dict(
        DOWN_PATH="downloads",
        ASSERT_SINGLE_INSTANCE="false",
        CMD_TRIGGER='.',
        SUDO_TRIGGER='!',
        FINISHED_PROGRESS_STR='█',
        UNFINISHED_PROGRESS_STR='░'
    )
    for k, v in _vars.items():
        env.setdefault(k, v)

    workers = int(env.get('WORKERS') or 0)
    env['WORKERS'] = str(min((16, min((os.cpu_count() + 4, workers)))))
    env['MOTOR_MAX_WORKERS'] = env['WORKERS']

    down_path = env['DOWN_PATH']
    env['DOWN_PATH'] = down_path.rstrip('/') + '/'

    cmd_trigger = env['CMD_TRIGGER']
    sudo_trigger = env['SUDO_TRIGGER']
    if cmd_trigger == sudo_trigger:
        error(f"Invalid SUDO_TRIGGER!, You can't use {cmd_trigger} as SUDO_TRIGGER")
    if cmd_trigger == '/' or sudo_trigger == '/':
        error(f"You can't use / as CMD_TRIGGER or SUDO_TRIGGER")

    h_api = 'HEROKU_API_KEY'
    h_app = 'HEROKU_APP_NAME'

    if not env.get('DYNO'):
        for _ in (h_api, h_app):
            if _ in env:
                env.pop(_)

    h_api = env.get(h_api)
    h_app = env.get(h_app)

    if h_api and not h_app or not h_api and h_app:
        error("Need both HEROKU_API_KEY and HEROKU_APP_NAME vars !")

    if h_api and h_app:
        if len(h_api) != 36 or len(h_api.split('-')) != 5:
            error(f"Invalid HEROKU_API_KEY ({h_api}) !")

        headers = {'Accept': "application/vnd.heroku+json; version=3", 'Bearer': h_api}

        e = open_url("https://api.heroku.com/account/rate-limits", headers)
        if e:
            error(f"Invalid HEROKU_API_KEY, heroku response > {e}")

        e = open_url(f"https://api.heroku.com/apps/{h_app}", headers)
        if e:
            error(f"Invalid HEROKU_APP_NAME ({h_app}), heroku response > {e}")

    if Database.is_none():
        db_url = env.get('DATABASE_URL')
        new_url = Database.fix_url(db_url)
        if new_url != db_url:
            env['DATABASE_URL'] = new_url

        cl = MongoClient(new_url, maxPoolSize=1, minPoolSize=0)
        try:
            cl.list_database_names()
        except Exception as e:
            error(f"Invalid DATABASE_URL, pymongo response > {str(e)}")
        Database.set(cl)

    for _ in (down_path, 'logs', '.rcache'):
        if not exists(_):
            os.mkdir(_)


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
                    reason = f"removed"
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
        check_git()
        check_py_version()
        load_config_file()
        check_vars()
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
