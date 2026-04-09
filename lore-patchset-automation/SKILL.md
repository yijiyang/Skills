---
name: lore-patchset-automation
description: Automate Linux patchset intake from lore.kernel.org using b4 and git am, then normalize commit messages by enforcing Signed-off-by trailers before Link and prefixing subjects with UPSTREAM or FROMLIST based on upstream branch presence checks. Use when asked to fetch/apply a lore patch series, keep mbox artifacts on failures, or mass-update applied patch commit metadata.
---

# Lore Patchset Automation

Execute each step below directly in the shell. Do not delegate to a script.

## Variables (resolve from user input before starting)

```
TARGET_REPO=<path to target git repo>
UPSTREAM_REPO=<path to upstream git repo>
PATCHSET_LINK=<lore.kernel.org URL or message-id>
PRIMARY_BRANCH=<upstream branch, e.g. master>
SECONDARY_BRANCH=<optional second upstream branch, or empty>
MBOX_BASENAME=lore-patchset          # or user-supplied name
LINK_TEMPLATE=https://lore.kernel.org/r/{msgid}
```

Sign-off identity: use `git -C $TARGET_REPO config user.name` + `user.email`.
Fallback if both are empty: `Yijie Yang <yijie.yang@oss.qualcomm.com>`.

---

## Step 1 — Verify prerequisites

```bash
command -v b4   || { echo "ERROR: b4 not found"; exit 1; }
command -v git  || { echo "ERROR: git not found"; exit 1; }
git -C "$TARGET_REPO"   rev-parse --is-inside-work-tree
git -C "$UPSTREAM_REPO" rev-parse --is-inside-work-tree
```

Optionally check target is clean:
```bash
git -C "$TARGET_REPO" status --porcelain
# If output is non-empty, stash or commit before continuing.
```

---

## Step 2 — Fetch patchset with b4

```bash
cd "$TARGET_REPO"
b4 am -o . -n "$MBOX_BASENAME" "$PATCHSET_LINK"
# Produces: ./<MBOX_BASENAME>.mbx  (and optionally ./<MBOX_BASENAME>.cover)
MBOX_PATH="$TARGET_REPO/${MBOX_BASENAME}.mbx"
```

---

## Step 3 — Count patches in the mbox

```bash
PATCH_COUNT=$(grep -c '^From ' "$MBOX_PATH")
echo "Patch count: $PATCH_COUNT"
```

---

## Step 4 — Apply with git am

```bash
git -C "$TARGET_REPO" am "$MBOX_PATH"
```

- On **success**: continue to Step 5.
- On **failure**: do NOT delete `$MBOX_PATH`. Abort and report the conflict:
  ```bash
  git -C "$TARGET_REPO" am --abort
  echo "git am failed. Mbox kept at: $MBOX_PATH"
  ```
  Stop here and ask the user to resolve conflicts manually.

---

## Step 5 — Collect applied commit hashes (oldest → newest)

```bash
COMMITS=$(git -C "$TARGET_REPO" rev-list --reverse --max-count="$PATCH_COUNT" HEAD)
# $COMMITS is a newline-separated list of $PATCH_COUNT hashes.
```

---

## Step 6 — Extract Message-IDs from the mbox (same order as patches)

```bash
MSGIDS=$(python3 - "$MBOX_PATH" <<'EOF'
import mailbox, re, sys
PATCH_RE = re.compile(r"\[PATCH[^\]]*\]", re.IGNORECASE)
mbox = mailbox.mbox(sys.argv[1])
entries = []
for msg in mbox:
    subj = (msg.get("Subject") or "").strip()
    if not PATCH_RE.search(subj):
        continue
    mid = (msg.get("Message-Id") or msg.get("Message-ID") or "").strip().strip("<>")
    if mid:
        entries.append(mid)
for mid in entries:
    print(mid)
EOF
)
```

---

## Step 7 — Load upstream subject sets

```bash
PRIMARY_SUBJECTS=$(git -C "$UPSTREAM_REPO" log "$PRIMARY_BRANCH" --format="%s")

# Only if SECONDARY_BRANCH is set:
if [ -n "$SECONDARY_BRANCH" ]; then
    SECONDARY_SUBJECTS=$(git -C "$UPSTREAM_REPO" log "$SECONDARY_BRANCH" --format="%s")
fi
```

