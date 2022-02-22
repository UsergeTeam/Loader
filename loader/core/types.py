__all__ = ['Database', 'Repos', 'RemovedPlugins', 'Sig', 'Requirements', 'Session', 'Tasks']

import os
import re
import sys
from configparser import ConfigParser, SectionProxy
from contextlib import suppress
from multiprocessing import Process
from os.path import isdir, join, exists, isfile
from shutil import copytree, rmtree
from typing import Set, Iterable, Dict, Union, Optional, List, Callable, Tuple, Iterator
from urllib.parse import quote_plus

from git import Repo as GitRepo, Commit, InvalidGitRepositoryError, GitCommandError
from gitdb.exc import BadName
from pymongo import MongoClient
from pymongo.collection import Collection

from ..types import RepoInfo, Update
from .utils import error, call, safe_url

_CACHE_PATH = ".rcache"


class Database:
    _instance = None

    @classmethod
    def is_none(cls) -> bool:
        return cls._instance is None

    @classmethod
    def get(cls) -> 'Database':
        if not cls._instance:
            error("Database not initialized !")
        return cls._instance

    @classmethod
    def set(cls, client: MongoClient) -> None:
        if not cls._instance:
            cls._instance = cls.parse(client)

    _RE_UP = re.compile(r"(?<=//)(.+)(?=@cluster)")

    @classmethod
    def fix_url(cls, url: str) -> str:
        u_and_p = cls._RE_UP.search(url).group(1)
        name, pwd = u_and_p.split(':')
        escaped = quote_plus(name) + ':' + quote_plus(pwd)
        return url.replace(u_and_p, escaped)

    def __init__(self, config: Collection, repos: Collection, removed: Collection):
        self._config = config
        self._repos = repos
        self._removed = removed

    @classmethod
    def parse(cls, client: MongoClient) -> 'Database':
        db = client["Loader"]

        config = db["config"]
        repos = db["repos"]
        removed = db["removed"]

        return cls(config, repos, removed)

    @property
    def config(self) -> Collection:
        return self._config

    @property
    def repos(self) -> Collection:
        return self._repos

    @property
    def removed(self) -> Collection:
        return self._removed


class _Parser:
    def __init__(self, section: SectionProxy):
        self._section = section

    @classmethod
    def parse(cls, path: str) -> '_Parser':
        parser = ConfigParser()
        parser.read(path)
        section = parser[parser.default_section]

        return cls(section)

    def get(self, key: str) -> Optional[str]:
        with suppress(KeyError):
            return self._section.get(key)

    def getint(self, key: str) -> Optional[int]:
        with suppress(KeyError, ValueError):
            return self._section.getint(key)

    def getboolean(self, key: str) -> Optional[bool]:
        with suppress(KeyError, ValueError):
            return self._section.getboolean(key)

    def getset(self, key: str) -> Optional[Set[str]]:
        value = self.get(key)
        if value:
            return set(filter(None, map(lambda _: _.strip().lower(), value.split(','))))


class _Config:
    def __init__(self, available: Optional[bool], min_core: Optional[int],
                 max_core: Optional[int], client_type: Optional[str],
                 envs: Optional[Set[str]], bins: Optional[Set[str]],
                 depends: Optional[Set[str]], packages: Optional[Set[str]]):
        self.available = available
        self.min_core = min_core
        self.max_core = max_core
        self.client_type = client_type
        self.envs = envs
        self.bins = bins
        self.depends = depends
        self.packages = packages

    @classmethod
    def parse(cls, path: str) -> '_Config':
        parser = _Parser.parse(path)

        available = parser.getboolean('available')
        min_core = parser.getint('min_core')
        max_core = parser.getint('max_core')
        client_type = parser.get('client_type')
        envs = parser.getset('envs')
        bins = parser.getset('bins')
        depends = parser.getset('depends')
        packages = parser.getset('packages')

        return cls(available, min_core, max_core, client_type, envs, bins, depends, packages)


