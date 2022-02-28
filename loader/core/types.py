__all__ = ['Database', 'Repos', 'Constraints', 'Sig', 'Requirements', 'Session', 'Tasks']

import os
import re
import sys
from configparser import ConfigParser, SectionProxy
from contextlib import suppress
from itertools import count
from multiprocessing import Process
from os.path import isdir, join, exists, isfile
from shutil import copytree, rmtree
from typing import Set, Iterable, Dict, Union, Optional, List, Callable, Tuple, Iterator
from urllib.parse import quote_plus

from git import Repo as GitRepo, Commit, InvalidGitRepositoryError, GitCommandError
from gitdb.exc import BadName
from pymongo import MongoClient
from pymongo.collection import Collection

from .utils import error, call, safe_url
from ..types import RepoInfo, Update, Constraint

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

    _RE_UP = re.compile(r"(?<=//)(.+)(?=@\w+)")

    @classmethod
    def fix_url(cls, url: str) -> str:
        u_and_p = cls._RE_UP.search(url).group(1)
        name, pwd = u_and_p.split(':')
        escaped = quote_plus(name) + ':' + quote_plus(pwd)
        return url.replace(u_and_p, escaped)

    def __init__(self, config: Collection, repos: Collection, constraint: Collection):
        self._config = config
        self._repos = repos
        self._constraint = constraint

    @classmethod
    def parse(cls, client: MongoClient) -> 'Database':
        db = client["Loader"]

        config = db["config"]
        repos = db["repos"]
        constraint = db["constraint"]

        return cls(config, repos, constraint)

    @property
    def config(self) -> Collection:
        return self._config

    @property
    def repos(self) -> Collection:
        return self._repos

    @property
    def constraint(self) -> Collection:
        return self._constraint


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
                 config: _Config, repo_name: str, repo_url: str):
        self.path = path
        self.cat = cat
        self.name = name
        self.config = config
        self.repo_name = repo_name
        self.repo_url = repo_url

    @classmethod
    def parse(cls, path: str, cat: str, name: str, repo: RepoInfo) -> '_Plugin':
        config = _Config.parse(join(path, "config.ini"))
        repo_name = repo.name

        return cls(path, cat, name, config, repo_name, repo.url)

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
                self._stderr = (e.stderr or 'null').strip()

    def _branch_exists(self, branch: str) -> bool:
        return branch and self._git and branch in self._git.heads

    def _version_exists(self, version: Union[int, str]) -> bool:
        return version and self._get_commit(version) is not None

    def _get_commit(self, version: Union[int, str]) -> Optional[Commit]:
        if self._git:
            if isinstance(version, int) or version.isnumeric():
                commit = self._git.commit(self.info.branch)

                input_count = int(version)
                head_count = commit.count()

                if input_count == head_count:
                    return commit

                if input_count < head_count:
                    skip = head_count - input_count
                    data = list(self._git.iter_commits(self.info.branch, max_count=1, skip=skip))

                    if data:
                        return data[0]

            elif isinstance(version, str):
                with suppress(BadName):
                    return self._git.commit(version)

    def fetch(self) -> None:
        if self.failed:
            return

        try:
            for info in self._git.remote().fetch():
                branch = info.ref.remote_head
                if branch not in self._git.heads:
                    self._git.create_head(branch, info.ref).set_tracking_branch(info.ref)
        except GitCommandError as e:
            self._git = None
            self._error_code = e.status
            self._stderr = (e.stderr or 'null').strip()
            return

        _changed = False

        if self._branch_exists(self.info.branch):
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
        self.info.max_count = head.commit.count()
        self.info.branches.update(head.name for head in self._git.heads)

        if _changed:
            self._update()

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

        if self._version_exists(version):
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

        if limit > 0 and self._version_exists(version):
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

    def _update(self) -> None:
        raise NotImplementedError


