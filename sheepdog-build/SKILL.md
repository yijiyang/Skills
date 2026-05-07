---
name: sheepdog-build
description: Build a kernel image for any supported device using sheepdog on the remote build host. Transmits commits as patch files to the remote patch_dir, then lets sheepdog handle codebase alignment (fetch → checkout tag → apply patches → build). No git push.
license: BSD-3-Clause-Clear
compatibility: Requires SSH access to the remote build host and a local Linux kernel git repo
metadata:
  author: yijiyang
  version: "7.0.0"
  category: devops
  tags: sheepdog kernel build remote qcom
---

# Sheepdog Build

Build a kernel image for any supported device on the remote build host using sheepdog. Transmits the
commits to be built as patch files to the remote `patch_dir`. Sheepdog handles all
codebase alignment: fetches from the original `url`, checks out the configured `tag`
(or branch HEAD when `tag` is empty), and applies the patches.

**No git push is used.** The original `url`, `branch`, and `tag` in the slave config
are preserved; only `patch_dir` is overridden in the temp config.

## How alignment works

Sheepdog's `sync_main_kernel_code()` fetches from `url`, resets to `tag` (or branch HEAD
when `tag` is empty), then applies each patch in `patch_dir` in alphabetical order.
The result is the compilation tree at the configured base plus all submitted patch files.

## Constraints (non-negotiable)

- **Never create or modify files inside `LOCAL_REPO`** — the local kernel source tree is
  read-only; local temp files outside the repo (e.g. `/tmp`) are acceptable
- **Never modify the local repo state** — no `git fetch`, rebase, amend, checkout, reset,
  or source edits inside `LOCAL_REPO`
- **No git push** — commit transmission must be file-based (`git format-patch` + rsync)
- **On compilation error: search local commits for dependency candidates first** — do not
  fix or modify the compilation code base directly; only report if no dependency commits
  are found

## Variables (all required — resolve from user prompt before running)

All `<PLACEHOLDER>` values must be substituted with real values before executing any command.

| Variable | Description |
|---|---|
| `LOCAL_REPO` | Local kernel source tree path |
| `BASE_COMMIT` | Commit/tag to generate patches from — caller provides this (e.g. the base branch tip) |
| `REMOTE_HOST` | Remote build host (`user@hostname`) |
| `REMOTE_SHEEPDOG` | Sheepdog workspace path on the remote host |
| `REMOTE_LINUX` | Kernel repo path on the remote host (e.g. `<REMOTE_SHEEPDOG>/private-kernel`) |
| `CHIP_CONFIG` | Slave config name, e.g. `maili` or `maili-qrd` |
| `REMOTE_PATCH_DIR` | Remote directory to hold patch files — e.g. `<REMOTE_SHEEPDOG>/patches/<CHIP_CONFIG>-build-tmp` |

---

## Step 1 — Generate patch files locally

Run locally. Creates one `.patch` file per commit between `BASE_COMMIT` and the current
`LOCAL_REPO` HEAD. Output goes to a temp directory outside the repo.

```bash
rm -rf /tmp/sheepdog-patches-<CHIP_CONFIG>
mkdir -p /tmp/sheepdog-patches-<CHIP_CONFIG>

git -C <LOCAL_REPO> format-patch <BASE_COMMIT>..HEAD \
  -o /tmp/sheepdog-patches-<CHIP_CONFIG>/
```

If `format-patch` produces no files, there are no commits beyond `BASE_COMMIT` — stop and
report to the leader.

---

## Step 2 — Transfer patch files to remote

```bash
ssh <REMOTE_HOST> "mkdir -p <REMOTE_PATCH_DIR>"

rsync -av --delete /tmp/sheepdog-patches-<CHIP_CONFIG>/ \
  "<REMOTE_HOST>:<REMOTE_PATCH_DIR>/"
```

---

## Step 3 — Create temp config, run sheepdog, clean up — single SSH session

Override only `patch_dir` in the temp config. `url`, `branch`, and `tag` are preserved
from the original slave config so sheepdog fetches from upstream and checks out the
configured base.

```bash
ssh <REMOTE_HOST> "
set -e

# Write temp config (override patch_dir only)
python3 - <<'PYEOF'
import configparser
src = '<REMOTE_SHEEPDOG>/config/<CHIP_CONFIG>-slave.ini'
dst = '<REMOTE_SHEEPDOG>/config/<CHIP_CONFIG>-build-tmp.ini'
c = configparser.ConfigParser()
c.read(src)
c['PATCH']['patch_dir'] = '<REMOTE_PATCH_DIR>'
c.write(open(dst, 'w'))
PYEOF

# Run sheepdog — fetches from url, checks out tag/branch, applies patches, builds
cd <REMOTE_SHEEPDOG>
timeout 1500 python3 sheepdog-slave.py \
  --config config/<CHIP_CONFIG>-build-tmp.ini \
  --local private-kernel \
  2>&1 | tee <REMOTE_SHEEPDOG>/linux-sheepdog-slave.log

# Report result — clean up patch_dir only on success so a fix patch can be
# dropped in and sheepdog re-run directly without a full format-patch + rsync
if grep -q 'Slave successful!' <REMOTE_SHEEPDOG>/linux-sheepdog-slave.log; then
  rm -f <REMOTE_SHEEPDOG>/config/<CHIP_CONFIG>-build-tmp.ini
  rm -rf <REMOTE_PATCH_DIR>
  echo 'BUILD_SUCCEEDED'
else
  rm -f <REMOTE_SHEEPDOG>/config/<CHIP_CONFIG>-build-tmp.ini
  grep -E 'ERROR|error:|undefined reference|fatal error' \
    <REMOTE_SHEEPDOG>/linux-sheepdog-slave.log | tail -20
  echo 'BUILD_FAILED'
fi
"
```

---

## Step 4 — Parse output and report to leader

Check the output of Step 3 for `BUILD_SUCCEEDED` or `BUILD_FAILED`.

### On success

```
=== BUILD SUCCEEDED ===
boot.img: <REMOTE_SHEEPDOG>/boot.img
```

### On compilation error — search local commits for dependencies first

Extract error lines from the Step 3 output, then search `<LOCAL_REPO>` git history:

```bash
for f in <error files from output>; do
  git -C <LOCAL_REPO> log --oneline -200 -- "$f" 2>/dev/null
done
for sym in <undefined symbols from output>; do
  git -C <LOCAL_REPO> log --oneline -200 -S "$sym" 2>/dev/null
done
```

**Decision after search:**

- Commits found: report them + the error lines to the leader via `SendMessage`.
  The leader decides whether to apply them.
- No commits found: report raw compilation errors to the leader.

**Do NOT rerun the build or modify the source tree.**

---

## Quick-reference decision table

| Situation | Steps to run |
|---|---|
| Normal build | 1 → 2 → 3 → 4 |
| No commits beyond BASE_COMMIT | Stop after Step 1; report to leader |
| Remote transfer failed | Re-check SSH/rsync; verify `<REMOTE_PATCH_DIR>` is writable |
| Compilation error, deps found | Report candidate commits + errors to leader; stop |
| Compilation error, no deps | Report raw errors to leader; stop |