class _Plugin:
    def __init__(self, path: str, cat: str, name: str,
                 config: _Config, repo_url: str):
        self.path = path
        self.cat = cat
        self.name = name
        self.config = config
        self.repo_url = repo_url

    @classmethod
    def parse(cls, path: str, cat: str, name: str, repo: RepoInfo) -> '_Plugin':
        config = _Config.parse(join(path, "config.ini"))

        return cls(path, cat, name, config, repo.url)

    def copy(self) -> None:
        copytree(self.path, join("userge", "plugins", self.cat, self.name))


class _BaseRepo:
    def __init__(self, info: RepoInfo, path: str):
        self.info = info
        self._path = path
        self._git: Optional[GitRepo] = None
        self._error_code = 0
        self._stderr = ""

    @property
    def failed(self):
        return self._git is None

    @property
    def error(self) -> Tuple[int, str]:
        return self._error_code, self._stderr

    def init(self) -> None:
        if self._git:
            return

        if exists(self._path):
            try:
                self._git = GitRepo(self._path)
            except InvalidGitRepositoryError:
                self.delete()

        if not self._git:
            try:
                self._git = GitRepo.clone_from(self.info.url, self._path)
            except GitCommandError as e:
                self._error_code = e.status
                self._stderr = e.stderr

    def branch_exists(self, branch: str) -> bool:
        return branch and self._git and branch in self._git.heads

    def version_exists(self, version: str) -> bool:
        return version and self._get_commit(version) is not None

    def _get_commit(self, version: str) -> Optional[Commit]:
        if self._git:
            with suppress(BadName):
                return self._git.commit(version)

    def fetch(self) -> None:
        if self.failed:
            return

        for info in self._git.remote().fetch():
            branch = info.ref.remote_head
            if branch not in self._git.heads:
                self._git.create_head(branch, info.ref).set_tracking_branch(info.ref)

        _changed = False

        if self.branch_exists(self.info.branch):
            head = self._git.heads[self.info.branch]
        else:
            head = self._git.heads[0]
            self.info.branch = head.name
            _changed = True

        if self._git.head.is_detached or self._git.head.ref != head:
            head.checkout(force=True)
        self._git.remote().pull(head.name, force=True)

        commit = self._get_commit(self.info.version) if self.info.version else None

        if not commit:
            self.info.version = head.commit.hexsha
            _changed = True

        self.info.count = (commit or head.commit).count()
        self.info.branches.update(head.name for head in self._git.heads)

        if _changed:
            self.update()

    def checkout_version(self) -> None:
        version = self.info.version

        if self._git and self._git.head.commit.hexsha != version:
            self._git.git.checkout(version, force=True)

    def checkout_branch(self) -> None:
        branch = self.info.branch

        if self._git and (self._git.head.is_detached or self._git.head.ref.name != branch):
            self._git.git.checkout(branch, force=True)

    def copy(self, source: str, path: str) -> None:
        copytree(join(self._path, source), path)

    def new_commits(self) -> List[Update]:
        data = []
        version = self.info.version

        if self.version_exists(version):
            found = False
            for commit in self._git.iter_commits(self.info.branch):
                if commit.hexsha == version:
                    found = True
                    break
                data.append(Update.parse(safe_url(self.info.url), commit))

            if not found:
                data.clear()

        return data

    def old_commits(self, limit: int) -> List[Update]:
        data = []
        version = self.info.version

        if limit > 0 and self.version_exists(version):
            found = False
            for commit in self._git.iter_commits(self.info.branch):
                if not found:
                    if commit.hexsha != version:
                        continue
                    found = True
                    continue
                data.append(Update.parse(safe_url(self.info.url), commit))

                limit -= 1
                if limit <= 0:
                    break

        return data

    def delete(self) -> None:
        rmtree(self._path, ignore_errors=True)

    @staticmethod
    def gen_path(path: str, url: str) -> str:
        return join(path, '.'.join(url.split('/')[-2:]))

    def update(self) -> None:
        raise NotImplementedError


