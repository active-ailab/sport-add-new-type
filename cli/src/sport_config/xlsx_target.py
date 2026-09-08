"""Resolve sports.xlsx for CLI commands and the local Web server."""
from dataclasses import dataclass
from pathlib import Path


COMMON_RELATIVE = Path("framework/engine/sportEngine/common")
XLSX_NAME = "sports.xlsx"
GENERATOR_NAME = "sport_gen.py"


class TargetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    xlsx: Path
    repo: Path = None
    generator: Path = None

    @property
    def can_generate(self):
        return self.generator is not None


def find_repo(start):
    current = Path(start).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".repo").is_dir():
            return candidate
    return None


def _from_repo(repo):
    common = repo / COMMON_RELATIVE
    xlsx = common / XLSX_NAME
    if not xlsx.is_file():
        raise TargetError("missing sports.xlsx: {}".format(xlsx))
    generator = common / GENERATOR_NAME
    return Target(xlsx, repo, generator if generator.is_file() else None)


def resolve_target(start):
    """Use a direct sports.xlsx first, then the firmware-standard location."""
    start = Path(start).expanduser().resolve()
    direct = start if start.is_file() else start / XLSX_NAME
    if direct.name == XLSX_NAME and direct.is_file():
        repo = find_repo(direct.parent)
        generator = repo / COMMON_RELATIVE / GENERATOR_NAME if repo else None
        return Target(direct, repo, generator if generator and generator.is_file() else None)
    repo = find_repo(start)
    if repo is None:
        raise TargetError("cannot find sports.xlsx or a repo root containing .repo from: {}".format(start))
    return _from_repo(repo)


def resolve_web_target(start):
    try:
        return resolve_target(start)
    except TargetError:
        return None


def selected_target(path):
    xlsx = Path(path).expanduser().resolve()
    if xlsx.name != XLSX_NAME or not xlsx.is_file():
        raise TargetError("only an existing sports.xlsx file can be selected: {}".format(path))
    repo = find_repo(xlsx.parent)
    generator = repo / COMMON_RELATIVE / GENERATOR_NAME if repo else None
    return Target(xlsx, repo, generator if generator and generator.is_file() else None)