class _CoreRepo(_BaseRepo):
    _URL = "https://github.com/UsergeTeam/Userge"
    _PATH = join(_CACHE_PATH, "core")

    @classmethod
    def parse(cls, branch: str, version: str) -> '_CoreRepo':
        info = RepoInfo.parse(-1, -1, branch, version, cls._URL)
        path = _BaseRepo.gen_path(cls._PATH, cls._URL)

        return cls(info, path)

    def grab_req(self) -> Optional[List[str]]:
        req = join(self._path, "requirements.txt")

        if isfile(req):
            with open(req) as f:
                return f.read().strip().split()

    def grab_loader_version(self) -> Optional[str]:
        loader_ = join(self._path, "min_loader.txt")

        if isfile(loader_):
            with open(loader_) as f:
                return f.read().strip()

    def get_plugins(self) -> List[str]:
        cat_path = join(self._path, "plugins", "builtin")

        if exists(cat_path):
            return list(filter(lambda _: isdir(_) and not _.startswith("_"), os.listdir(cat_path)))

        return []

    def edit(self, branch: Optional[str], version: Optional[Union[int, str]]) -> bool:
        _changed = False

        if version and self.info.version != version and self._version_exists(version):
            self.info.version = version

            _changed = True

        if branch and self.info.branch != branch and self._branch_exists(branch):
            self.info.branch = branch
            self.info.version = ""

            _changed = True

        if _changed:
            self._update()
            Sig.core_remove()

        return _changed

    def copy(self, source="userge", path="userge") -> None:
        super().copy(source, path)

    def _update(self) -> None:
        Database.get().config.update_one({'key': 'core'},
                                         {"$set": {'branch': self.info.branch,
                                                   'version': self.info.version}}, upsert=True)


class _PluginsRepo(_BaseRepo):
    _PATH = join(_CACHE_PATH, "repos")
    _counter = count()

    def __init__(self, info: RepoInfo, path: str):
        super().__init__(info, path)
        self._plugins: List[_Plugin] = []

    @classmethod
    def parse(cls, priority: int, branch: str, version: str, url: str) -> '_PluginsRepo':
        info = RepoInfo.parse(next(cls._counter), priority, branch, version, url)
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

    def edit(self, branch: Optional[str], version: Optional[Union[int, str]],
             priority: Optional[int]) -> bool:
        _changed = False

        if version and self.info.version != version and self._version_exists(version):
            self.info.version = version

            _changed = True

        if self.info.branch != branch and self._branch_exists(branch):
            self.info.branch = branch
            self.info.version = ""

            _changed = True

        if self.info.priority != priority:
            self.info.priority = priority

            Repos.sort()
            _changed = True

        if _changed:
            self._update()
            Sig.repos_remove()

        return _changed

    def iter_plugins(self) -> Iterator[_Plugin]:
        return iter(self._plugins)

    def _update(self) -> None:
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
        reset = len(sys.argv) > 1 and sys.argv[1].lower() == "reset"

        data = db.config.find_one({'key': 'core'})
        branch = data['branch'] if data and not reset else "alpha"
        version = data['version'] if data and not reset else ""
        cls._core = _CoreRepo.parse(branch, version)

        for d in db.repos.find():
            repo = _PluginsRepo.parse(d['priority'], d['branch'], d['version'], d['url'])
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

        version = ""

        cls._plugins.append(_PluginsRepo.parse(priority, branch, version, url))
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


class _ConstraintData:
    def __init__(self, repo_name: Optional[str], plg_cat: Optional[str],
                 plg_name: Optional[str], raw: str):
        self.repo_name = repo_name
        self.plg_cat = plg_cat
        self.plg_name = plg_name
        self.raw = raw

    @classmethod
    def parse(cls, data: str) -> '_ConstraintData':
        data = data.strip().lower()
        parts = data.split('/')
        size = len(parts)

        repo_name = None
        plg_cat = None
        plg_name = None

        # possible cases
        #
        # plg_name
        # plg_cat/
        # repo_name/plg_name
        # repo_name/plg_cat/
        #

        if size == 3:
            repo_name = parts[0]
            plg_cat = parts[1]

        elif size == 2:
            if parts[1]:
                repo_name = parts[0]
                plg_name = parts[1]
            else:
                plg_cat = parts[0]

        else:
            plg_name = parts[0]

        return cls(repo_name, plg_cat, plg_name, data)

    def match(self, repo_name: str, plg_cat: str, plg_name: str) -> bool:
        if self.repo_name and self.repo_name != repo_name:
            return False

        if self.plg_cat and self.plg_cat != plg_cat:
            return False

        if self.plg_name and self.plg_name != plg_name:
            return False

        if self.repo_name or self.plg_cat or self.plg_name:
            return True

        return False

    def __str__(self) -> str:
        return self.raw


