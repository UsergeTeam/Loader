__all__ = ['fetch_core', 'fetch_repos']

from contextlib import suppress
from copy import copy
from os import environ
from typing import List, Optional, Callable

from dotenv import set_key, unset_key

from .. import job
from ..types import RepoInfo, Update
from . import CONF_TMP_PATH
from .types import Tasks, Session, Repos, RemovedPlugins, Sig
from .utils import error, safe_url


def on(work: int) -> Callable[[Callable], Callable]:
    def wrapper(func: Callable) -> Callable:
        Tasks.add(work, func)
        return func

    return wrapper


@on(job.SOFT_RESTART)
def restart_soft() -> None:
    Session.restart(False)


@on(job.HARD_RESTART)
def restart_hard() -> None:
    Session.restart(True)


@on(job.FETCH_CORE)
def fetch_core() -> None:
    core = Repos.get_core()
    if not core:
        error("Core Not Found !")

    core.init()
    core.fetch()


@on(job.FETCH_REPOS)
def fetch_repos() -> None:
    for repo in Repos.iter_repos():
        repo.init()
        repo.fetch()


@on(job.GET_CORE)
def get_core() -> Optional[RepoInfo]:
    core = Repos.get_core()
    if core:
        return core.info


@on(job.GET_REPOS)
def get_repos() -> List[RepoInfo]:
    data = []

    for repo in Repos.iter_repos():
        info = copy(repo.info)
        info.url = safe_url(info.url)
        data.append(info)

    return data


@on(job.ADD_REPO)
def add_repo(priority: int, branch: str, url: str) -> None:
    Repos.add(priority, branch, url)


@on(job.REMOVE_REPO)
def remove_repo(repo_id: int) -> None:
    Repos.remove(repo_id)


@on(job.GET_CORE_NEW_COMMITS)
def get_core_new_commits() -> Optional[List[Update]]:
    core = Repos.get_core()
    if core:
        return core.new_commits()


@on(job.GET_CORE_OLD_COMMITS)
def get_core_old_commits(limit: int) -> Optional[List[Update]]:
    core = Repos.get_core()
    if core:
        return core.old_commits(limit)


@on(job.GET_REPO_NEW_COMMITS)
def get_repo_new_commits(repo_id: int) -> Optional[List[Update]]:
    repo = Repos.get(repo_id)
    if repo:
        return repo.new_commits()


@on(job.GET_REPO_OLD_COMMITS)
def get_repo_old_commits(repo_id: int, limit: int) -> Optional[List[Update]]:
    repo = Repos.get(repo_id)
    if repo:
        return repo.old_commits(limit)


@on(job.SET_CORE_BRANCH)
def set_core_branch(branch: str) -> None:
    core = Repos.get_core()
    if core and core.info.branch != branch and core.branch_exists(branch):
        core.info.branch = branch
        core.info.version = ""

        core.update()
        Sig.core_remove()


@on(job.SET_CORE_VERSION)
def set_core_version(version: str) -> None:
    core = Repos.get_core()
    if core and core.info.version != version and core.version_exists(version):
        core.info.version = version

        core.update()
        Sig.core_remove()


@on(job.SET_REPO_BRANCH)
def set_repo_branch(repo_id: int, branch: str) -> None:
    repo = Repos.get(repo_id)
    if repo and repo.info.branch != branch and repo.branch_exists(branch):
        repo.info.branch = branch
        repo.info.version = ""

        repo.update()
        Sig.repos_remove()


@on(job.SET_REPO_VERSION)
def set_repo_version(repo_id: int, version: str) -> None:
    repo = Repos.get(repo_id)
    if repo and repo.info.version != version and repo.version_exists(version):
        repo.info.version = version

        repo.update()
        Sig.repos_remove()


@on(job.SET_REPO_PRIORITY)
def set_repo_priority(repo_id: int, priority: int) -> None:
    repo = Repos.get(repo_id)
    if repo and repo.info.priority != priority:
        repo.info.priority = priority

        Repos.sort()
        repo.update()
        Sig.repos_remove()


@on(job.REMOVE_PLUGINS)
def remove_plugins(names: List[str]) -> None:
    RemovedPlugins.add(names)


@on(job.RESTORE_PLUGINS)
def restore_plugins(names: List[str]) -> None:
    RemovedPlugins.remove(names)


@on(job.GET_REMOVED_PLUGINS)
def get_removed_plugins() -> List[str]:
    return RemovedPlugins.get()


@on(job.CLEAR_REMOVED_PLUGINS)
def clear_removed_plugins() -> None:
    RemovedPlugins.clear()


@on(job.INVALIDATE_REPOS_CACHE)
def invalidate_repos_cache() -> None:
    Sig.repos_remove()


@on(job.SET_ENV)
def set_env(key: str, value: str) -> None:
    set_key(CONF_TMP_PATH, key, value)
    if key not in environ:
        Sig.repos_remove()

    environ[key] = value


@on(job.UNSET_ENV)
def unset_env(key: str) -> None:
    unset_key(CONF_TMP_PATH, key)
    with suppress(KeyError):
        del environ[key]
        Sig.repos_remove()