---

## Step 8 — Rewrite each commit (loop)

For each pair of (commit_hash, message_id), run the following. Iterate using
`paste <(echo "$COMMITS") <(echo "$MSGIDS")` or equivalent.

```bash
PREFIX_RE='^(FROMLIST:[[:space:]]+|UPSTREAM:[[:space:]]+)'

while IFS=$'\t' read -r COMMIT MSGID; do
    SUBJECT=$(git -C "$TARGET_REPO" show -s --format="%s" "$COMMIT")
    BASE_SUBJECT=$(echo "$SUBJECT" | sed -E "s/$PREFIX_RE//")
    LINK="${LINK_TEMPLATE//\{msgid\}/$MSGID}"

    # Determine prefix
    if echo "$PRIMARY_SUBJECTS" | grep -qxF "$BASE_SUBJECT" || \
       echo "$PRIMARY_SUBJECTS" | grep -qxF "UPSTREAM: $BASE_SUBJECT" || \
       echo "$PRIMARY_SUBJECTS" | grep -qxF "FROMLIST: $BASE_SUBJECT"; then
        PREFIX="UPSTREAM: "
    elif [ -n "$SECONDARY_BRANCH" ] && \
         { echo "$SECONDARY_SUBJECTS" | grep -qxF "$BASE_SUBJECT" || \
           echo "$SECONDARY_SUBJECTS" | grep -qxF "UPSTREAM: $BASE_SUBJECT" || \
           echo "$SECONDARY_SUBJECTS" | grep -qxF "FROMLIST: $BASE_SUBJECT"; }; then
        PREFIX=""
    else
        PREFIX="FROMLIST: "
    fi

    # Resolve sign-off identity
    SOB_NAME=$(git -C "$TARGET_REPO" config user.name)
    SOB_EMAIL=$(git -C "$TARGET_REPO" config user.email)
    if [ -n "$SOB_NAME" ] && [ -n "$SOB_EMAIL" ]; then
        SIGNOFF="Signed-off-by: $SOB_NAME <$SOB_EMAIL>"
    else
        SIGNOFF="Signed-off-by: Yijie Yang <yijie.yang@oss.qualcomm.com>"
    fi

    # Rewrite commit message via git commit --amend using filter-branch for the range,
    # or amend each commit individually with git rebase -i automation:
    GIT_SEQUENCE_EDITOR="sed -i 's/^pick/reword/'" \
    GIT_EDITOR="python3 - '$BASE_SUBJECT' '$PREFIX' '$LINK' '$SIGNOFF'" \
    git -C "$TARGET_REPO" rebase -i "${COMMIT}^" 2>/dev/null || true
    # See note below for the recommended per-commit rewrite approach.

done < <(paste <(echo "$COMMITS") <(echo "$MSGIDS"))
```

### Recommended per-commit rewrite (cleaner than rebase loop)

Use `git filter-branch` over the applied range in one shot:

