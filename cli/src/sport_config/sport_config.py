"""sport-config command entry point."""
import argparse
from pathlib import Path
import sys

from .xlsx_check import check_target
from .xlsx_generate import generate
from .xlsx_target import TargetError, resolve_target, resolve_web_target
from .xml_report import write_report


VERSION = "0.2.0"
ACTION_ALIASES = {
    "-c": "check", "-check": "check", "check": "check",
    "-g": "gen", "-gen": "gen", "gen": "gen",
    "-a": "add", "add": "add",
}


def normalize_arguments(argv):
    normalized = []
    for argument in argv:
        if len(argument) >= 2 and argument[0] == "-" and argument[1] != "-" and argument[1].isalpha():
            argument = "-" + argument[1].lower() + argument[2:]
        normalized.append(ACTION_ALIASES.get(argument.lower(), argument))
    return normalized


def build_parser():
    parser = argparse.ArgumentParser(
        description="Check, generate, and edit sports.xlsx through the local Web UI.",
        usage="sport-config [-h] [-v] ACTION [REPORT_DIR] [-r PATH]",
        epilog="ACTION: -c/check, -g/gen, -a/add. REPORT_DIR only applies to -c.",
    )
    parser.add_argument("-v", "--version", action="version", version="sport-config " + VERSION)
    parser.add_argument("command", choices=("check", "gen", "add"), metavar="ACTION")
    parser.add_argument("report_dir", nargs="?", metavar="REPORT_DIR", help="-c XML report directory only")
    parser.add_argument("-r", "--repo", metavar="PATH", help="sports.xlsx target resolution start directory")
    return parser


def _target(args, cwd):
    return resolve_target(args.repo or cwd)


def _check(args, cwd):
    target = _target(args, cwd)
    result = check_target(target)
    report = write_report(result, args.report_dir or cwd)
    print("报告生成成功：{}".format(report))
    return 2 if result.error_count else 0


def _generate(args, cwd):
    if args.report_dir:
        raise TargetError("REPORT_DIR is only supported by -c/check")
    target = _target(args, cwd)
    result = check_target(target)
    if result.error_count:
        raise TargetError("sports.xlsx check failed: {} error(s)".format(result.error_count))
    print("PASS: sport_gen.py completed")
    print(generate(target))
    return 0


def _add(args, cwd):
    if args.report_dir:
        raise TargetError("REPORT_DIR is only supported by -c/check")
    from .web_app import run as run_web
    run_web(resolve_web_target(args.repo or cwd))
    return 0


def run(arguments, cwd=None):
    parser = build_parser()
    args = parser.parse_args(normalize_arguments(arguments))
    cwd = Path(cwd or Path.cwd()).resolve()
    try:
        if args.command == "check":
            return _check(args, cwd)
        if args.command == "gen":
            return _generate(args, cwd)
        return _add(args, cwd)
    except (TargetError, RuntimeError) as exc:
        parser.error(str(exc))
    return 2


def main():
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
