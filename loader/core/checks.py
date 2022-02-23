__all__ = ['do_checks']

import os
import sys
from os.path import exists, isfile
from shutil import which

from dotenv import load_dotenv
from pymongo import MongoClient

from . import MIN_PY, MAX_PY, CONF_PATH, CONF_TMP_PATH
from .types import Database
from .utils import log, error, open_url


def _git() -> None:
    log("Checking Git ...")

    if not which("git"):
        error("Required git !")


def _py_version() -> None:
    log("Checking Python Version ...")

    py_ver = sys.version_info[0] + sys.version_info[1] / 10

    if py_ver < MIN_PY or py_ver > MAX_PY:
        error(f"You MUST have a python version of at least {MIN_PY}.0 !")

    log(f"\tFound PYTHON - v{py_ver}.{sys.version_info[2]} ...")


def _config_file() -> None:
    log("Checking Config File ...")

    if isfile(CONF_PATH):
        log(f"\tConfig file found : {CONF_PATH}, Exporting ...")

        load_dotenv(CONF_PATH)

    if isfile(CONF_TMP_PATH):
        log(f"\tConfig file found : {CONF_TMP_PATH}, Exporting ...")

        load_dotenv(CONF_TMP_PATH, override=True)


def _vars() -> None:
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

    _var_data = dict(
        DOWN_PATH="downloads",
        ASSERT_SINGLE_INSTANCE="false",
        CMD_TRIGGER='.',
        SUDO_TRIGGER='!',
        FINISHED_PROGRESS_STR='█',
        UNFINISHED_PROGRESS_STR='░'
    )
    for k, v in _var_data.items():
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
        error("You can't use / as CMD_TRIGGER or SUDO_TRIGGER")

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


def do_checks() -> None:
    _git()
    _py_version()
    _config_file()
    _vars()
