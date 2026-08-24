# Learnings

Owner: cs-dongqi@zepp.com  
Organization: Active.Bu

Corrections, insights, and knowledge gaps captured during development.

---

## [LRN-20260824-006] correction

**Logged**: 2026-08-24T12:45:00+08:00
**Priority**: medium
**Status**: applied
**Area**: cli

### Summary
Profile names must be discoverable from `-l` and equal the proto filename without `.proto`.

### Details
Path-only listing did not expose valid `-p` values. The CLI now emits the profile beside each discovered proto and uses the basename-without-extension as its profile identity.

### Suggested Action
Keep profile names mechanically derived from their proto input name and test `-L` output together with `-P <profile>` execution.

### Metadata
- Source: user_feedback
- Related Files: cli/src/sport_proto.py
- Tags: cli, profiles, discoverability

---

## [LRN-20260824-007] correction

**Logged**: 2026-08-24T12:50:00+08:00
**Priority**: low
**Status**: applied
**Area**: cli

### Summary
Profile labels in `-l` output are left-aligned to the longest displayed profile.

### Details
The profile-to-proto mapping is intended for direct terminal use, so the Profile column needs deterministic padding before the relative path.

### Suggested Action
Calculate the display width from the current rows and print two spaces between the padded Profile and proto path.

### Metadata
- Source: user_feedback
- Related Files: cli/src/sport_proto.py
- Tags: cli, formatting, list

---

## [LRN-20260824-008] correction

**Logged**: 2026-08-24T13:00:00+08:00
**Priority**: low
**Status**: applied
**Area**: cli

### Summary
Command help stays concise; operational examples belong in README.

### Details
The requested workflow documentation belongs in the project README, while `-h` should remain a compact reference for parameters.

### Suggested Action
Do not add workflow examples to argparse help; keep README as the detailed usage guide.

### Metadata
- Source: user_feedback
- Related Files: README.md, cli/src/sport_proto.py
- Tags: cli, help, readme

---

## [LRN-20260824-009] correction

**Logged**: 2026-08-24T13:05:00+08:00
**Priority**: low
**Status**: applied
**Area**: cli

### Summary
Command help includes a concise workflow statement without command examples.

### Details
The CLI help now states the list, preview, write sequence in one sentence, while README remains the source for executable examples.

### Suggested Action
Keep help workflow prose short and avoid duplicating README command blocks.

### Metadata
- Source: user_feedback
- Related Files: cli/src/sport_proto.py, README.md
- Tags: cli, help, workflow

---