class _CoreRepo(_BaseRepo):
    _URL = "https://github.com/UsergeTeam/Userge"
    _PATH = join(_CACHE_PATH, "core")

    @classmethod
    def parse(cls, branch: str, version: str) -> '_CoreRepo':
        info = RepoInfo(-1, -1, branch, version, cls._URL)
        path = _BaseRepo.gen_path(cls._PATH, cls._URL)

        return cls(info, path)

    def grab_req(self) -> Optional[List[str]]:
        req = join(self._path, "requirements.txt")

        if isfile(req):
            with open(req) as f:
                return f.read().strip().split()

    def get_plugins(self) -> List[str]:
        cat_path = join(self._path, "plugins", "builtin")

        if exists(cat_path):
            return list(filter(lambda _: isdir(_) and not _.startswith("_"), os.listdir(cat_path)))

        return []

    def update(self) -> None:
        Database.get().config.update_one({'key': 'core'},
                                         {"$set": {'branch': self.info.branch,
                                                   'version': self.info.version}}, upsert=True)


class _PluginsRepo(_BaseRepo):
    _PATH = join(_CACHE_PATH, "repos")

    def __init__(self, info: RepoInfo, path: str):
        super().__init__(info, path)
        self._plugins: List[_Plugin] = []

    @classmethod
    def parse(cls, id_: int, priority: int, branch: str, version: str, url: str) -> '_PluginsRepo':
        info = RepoInfo(id_, priority, branch, version, url)
        path = _BaseRepo.gen_path(cls._PATH, url)

        return cls(info, path)

    def load_plugins(self) -> None:
        self._plugins.clear()

        plugins_path = join(self._path, "plugins")
        if not isdir(plugins_path):
            return

        for cat in os.listdir(plugins_path):
            cat_path = join(plugins_path, cat)
            if not isdir(cat_path) or cat == "builtin" or cat.startswith('_'):
                continue

            for plg in os.listdir(cat_path):
                plg_path = join(cat_path, plg)
                if not isdir(plg_path) or plg.startswith('_'):
                    continue

                self._plugins.append(_Plugin.parse(plg_path, cat, plg, self.info))

    def iter_plugins(self) -> Iterator[_Plugin]:
        return iter(self._plugins)

    def update(self) -> None:
        Database.get().repos.update_one({'url': self.info.url},
                                        {"$set": {'branch': self.info.branch,
                                                  'version': self.info.version,
                                                  'priority': self.info.priority}})


class Repos:
    _core: Optional[_CoreRepo] = None
    _plugins: List[_PluginsRepo] = []
    _loaded = False
    _RE_REPO = re.compile(r"https://(?:ghp_[0-9A-z]{36}@)?github.com/.+/.+")

    @classmethod
    def load(cls) -> None:
        if cls._loaded:
            return

        db = Database.get()

        data = db.config.find_one({'key': 'core'})
        branch = data['branch'] if data else "new"
        version = data['version'] if data else ""
        cls._core = _CoreRepo.parse(branch, version)

        for i, d in enumerate(db.repos.find(), start=1):
            repo = _PluginsRepo.parse(i, d['priority'], d['branch'], d['version'], d['url'])
            cls._plugins.append(repo)

        cls.sort()
        cls._loaded = True

    @classmethod
    def sort(cls) -> None:
        cls._plugins.sort(key=lambda _: _.info.priority)

    @classmethod
    def get_core(cls) -> Optional[_CoreRepo]:
        return cls._core

    @classmethod
    def get(cls, repo_id_or_url: Union[int, str]) -> Optional[_PluginsRepo]:
        is_id = isinstance(repo_id_or_url, int)

        for repo in cls._plugins:
            if is_id:
                if repo.info.id == repo_id_or_url:
                    return repo
            else:
                if repo.info.url == repo_id_or_url:
                    return repo

    @classmethod
    def has_repos(cls) -> bool:
        return len(cls._plugins) > 0

    @classmethod
    def iter_repos(cls) -> Iterator[_PluginsRepo]:
        return iter(cls._plugins)

    @classmethod
    def add(cls, priority: int, branch: str, url: str) -> None:
        if not cls._RE_REPO.match(url) or cls.get(url):
            return

        repo_id = cls._plugins[-1].info.id + 1 if cls._plugins else 1
        version = ""

        cls._plugins.append(_PluginsRepo.parse(repo_id, priority, branch, version, url))
        cls.sort()
        Database.get().repos.insert_one({'priority': priority, 'branch': branch,
                                         'version': version, 'url': url})
        Sig.repos_remove()

    @classmethod
    def remove(cls, repo_id: int) -> None:
        repo = cls.get(repo_id)
        if repo:
            cls._plugins.remove(repo)
            Database.get().repos.delete_one({'url': repo.info.url})
            repo.delete()
            Sig.repos_remove()


