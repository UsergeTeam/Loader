from os import environ

MIN_PY = 3.8
MAX_PY = 3.9

CONF_PATH = "config.env"
CONF_TMP_PATH = f"{CONF_PATH}.tmp"

CORE_REPO = environ.get('CORE_REPO', "https://github.com/UsergeTeam/Userge")
CORE_BRANCH = environ.get('CORE_BRANCH', "master")
