"""CLI for generating nanopb artifacts owned by packages/services/sport."""

import argparse
import difflib
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable, List, Optional, Sequence


VERSION = "0.1.0"
SPORT_ROOT = Path("packages/services/sport")
GENERATOR_RELATIVE = Path("framework/utils/nanopb/generator/nanopb_generator.py")


@dataclass(frozen=True)
class Profile:
    name: str
    proto: Path
    options: Optional[Path]
    source: Path
    header: Path


def _profile(name: str, proto: str, options: Optional[str], source: str, header: str) -> Profile:
    return Profile(name, Path(proto), Path(options) if options else None, Path(source), Path(header))


PROFILES = (
    _profile("sport_settings", "packages/services/sport/settings/sport_settings.proto", "packages/services/sport/settings/sport_settings.options", "packages/services/sport/settings/sport_settings.pb.c", "packages/services/sport/settings/sport_settings.pb.h"),
    _profile("equipment", "packages/services/sport/src/equipment/equipment.proto", "packages/services/sport/src/equipment/equipment.options", "packages/services/sport/src/equipment/equipment.pb.c", "packages/services/sport/include/equipment/equipment.pb.h"),
    _profile("lactate_data", "packages/services/sport/src/gomore_service/proto/lactate_data.proto", "packages/services/sport/src/gomore_service/proto/lactate_data.options", "packages/services/sport/src/gomore_service/proto/lactate_data.pb.c", "packages/services/sport/include/gomore_service/lactate_data.pb.h"),
    _profile("PHN", "packages/services/sport/src/phn/phn_proto/PHN.proto", "packages/services/sport/src/phn/phn_proto/PHN.options", "packages/services/sport/src/phn/phn_proto/PHN.pb.c", "packages/services/sport/include/phn/PHN.pb.h"),
    _profile("phn_plan", "packages/services/sport/src/phn/phn_proto/phn_plan.proto", "packages/services/sport/src/phn/phn_proto/phn_plan.options", "packages/services/sport/src/phn/phn_proto/phn_plan.pb.c", "packages/services/sport/include/phn/phn_plan.pb.h"),
    _profile("phn_record", "packages/services/sport/src/phn/phn_proto/phn_record.proto", "packages/services/sport/src/phn/phn_proto/phn_record.options", "packages/services/sport/src/phn/phn_proto/phn_record.pb.c", "packages/services/sport/include/phn/phn_record.pb.h"),
    _profile("phn_sport_reminder", "packages/services/sport/src/phn/phn_proto/phn_sport_reminder.proto", None, "packages/services/sport/src/phn/phn_proto/phn_sport_reminder.pb.c", "packages/services/sport/include/phn/phn_sport_reminder.pb.h"),
    _profile("readiness", "packages/services/sport/src/readiness/readiness.proto", None, "packages/services/sport/src/readiness/readiness.pb.c", "packages/services/sport/include/readiness/readiness.pb.h"),
    _profile("sport_data_page", "packages/services/sport/src/sport_data_page/sport_page_proto/sport_data_page.proto", "packages/services/sport/src/sport_data_page/sport_page_proto/sport_data_page.options", "packages/services/sport/src/sport_data_page/sport_page_proto/sport_data_page.pb.c", "packages/services/sport/include/sport_data_page/sport_data_page.pb.h"),
    _profile("sport_effect", "packages/services/sport/src/sport_effect.proto", "packages/services/sport/src/sport_effect.options", "packages/services/sport/src/sport_effect.pb.c", "packages/services/sport/include/sport_effect.pb.h"),
    _profile("treadmill_setting", "packages/services/sport/src/treadmill_setting/treadmill_setting.proto", None, "packages/services/sport/src/treadmill_setting/treadmill_setting.pb.c", "packages/services/sport/include/treadmill_setting/treadmill_setting.pb.h"),
    _profile("sport_summary", "packages/services/sport/summary/sport_summary.proto", "packages/services/sport/summary/sport_summary.options", "packages/services/sport/summary/sport_summary.pb.c", "packages/services/sport/summary/sport_summary.pb.h"),
)
PROFILE_BY_NAME = {profile.name: profile for profile in PROFILES}
PROFILE_BY_PROTO = {profile.proto: profile for profile in PROFILES}