class _Constraint:
    def __init__(self):
        self._data: List[_ConstraintData] = []

    def add(self, data: List[str]) -> List[str]:
        added = []

        for d in set(map(lambda _: _.strip().lower(), data)):
            if all(map(lambda _: _.raw != d, self._data)):
                self._data.append(_ConstraintData.parse(d.strip()))
                added.append(d)

        return added

    def remove(self, data: List[str]) -> List[str]:
        removed = []

        for d in set(map(lambda _: _.strip().lower(), data)):
            for cd in self._data:
                if cd.raw == d:
                    self._data.remove(cd)
                    removed.append(d)
                    break

        return removed

    def clear(self) -> int:
        size = len(self._data)
        self._data.clear()

        return size

    def to_constraint(self) -> Optional[Constraint]:
        if self._data:
            return Constraint(self.get_type(), self._to_str_list())

    def get_type(self) -> str:
        raise NotImplementedError

    def _to_str_list(self) -> List[str]:
        return list(map(str, self._data))

    def empty(self) -> bool:
        return len(self._data) == 0

    def match(self, *args: str) -> bool:
        for part in self._data:
            if part.match(*args):
                return True

        return False

    def __str__(self) -> str:
        return self.get_type() + '(' + str(self._to_str_list()) + ')'


class _Include(_Constraint):
    def get_type(self) -> str:
        return "include"


class _Exclude(_Constraint):
    def get_type(self) -> str:
        return "exclude"


class _In(_Constraint):
    def get_type(self) -> str:
        return "in"


class _Constraints:
    def __init__(self, *data: _Constraint):
        self._data = data

    def get(self, c_type: str) -> Optional[_Constraint]:
        c_type = c_type.strip().lower()

        for const in self._data:
            if const.get_type() == c_type:
                return const

    def remove(self, data: List[str]) -> List[str]:
        removed = []

        for const in self._data:
            removed.extend(const.remove(data))

        return removed

    def clear(self) -> int:
        _count = 0

        for const in self._data:
            _count += const.clear()

        return _count

    def to_constraints(self) -> List[Constraint]:
        return list(filter(None, map(_Constraint.to_constraint, self._data)))

    def match(self, *args: str) -> Optional[_Constraint]:
        for const in self._data:
            if const.empty():
                continue

            if isinstance(const, _Include):
                if const.match(*args):
                    break

            elif isinstance(const, _Exclude):
                if const.match(*args):
                    return const

            elif isinstance(const, _In):
                if not const.match(*args):
                    return const


class Constraints:
    _data = _Constraints(_Include(), _Exclude(), _In())
    _loaded = False

    @classmethod
    def load(cls) -> None:
        if cls._loaded:
            return

        for d in Database.get().constraint.find():
            c_type = d['type']
            data = d['data']

            const = cls._data.get(c_type)

            if const:
                const.add([data])

        cls._loaded = True

    @classmethod
    def add(cls, c_type: str, data: List[str]) -> None:
        const = cls._data.get(c_type)

        if not const:
            return

        to_add = const.add(data)

        if to_add:
            Database.get().constraint.insert_many(
                map(lambda _: dict(type=const.get_type(), data=_), to_add))

            Sig.repos_remove()

    @classmethod
    def remove(cls, c_type: Optional[str], data: List[str]) -> None:
        if c_type:
            const = cls._data.get(c_type)

            if not const:
                return

            to_remove = const.remove(data)
        else:
            to_remove = cls._data.remove(data)

        if to_remove:
            _data = {'data': {'$in': to_remove}}

            if c_type:
                _data['type'] = c_type.strip().lower()

            Database.get().constraint.delete_many(_data)
            Sig.repos_remove()

    @classmethod
    def clear(cls, c_type: Optional[str]) -> None:
        if c_type:
            const = cls._data.get(c_type)

            if not const:
                return

            _count = const.clear()
        else:
            _count = cls._data.clear()

        if _count:
            Database.get().constraint.drop()
            Sig.repos_remove()

    @classmethod
    def get(cls) -> List[Constraint]:
        return cls._data.to_constraints()

    @classmethod
    def match(cls, plg: _Plugin) -> Optional[_Constraint]:
        return cls._data.match(plg.repo_name.lower(), plg.cat.lower(), plg.name.lower())


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

            cls._upgrade_pip()
            return call(sys.executable, '-m', 'pip', 'install', '--no-warn-script-location', *data)

        return 0, ''

    @classmethod
    def _upgrade_pip(cls) -> None:
        call(sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip')


class Tasks:
    _handlers: Dict[int, Callable] = {}

    @classmethod
    def add(cls, job: int, callback: Callable) -> None:
        cls._handlers[job] = callback

    @classmethod
    def handle(cls, job: int, *arg) -> object:
        try:
            return cls._handlers[job](*arg)
        except KeyError:
            return KeyError(f"Invalid job id: {job}")
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