class RemovedPlugins:
    _data: Set[str] = set()
    _loaded = False

    @classmethod
    def load(cls) -> None:
        if cls._loaded:
            return

        for d in Database.get().removed.find():
            cls._data.add(d['name'])

        cls._loaded = True

    @classmethod
    def add(cls, names: List[str]) -> None:
        to_add = set(map(str.strip, names)).difference(cls._data)

        if to_add:
            cls._data.update(to_add)
            Database.get().removed.insert_many(map(lambda _: dict(name=_), to_add))
            Sig.repos_remove()

    @classmethod
    def remove(cls, names: List[str]) -> None:
        to_remove = cls._data.intersection(set(map(str.strip, names)))

        if to_remove:
            cls._data.difference_update(to_remove)
            Database.get().removed.delete_many({'name': {'$in': to_remove}})
            Sig.repos_remove()

    @classmethod
    def contains(cls, name: str) -> bool:
        return name in cls._data

    @classmethod
    def get(cls) -> List[str]:
        return list(cls._data)

    @classmethod
    def clear(cls) -> None:
        if cls._data:
            cls._data.clear()
            Database.get().removed.drop()
            Sig.repos_remove()


class Sig:
    _core = join(_CACHE_PATH, ".sig_core")
    _repos = join(_CACHE_PATH, ".sig_repos")

    @staticmethod
    def _make(path: str) -> None:
        if not exists(path):
            open(path, 'w').close()

    @staticmethod
    def _remove(path: str) -> None:
        if exists(path):
            os.remove(path)

    @classmethod
    def core_exists(cls) -> bool:
        return exists(cls._core)

    @classmethod
    def core_make(cls) -> None:
        cls._make(cls._core)

    @classmethod
    def core_remove(cls) -> None:
        cls._remove(cls._core)

    @classmethod
    def repos_exists(cls) -> bool:
        return exists(cls._repos)

    @classmethod
    def repos_make(cls) -> None:
        cls._make(cls._repos)

    @classmethod
    def repos_remove(cls) -> None:
        cls._remove(cls._repos)


class Requirements:
    _data = set()

    @classmethod
    def has(cls) -> bool:
        return len(cls._data) > 0

    @classmethod
    def update(cls, data: Optional[Iterable[str]]) -> None:
        if data:
            cls._data.update(filter(None, map(str.strip, data)))

    @classmethod
    def install(cls) -> Tuple[int, str]:
        if cls._data:
            data = cls._data.copy()
            cls._data.clear()
            return call(sys.executable, '-m', 'pip', 'install', *data)

        return 0, ''


class Tasks:
    _handlers: Dict[int, Callable] = {}

    @classmethod
    def add(cls, job: int, callback: Callable) -> None:
        cls._handlers[job] = callback

    @classmethod
    def handle(cls, job: int, *arg) -> object:
        try:
            return cls._handlers[job](*arg)
        except Exception as e:
            return e


class Session:
    _init = True
    _restart = False
    _process: Optional[Process] = None

    @classmethod
    def should_init(cls) -> bool:
        if cls._init:
            cls._init = False
            return True

        return False

    @classmethod
    def should_restart(cls) -> bool:
        if cls._restart:
            cls._restart = False
            return True

        return False

    @classmethod
    def set_process(cls, p: Process) -> None:
        cls._process = p

    @classmethod
    def restart(cls, should_init: bool) -> None:
        cls._init = should_init
        cls._restart = True
        if cls._process:
            cls._process.terminate()