class SportProtoError(RuntimeError):
    pass


def normalize_short_options(argv: Sequence[str]) -> List[str]:
    """Make one-letter short options case-insensitive without changing values."""
    normalized = []
    for argument in argv:
        if len(argument) >= 2 and argument[0] == "-" and argument[1] != "-" and argument[1].isalpha():
            normalized.append("-" + argument[1].lower() + argument[2:])
        else:
            normalized.append(argument)
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate nanopb artifacts for packages/services/sport.",
        epilog="流程：先使用 -l 获取 Profile，再使用 -p 预览；确认后追加 -w 回写。",
    )
    parser.add_argument("-v", "--version", action="version", version="sport-proto " + VERSION)
    parser.add_argument("-r", "--repo", metavar="PATH", help="repo root or a directory inside it")
    parser.add_argument("-l", "--list", action="store_true", help="list existing sport proto files")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("-p", "--profile", action="append", metavar="NAME", help="profile to generate; may be repeated")
    selection.add_argument("-a", "--all", action="store_true", help="generate all existing supported profiles")
    parser.add_argument("-w", "--write", action="store_true", help="copy generated files from /tmp into mapped targets")
    return parser


def find_repo(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".repo").is_dir():
            return candidate
    raise SportProtoError("cannot find a repo root containing .repo from: {}".format(start))


def require_layout(repo: Path) -> Path:
    sport_dir = repo / SPORT_ROOT
    generator = repo / GENERATOR_RELATIVE
    if not sport_dir.is_dir():
        raise SportProtoError("missing sport service directory: {}".format(sport_dir))
    if not generator.is_file():
        raise SportProtoError("missing nanopb generator: {}".format(generator))
    return generator


def list_proto_files(repo: Path) -> List[Path]:
    sport_dir = repo / SPORT_ROOT
    return sorted(path.relative_to(repo) for path in sport_dir.rglob("*.proto") if path.is_file())


