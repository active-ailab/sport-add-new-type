"""Invoke the existing firmware sport generator from the resolved target."""
import subprocess
import sys

from .xlsx_target import TargetError


def generate(target, *, on_process=None, is_cancelled=None):
    if not target.can_generate:
        raise TargetError("cannot generate: selected sports.xlsx is not associated with sport_gen.py")
    if is_cancelled and is_cancelled():
        raise TargetError("sport_gen.py generation was interrupted")
    process = subprocess.Popen([sys.executable, target.generator.name], cwd=str(target.generator.parent))
    if on_process:
        on_process(process)
    try:
        if is_cancelled and is_cancelled() and process.poll() is None:
            process.terminate()
        returncode = process.wait()
    finally:
        if on_process:
            on_process(None)
    if is_cancelled and is_cancelled():
        raise TargetError("sport_gen.py generation was interrupted")
    if returncode:
        raise TargetError("sport_gen.py failed with exit {}".format(returncode))
    diff = subprocess.run(["git", "-C", str(target.generator.parent), "diff", "--stat"], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return diff.stdout.rstrip() or "git diff --stat: no unstaged diff"
