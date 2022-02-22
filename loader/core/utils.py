__all__ = ['log', 'error', 'call', 'open_url', 'get_client_type',
           'safe_url', 'grab_conflicts', 'clean_core', 'clean_plugins']

import logging
import os
import re
import subprocess
from functools import lru_cache
from itertools import combinations
from os.path import join
from shutil import rmtree
from signal import SIGTERM
from typing import Optional, Tuple, Set, Dict
from urllib.error import HTTPError
from urllib.request import urlopen, Request

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s - %(levelname)s] - %(name)s - %(message)s',
                    datefmt='%d-%b-%y %H:%M:%S')
_LOG = logging.getLogger("loader")


def log(msg: str) -> None:
    _LOG.info(msg)


def error(msg: str) -> None:
    _LOG.error(msg)
    os.kill(os.getpid(), SIGTERM)


def call(*args: str) -> Tuple[int, str]:
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    return p.wait(), p.communicate()[1]


def open_url(url: str, headers: dict) -> Optional[str]:
    r = Request(url, headers=headers)
    try:
        urlopen(r)
    except HTTPError as e:
        return str(e)


def get_client_type() -> str:
    token = os.environ.get('BOT_TOKEN')
    string = os.environ.get('SESSION_STRING')

    if token and string:
        return "dual"
    if token:
        return "bot"
    if string:
        return "user"


_TOKEN = re.compile("ghp_[0-9A-z]{36}")
_REQUIREMENTS = re.compile(r'(\S+)(<=|<|==|>=|>|!=|~=)(\S+)')


@lru_cache
def safe_url(url: str) -> str:
    return _TOKEN.sub('private', url)


def grab_conflicts(requirements: Set[str]) -> Set[str]:
    to_audit: Dict[str, Dict[str, Set[str]]] = {}

    for req in filter(lambda _: any(map(_.__contains__, ('=', '>', '<'))), requirements):
        match = _REQUIREMENTS.match(req)

        name = match.group(1)
        cond = match.group(2)
        version = match.group(3)

        if name not in to_audit:
            to_audit[name] = {}

        versions = to_audit[name]

        if version not in versions:
            versions[version] = set()

        version = versions[version]

        # :)
        if cond == '~=':
            cond = '>='

        version.add(cond)

    gt, ge, eq, le, lt, neq = '>', '>=', '==', '<=', '<', '!='

    sequence = (
        (gt, ge, neq),
        (ge, eq, le),
        (le, lt, neq)
    )

    pattern = []

    for i in range(len(sequence)):
        seq = sequence[i]

        pattern.append(seq)
        pattern.extend(combinations(seq, 2))

        for j in range(i + 1):
            pattern.append((seq[j],))

    pattern = tuple(pattern)

    for name, versions in to_audit.items():
        found = False

        for version in sorted(versions, reverse=True):
            args = versions[version]

            if found:
                # find and remove compatible reqs
                for _ in sequence[0]:
                    if _ in args:
                        args.remove(_)
            else:
                for check in pattern:
                    if all(map(args.__contains__, check)):
                        # found the breakpoint
                        for _ in check:
                            args.remove(_)

                        if not any(map(check.__contains__, sequence[2])):
                            found = True

                        break

    conflicts = set()

    for name, versions in to_audit.items():
        for version, args in versions.items():
            for arg in args:
                conflicts.add(name + arg + version)

    return conflicts


def clean_core() -> None:
    rmtree("userge", ignore_errors=True)


def clean_plugins() -> None:
    plugins_path = join("userge", "plugins")

    for cat in os.listdir(plugins_path):
        if cat == "builtin":
            continue

        rmtree(join(plugins_path, cat), ignore_errors=True)