def command_output(command: Sequence[str], cwd: Optional[Path] = None) -> str:
    try:
        result = subprocess.run(command, cwd=str(cwd) if cwd else None, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        return "unavailable ({})".format(exc)
    output = result.stdout.strip()
    return output if output else "unavailable (exit {})".format(result.returncode)


def print_summary(repo: Path, generator: Path) -> None:
    proto_count = len(list_proto_files(repo))
    protobuf_version = command_output([sys.executable, "-c", "import google.protobuf; print(google.protobuf.__version__)"])
    print("repo: {}".format(repo))
    print("generator: {}".format(generator))
    print("protoc: {}".format(command_output(["protoc", "--version"])))
    print("python protobuf: {}".format(protobuf_version))
    print("sport proto count: {}".format(proto_count))
    print("use -l to list proto files; use -p NAME or -a to generate")


def select_profiles(repo: Path, profiles: Optional[Sequence[str]], all_profiles: bool) -> List[Profile]:
    if all_profiles:
        return [profile for profile in PROFILES if (repo / profile.proto).is_file()]
    selected = []
    for name in profiles or ():
        profile = PROFILE_BY_NAME.get(name)
        if profile is None:
            raise SportProtoError("unknown profile: {}".format(name))
        if not (repo / profile.proto).is_file():
            raise SportProtoError("profile proto does not exist: {}".format(repo / profile.proto))
        selected.append(profile)
    return selected


def text(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)


def print_diff(label: str, generated: Path, target: Path) -> None:
    before = text(target) if target.is_file() else []
    after = text(generated)
    diff = list(difflib.unified_diff(before, after, fromfile=str(target), tofile=str(generated)))
    if diff:
        print("".join(diff), end="")
    else:
        print("{}: no diff".format(label))


def atomic_copy(source: Path, destination: Path) -> None:
    if not destination.is_file():
        raise SportProtoError("mapped output does not exist: {}".format(destination))
    descriptor, temporary_name = tempfile.mkstemp(prefix=".sport-proto-", dir=str(destination.parent))
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(str(source), str(temporary))
        os.replace(str(temporary), str(destination))
    finally:
        if temporary.exists():
            temporary.unlink()


def staged_paths(generator_dir: Path, profile: Profile) -> List[Path]:
    stem = profile.proto.stem
    paths = [generator_dir / profile.proto.name, generator_dir / (stem + ".pb.c"), generator_dir / (stem + ".pb.h")]
    if profile.options:
        paths.append(generator_dir / profile.options.name)
    return paths


def generate_profile(repo: Path, generator: Path, profile: Profile, tmp_root: Path, write: bool) -> None:
    generator_dir = generator.parent
    source_proto = repo / profile.proto
    source_options = repo / profile.options if profile.options else None
    staged = staged_paths(generator_dir, profile)
    collisions = [path for path in staged if path.exists()]
    if collisions:
        raise SportProtoError("generator directory is not clean for {}: {}".format(profile.name, ", ".join(str(path) for path in collisions)))

    output_dir = tmp_root / profile.name
    output_dir.mkdir(parents=True, exist_ok=False)
    staged_proto = generator_dir / source_proto.name
    staged_options = generator_dir / source_options.name if source_options else None
    generated_source = generator_dir / (source_proto.stem + ".pb.c")
    generated_header = generator_dir / (source_proto.stem + ".pb.h")
    temporary_source = output_dir / generated_source.name
    temporary_header = output_dir / generated_header.name

    print("profile: {}".format(profile.name))
    try:
        shutil.copy2(str(source_proto), str(staged_proto))
        if source_options and staged_options:
            shutil.copy2(str(source_options), str(staged_options))
        result = subprocess.run([sys.executable, generator.name, staged_proto.name], cwd=str(generator_dir), check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            raise SportProtoError("nanopb failed for {}:\n{}".format(profile.name, result.stdout.strip()))
        if not generated_source.is_file() or not generated_header.is_file():
            raise SportProtoError("nanopb did not create paired outputs for {}".format(profile.name))
        shutil.move(str(generated_source), str(temporary_source))
        shutil.move(str(generated_header), str(temporary_header))
    finally:
        for path in staged:
            if path.exists():
                path.unlink()

    target_source = repo / profile.source
    target_header = repo / profile.header
    print_diff(profile.name + " source", temporary_source, target_source)
    print_diff(profile.name + " header", temporary_header, target_header)
    if write:
        atomic_copy(temporary_source, target_source)
        atomic_copy(temporary_header, target_header)
        print("output source: {} ({})".format(profile.source, target_source))
        print("output header: {} ({})".format(profile.header, target_header))
    else:
        print("temporary source: {}".format(temporary_source))
        print("temporary header: {}".format(temporary_header))


def run(arguments: Sequence[str], cwd: Optional[Path] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_short_options(arguments))
    start = Path(args.repo) if args.repo else (cwd or Path.cwd())
    try:
        repo = find_repo(start)
        generator = require_layout(repo)
        if args.list:
            proto_files = list_proto_files(repo)
            rows = [(PROFILE_BY_PROTO.get(path).name if PROFILE_BY_PROTO.get(path) else "-", path) for path in proto_files]
            width = max([len(profile) for profile, _ in rows], default=0)
            for profile, path in rows:
                print("{}  {}".format(profile.ljust(width), path))
            print("count: {}".format(len(proto_files)))
            return 0
        if not args.profile and not args.all:
            print_summary(repo, generator)
            return 0
        selected = select_profiles(repo, args.profile, args.all)
        if not selected:
            raise SportProtoError("no supported sport proto profiles exist in: {}".format(repo / SPORT_ROOT))
        tmp_root = Path(tempfile.mkdtemp(prefix="sport-proto-", dir="/tmp"))
        for profile in selected:
            generate_profile(repo, generator, profile, tmp_root, args.write)
        return 0
    except SportProtoError as exc:
        parser.error(str(exc))
    return 2


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
