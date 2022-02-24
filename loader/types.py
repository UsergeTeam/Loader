from typing import List

from git import Commit


class RepoInfo:
    def __init__(self, id_: int, priority: int, branch: str,
                 version: str, url: str):
        self.id = id_
        self.priority = priority
        self.branch = branch
        self.version = version
        self.url = url
        self.count = 0
        self.branches = set()

    def __repr__(self) -> str:
        return (f"<RepoInfo id={self.id}, priority={self.priority}, "
                f"branch={self.branch}, count={self.count}, url={self.url}>")


class Update:
    def __init__(self, summary: str, author: str, version: str,
                 count: int, url: str):
        self.summary = summary
        self.author = author
        self.version = version
        self.count = count
        self.url = url

    @classmethod
    def parse(cls, repo_url: str, commit: Commit) -> 'Update':
        summary = str(commit.summary)
        author = commit.author.name
        version = commit.hexsha
        count = commit.count()
        url = repo_url + "/commit/" + version

        return cls(summary, author, version, count, url)

    def __repr__(self) -> str:
        return (f"<Update summary={self.summary}, author={self.author}, "
                f"version={self.version}, count={self.count}, url={self.url}>")


class Constraint:
    def __init__(self, type_: str, data: List[str]):
        self.type = type_
        self.data = data

    def __repr__(self) -> str:
        return f"<Constraint type={self.type}, data={self.data}>"