```bash
python3 - "$TARGET_REPO" "$PATCH_COUNT" \
    "$PRIMARY_BRANCH" "${SECONDARY_BRANCH:-}" \
    "$UPSTREAM_REPO" "$LINK_TEMPLATE" \
    <<'EOF'
import json, os, re, subprocess, sys, tempfile
from pathlib import Path

target, count, primary, secondary, upstream, link_tmpl = sys.argv[1:7]
count = int(count)
PREFIX_RE = re.compile(r"^(FROMLIST:\s+|UPSTREAM:\s+)")

def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

def subjects(repo, branch):
    return set(git(repo, "log", branch, "--format=%s").splitlines())

def base(s): return PREFIX_RE.sub("", s, count=1)
def found(sset, s):
    b = base(s)
    return b in sset or f"UPSTREAM: {b}" in sset or f"FROMLIST: {b}" in sset

primary_subs = subjects(upstream, primary)
secondary_subs = subjects(upstream, secondary) if secondary else None

commits = git(target, "rev-list", "--reverse", f"--max-count={count}", "HEAD").splitlines()
msgids  = []
import mailbox as mb
mbox_path = next(Path(target).glob("*.mbx"), None)
if mbox_path:
    PATCH_RE = re.compile(r"\[PATCH[^\]]*\]", re.IGNORECASE)
    for msg in mb.mbox(str(mbox_path)):
        subj = (msg.get("Subject") or "").strip()
        if not PATCH_RE.search(subj): continue
        mid = (msg.get("Message-Id") or msg.get("Message-ID") or "").strip().strip("<>")
        if mid: msgids.append(mid)

name  = git(target, "config", "user.name")  or "Yijie Yang"
email = git(target, "config", "user.email") or "yijie.yang@oss.qualcomm.com"
signoff = f"Signed-off-by: {name} <{email}>"

plan = {}
for commit, msgid in zip(commits, msgids):
    subj = git(target, "show", "-s", "--format=%s", commit)
    link = link_tmpl.replace("{msgid}", msgid)
    if found(primary_subs, subj):
        prefix = "UPSTREAM: "
    elif secondary_subs is not None and found(secondary_subs, subj):
        prefix = ""
    else:
        prefix = "FROMLIST: "
    plan[commit] = {"prefix": prefix, "link": link, "signoff": signoff}

MSG_FILTER = r'''
import json, os, re, sys
PREFIX_RE = re.compile(r"^(FROMLIST:\s+|UPSTREAM:\s+)")
mapping = json.load(open(sys.argv[1], encoding="utf-8"))
commit = os.environ.get("GIT_COMMIT", "")
msg = sys.stdin.read()
data = mapping.get(commit)
if not data:
    sys.stdout.write(msg); raise SystemExit(0)
lines = msg.splitlines()
prefix, link, signoff = data["prefix"], data["link"].strip(), data["signoff"].strip()
lines[0] = f"{prefix}{PREFIX_RE.sub('', lines[0], count=1)}"
lines = [l for l in lines if l.strip() not in (link, signoff)]
last_sob = max((i for i, l in enumerate(lines) if l.startswith("Signed-off-by:")), default=-1)
if last_sob >= 0:
    lines.insert(last_sob + 1, signoff)
    lines.insert(last_sob + 2, link)
else:
    if lines and lines[-1]: lines.append("")
    lines += [signoff, link]
out = "\n".join(lines)
if msg.endswith("\n"): out += "\n"
sys.stdout.write(out)
'''

import shutil, tempfile
td = Path(tempfile.mkdtemp(prefix="lore-rewrite-"))
map_f = td / "map.json"; map_f.write_text(json.dumps(plan))
flt_f = td / "filter.py"; flt_f.write_text(MSG_FILTER); flt_f.chmod(0o755)
env = {**os.environ, "FILTER_BRANCH_SQUELCH_WARNING": "1"}
subprocess.run(
    ["git", "filter-branch", "-f", "--msg-filter",
     f"python3 {flt_f} {map_f}", f"HEAD~{count}..HEAD"],
    cwd=target, env=env, check=True)
shutil.rmtree(td)
print("Rewrite complete.")
EOF
```

---

## Step 9 — Verify results

```bash
git -C "$TARGET_REPO" log --oneline -n "$PATCH_COUNT"
git -C "$TARGET_REPO" status --short --branch
```

Check that:
- Each subject starts with `UPSTREAM:` or `FROMLIST:`.
- Each commit message has `Signed-off-by:` **before** `Link:`.
- The sign-off appears exactly once per commit.

---

## Step 10 — Clean up artifacts

Remove mbox files after a successful apply (skip if you want to keep them):

```bash
rm -f "$TARGET_REPO/${MBOX_BASENAME}.mbx"
rm -f "$TARGET_REPO/${MBOX_BASENAME}.cover"
```

Keep them if `git am` failed or if the user requested `--keep-mbox-on-success` equivalent.

---

## Failure handling summary

| Failure point | Action |
|---|---|
| `b4 am` fails | Report error, stop. No mbox to keep. |
| `git am` fails | Run `git am --abort`, keep `.mbx`, report path, stop. |
| `filter-branch` fails | Report error; commits are applied but not rewritten. |

---

## Notes

- Strip existing `UPSTREAM:` / `FROMLIST:` prefixes before comparing subjects to upstream.
- A subject is considered upstream-present if the bare form, `UPSTREAM: <bare>`, or `FROMLIST: <bare>` appears in the branch log.
- `Signed-off-by:` must appear **before** `Link:` in every rewritten commit.
- The sign-off is deduplicated: insert once, remove duplicates first.
