"""Invoke the existing firmware sport generator from the resolved target."""
import subprocess
import sys

from .xlsx_target import TargetError


def generate(target):
    if not target.can_generate:
        raise TargetError("cannot generate: selected sports.xlsx is not associated with sport_gen.py")
    result = subprocess.run([sys.executable, target.generator.name], cwd=str(target.generator.parent), check=False)
    if result.returncode:
        raise TargetError("sport_gen.py failed with exit {}".format(result.returncode))
    diff = subprocess.run(["git", "-C", str(target.generator.parent), "diff", "--stat"], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return diff.stdout.rstrip() or "git diff --stat: no unstaged diff"
