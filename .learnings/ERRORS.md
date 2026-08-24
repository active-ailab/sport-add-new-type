# Errors

Owner: cs-dongqi@zepp.com  
Organization: Active.Bu

Command failures and integration errors.

---

## [ERR-20260824-006] cache-cleanup-command-rejected

**Logged**: 2026-08-24T15:56:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The environment rejected a recursive forced deletion while cleaning an untracked Python cache directory.

### Error
```
rm -rf .../cli/src/__pycache__
```

### Context
- The bytecode file was already removed from the amended commit.
- Only the untracked local cache remained.

### Suggested Fix
Delete the known cache file with a non-recursive, explicit operation.

### Metadata
- Reproducible: yes
- Related Files: cli/src/__pycache__/sport_proto.cpython-38.pyc

---

## [ERR-20260824-001] unittest-import-path

**Logged**: 2026-08-24T12:25:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
Direct unittest discovery does not read pytest's `pythonpath` setting.

### Error
```
ModuleNotFoundError: No module named 'sport_proto'
```

### Context
- Command ran from the project root with tests under `cli/tests`.
- The source module is located in `cli/src`.

### Suggested Fix
Run unittest with `PYTHONPATH=cli/src`, or use pytest with the configured project metadata.

### Metadata
- Reproducible: yes
- Related Files: cli/tests/test_sport_proto.py

---

## [ERR-20260824-002] shell-entrypoint-mode

**Logged**: 2026-08-24T12:30:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The newly added shell entrypoint lacked its executable mode during direct validation.

### Error
```
permission denied: cli/bin/sport-proto
```

### Context
- Unit tests and shell syntax checks passed.
- Direct invocation requires the executable bit in addition to the shebang.

### Suggested Fix
Set executable mode for `cli/bin/sport-proto` and `install.sh` before entrypoint validation.

### Metadata
- Reproducible: yes
- Related Files: cli/bin/sport-proto, install.sh

---

## [ERR-20260824-003] git-diff-two-paths

**Logged**: 2026-08-24T12:35:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
Two paths passed to `git diff --` compare each other instead of checking each path against Git state.

### Error
```
git diff -- <source.pb.c> <header.pb.h>
```

### Context
- The command emitted a misleading C-versus-header diff during preview validation.
- It did not alter the checked-out files.

### Suggested Fix
Use `git status --short -- <paths>` or individual `git diff --quiet -- <path>` checks to verify preview non-mutation.

### Metadata
- Reproducible: yes
- Related Files: packages/services/sport/src/phn/phn_proto/PHN.pb.c, packages/services/sport/include/phn/PHN.pb.h

---

## [ERR-20260824-004] repo-root-not-git-worktree

**Logged**: 2026-08-24T12:40:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The `.repo` workspace root is not itself a Git worktree.

### Error
```
fatal: not a git repository (or any of the parent directories): .git
```

### Context
- `abs-stable` correctly contains `.repo/` for CLI root discovery.
- The sport service is a nested Git project and must be checked from its own directory.

### Suggested Fix
Use `.repo` only for root discovery and run Git validation in the affected nested project, such as `packages/services/sport`.

### Metadata
- Reproducible: yes
- Related Files: packages/services/sport

---

## [ERR-20260824-005] learning-log-bootstrap

**Logged**: 2026-08-24T12:45:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
A multi-file patch was rejected because the project learning log did not yet exist.

### Error
```
Failed to read file to update .learnings/LEARNINGS.md
```

### Context
- Error logging had been initialized, but the separate learning log had not.
- The rejected patch made no source or documentation changes.

### Suggested Fix
Initialize all required learning files before appending a correction entry.

### Metadata
- Reproducible: yes
- Related Files: .learnings/LEARNINGS.md

---
