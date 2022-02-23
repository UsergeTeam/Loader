__all__ = [
    'restart',
    'fetch_core',
    'fetch_repos',
    'get_core',
    'get_repos',
    'add_repo',
    'remove_repo',
    'get_core_new_commits',
    'get_core_old_commits',
    'get_repo_new_commits',
    'get_repo_old_commits',
    'set_core_branch',
    'set_core_version',
    'set_repo_branch',
    'set_repo_version',
    'set_repo_priority',
    'add_constraints',
    'remove_constraints',
    'get_constraints',
    'clear_constraints',
    'set_env',
    'unset_env']

from typing import List, Optional

from loader.job import *
from loader.types import RepoInfo, Update
from .connection import send_and_wait, send_and_async_wait


def restart(hard: bool = False) -> None:
    send_and_wait(HARD_RESTART if hard else SOFT_RESTART)


async def fetch_core() -> None:
    return await send_and_async_wait(FETCH_CORE)


async def fetch_repos() -> None:
    return await send_and_async_wait(FETCH_REPOS)


async def get_core() -> Optional[RepoInfo]:
    return await send_and_async_wait(GET_CORE)


async def get_repos() -> List[RepoInfo]:
    return await send_and_async_wait(GET_REPOS)


async def add_repo(priority: int, branch: str, url: str) -> None:
    return await send_and_async_wait(ADD_REPO, priority, branch, url)


async def remove_repo(repo_id: int) -> None:
    return await send_and_async_wait(REMOVE_REPO, repo_id)


async def get_core_new_commits() -> Optional[List[Update]]:
    return await send_and_async_wait(GET_CORE_NEW_COMMITS)


async def get_core_old_commits(limit: int) -> Optional[List[Update]]:
    return await send_and_async_wait(GET_CORE_OLD_COMMITS, limit)


async def get_repo_new_commits(repo_id: int) -> Optional[List[Update]]:
    return await send_and_async_wait(GET_REPO_NEW_COMMITS, repo_id)


async def get_repo_old_commits(repo_id: int, limit: int) -> Optional[List[Update]]:
    return await send_and_async_wait(GET_REPO_OLD_COMMITS, repo_id, limit)


async def set_core_branch(branch: str) -> None:
    return await send_and_async_wait(SET_CORE_BRANCH, branch)


async def set_core_version(version: str) -> bool:
    return await send_and_async_wait(SET_CORE_VERSION, version)


async def set_repo_branch(repo_id: int, branch: str) -> None:
    return await send_and_async_wait(SET_REPO_BRANCH, repo_id, branch)


async def set_repo_version(repo_id: int, version: str) -> bool:
    return await send_and_async_wait(SET_REPO_VERSION, repo_id, version)


async def set_repo_priority(repo_id: int, priority: int) -> None:
    return await send_and_async_wait(SET_REPO_PRIORITY, repo_id, priority)


async def add_constraints(c_type: str, data: List[str]) -> None:
    return await send_and_async_wait(ADD_CONSTRAINTS, c_type, data)


async def remove_constraints(c_type: Optional[str], data: List[str]) -> None:
    return await send_and_async_wait(REMOVE_CONSTRAINTS, c_type, data)


async def get_constraints() -> List[str]:
    return await send_and_async_wait(GET_CONSTRAINTS)


async def clear_constraints(c_type: Optional[str]) -> None:
    return await send_and_async_wait(CLEAR_CONSTRAINTS, c_type)


async def set_env(key: str, value: str) -> bool:
    return await send_and_async_wait(SET_ENV, key, value)


async def unset_env(key: str) -> bool:
    return await send_and_async_wait(UNSET_ENV, key)
