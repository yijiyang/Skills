#!/usr/bin/env python3
"""
Automate patchset intake from lore/b4 for a target git repository.

Workflow:
1. Fetch patchset mbox with b4.
2. Apply with git am.
3. Ensure trailers are normalized: keep all Signed-off-by trailers before a single
   "Link: <URL>" trailer for each applied patch.
4. Prefix commit subject according to upstream presence:
   - If commit subject exists in upstream primary branch: prefix "UPSTREAM: "
   - Else if missing in both primary and secondary branch (if provided): prefix "FROMLIST: "

Notes:
- History rewrite is performed with git filter-branch on the newly applied commits only.
- If git am fails, the fetched mbox is intentionally kept for manual resolution.
"""

from __future__ import annotations

import argparse
import json
import logging
import mailbox
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


LOG = logging.getLogger("lore_patchset_automation")
PATCH_SERIES_SUBJECT_RE = re.compile(r"\[PATCH[^\]]*?(\d+)\s*/\s*(\d+)[^\]]*\]", re.IGNORECASE)
PATCH_ANY_SUBJECT_RE = re.compile(r"\[PATCH[^\]]*\]", re.IGNORECASE)
PREFIX_RE = re.compile(r"^(FROMLIST:\s+|UPSTREAM:\s+)")
FALLBACK_SIGNOFF_IDENTITY = "Yijie Yang <yijie.yang@oss.qualcomm.com>"


def run(
    cmd: List[str],
    cwd: Optional[Path] = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    LOG.debug("Running command: %s (cwd=%s)", " ".join(cmd), cwd or os.getcwd())
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=repo, check=check)


@dataclass
class PatchEntry:
    index: int
    total: int
    subject: str
    message_id: str


def parse_patch_entries_from_mbox(mbox_path: Path) -> List[PatchEntry]:
    entries: List[PatchEntry] = []
    single_patch_subjects: List[tuple[str, str]] = []
    mbox = mailbox.mbox(str(mbox_path))
    for msg in mbox:
        subject = (msg.get("Subject") or "").strip()
        series_match = PATCH_SERIES_SUBJECT_RE.search(subject)
        has_patch_tag = PATCH_ANY_SUBJECT_RE.search(subject)
        if not has_patch_tag:
            continue
        message_id = (msg.get("Message-Id") or msg.get("Message-ID") or "").strip()
        if not message_id:
            continue
        if series_match:
            entries.append(
                PatchEntry(
                    index=int(series_match.group(1)),
                    total=int(series_match.group(2)),
                    subject=subject,
                    message_id=message_id.strip("<>"),
                )
            )
        else:
            single_patch_subjects.append((subject, message_id.strip("<>")))

    if entries:
        entries.sort(key=lambda e: e.index)
        expected = entries[-1].total
        if len(entries) != expected:
            raise RuntimeError(
                f"Parsed {len(entries)} patch entries, but expected {expected} from mbox series."
            )
    elif single_patch_subjects:
        total = len(single_patch_subjects)
        entries = [
            PatchEntry(index=i, total=total, subject=subject, message_id=msgid)
            for i, (subject, msgid) in enumerate(single_patch_subjects, start=1)
        ]
    else:
        raise RuntimeError(
            f"No [PATCH ...] entries found in mbox: {mbox_path}"
        )

    return entries


def find_generated_mbox(repo: Path, mbox_basename: str) -> Path:
    candidates = [
        repo / f"{mbox_basename}.mbx",
        repo / f"{mbox_basename}.mbox",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"Unable to find generated mbox. Checked: {', '.join(str(c) for c in candidates)}"
    )


def fetch_patchset_with_b4(repo: Path, patchset_link: str, mbox_basename: str) -> Path:
    if not shutil.which("b4"):
        raise RuntimeError("b4 is not installed or not in PATH.")
    LOG.info("Fetching patchset with b4 from: %s", patchset_link)
    proc = run(
        ["b4", "am", "-o", ".", "-n", mbox_basename, patchset_link],
        cwd=repo,
        check=True,
    )
    if proc.stdout.strip():
        LOG.debug("b4 stdout:\n%s", proc.stdout.strip())
    if proc.stderr.strip():
        LOG.debug("b4 stderr:\n%s", proc.stderr.strip())
    mbox_path = find_generated_mbox(repo, mbox_basename)
    LOG.info("Fetched mbox: %s", mbox_path)
    return mbox_path


def apply_mbox(repo: Path, mbox_path: Path) -> None:
    LOG.info("Applying patchset with git am: %s", mbox_path)
    proc = git(repo, "am", str(mbox_path), check=False)
    if proc.returncode != 0:
        LOG.error("git am failed. Keeping mbox for manual resolution: %s", mbox_path)
        if proc.stdout.strip():
            LOG.error("git am stdout:\n%s", proc.stdout.strip())
        if proc.stderr.strip():
            LOG.error("git am stderr:\n%s", proc.stderr.strip())
        raise RuntimeError("git am failed.")
    LOG.info("Patchset applied cleanly.")


def get_last_n_commits(repo: Path, n: int) -> List[str]:
    proc = git(repo, "rev-list", "--reverse", f"--max-count={n}", "HEAD")
    commits = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(commits) != n:
        raise RuntimeError(f"Expected {n} commits from HEAD, got {len(commits)}")
    return commits


def get_commit_subject(repo: Path, commit: str) -> str:
    return git(repo, "show", "-s", "--format=%s", commit).stdout.strip()


def load_branch_subject_set(upstream_repo: Path, branch: str) -> set[str]:
    LOG.info("Loading subject set from upstream branch: %s", branch)
    proc = git(upstream_repo, "log", branch, "--format=%s")
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def normalize_subject(subject: str) -> str:
    return PREFIX_RE.sub("", subject, count=1)


def subject_exists(subject_set: set[str], subject: str) -> bool:
    base = normalize_subject(subject)
    return (
        base in subject_set
        or f"FROMLIST: {base}" in subject_set
        or f"UPSTREAM: {base}" in subject_set
    )


def build_rewrite_plan(
    target_repo: Path,
    commit_hashes: List[str],
    patch_entries: List[PatchEntry],
    link_url_template: str,
    upstream_primary_subjects: set[str],
    upstream_secondary_subjects: Optional[set[str]],
    enable_fromlist_when_missing: bool,
    add_signed_off_by: Optional[str],
) -> Dict[str, Dict[str, str]]:
    if len(commit_hashes) != len(patch_entries):
        raise RuntimeError("Mismatch between applied commits and parsed patch entries.")

    plan: Dict[str, Dict[str, str]] = {}
    for commit, entry in zip(commit_hashes, patch_entries):
        subject = get_commit_subject(target_repo, commit)
        link = link_url_template.format(msgid=entry.message_id)

        if subject_exists(upstream_primary_subjects, subject):
            prefix = "UPSTREAM: "
            reason = "found in primary branch"
        elif upstream_secondary_subjects is not None:
            if not subject_exists(upstream_secondary_subjects, subject):
                prefix = "FROMLIST: " if enable_fromlist_when_missing else ""
                reason = "missing in both primary and secondary branch"
            else:
                prefix = ""
                reason = "found in secondary branch only"
        else:
            prefix = "FROMLIST: " if enable_fromlist_when_missing else ""
            reason = "missing in primary branch"

        plan[commit] = {
            "link": link,
            "prefix": prefix,
            "signoff": add_signed_off_by or "",
        }
        LOG.info(
            "Plan %-12s %s (%s)",
            ("UPSTREAM" if prefix.startswith("UPSTREAM") else "FROMLIST" if prefix.startswith("FROMLIST") else "KEEP"),
            commit[:12],
            reason,
        )
    return plan


MSG_FILTER = r"""#!/usr/bin/env python3
import json
import os
import re
import sys

PREFIX_RE = re.compile(r"^(FROMLIST:\s+|UPSTREAM:\s+)")

def strip_prefix(subject: str) -> str:
    return PREFIX_RE.sub("", subject, count=1)

def main() -> int:
    mapping_file = sys.argv[1]
    mapping = json.load(open(mapping_file, "r", encoding="utf-8"))
    commit = os.environ.get("GIT_COMMIT", "")
    msg = sys.stdin.read()
    data = mapping.get(commit)
    if not data:
        sys.stdout.write(msg)
        return 0

    lines = msg.splitlines()
    if not lines:
        sys.stdout.write(msg)
        return 0

    prefix = data.get("prefix", "")
    link = data.get("link", "").strip()
    signoff = data.get("signoff", "").strip()

    subject = lines[0]
    base = strip_prefix(subject)
    if prefix:
        lines[0] = f"{prefix}{base}"

    if link:
        # Keep exactly one Link trailer and reposition it after Signed-off-by trailers.
        lines = [line for line in lines if line.strip() != link]

    if signoff:
        # Keep exactly one requested sign-off trailer.
        lines = [line for line in lines if line.strip() != signoff]
        last_sob = -1
        for i, line in enumerate(lines):
            if line.startswith("Signed-off-by:"):
                last_sob = i
        if last_sob >= 0:
            lines.insert(last_sob + 1, signoff)
        else:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(signoff)

    if link:
        # Normalize trailer order so Signed-off-by trailers always come before Link.
        last_sob = -1
        for i, line in enumerate(lines):
            if line.startswith("Signed-off-by:"):
                last_sob = i
        if last_sob >= 0:
            lines.insert(last_sob + 1, link)
        else:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(link)

    out = "\n".join(lines)
    if msg.endswith("\n"):
        out += "\n"
    sys.stdout.write(out)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
"""


def rewrite_commits(repo: Path, rewrite_plan: Dict[str, Dict[str, str]], count: int) -> None:
    if count <= 0:
        LOG.info("No commits to rewrite.")
        return
    LOG.info("Rewriting the last %d commit messages.", count)
    with tempfile.TemporaryDirectory(prefix="lore-rewrite-") as td:
        td_path = Path(td)
        mapping_path = td_path / "rewrite_map.json"
        filter_path = td_path / "msg_filter.py"
        mapping_path.write_text(json.dumps(rewrite_plan), encoding="utf-8")
        filter_path.write_text(MSG_FILTER, encoding="utf-8")
        filter_path.chmod(0o755)

        env = dict(os.environ)
        env["FILTER_BRANCH_SQUELCH_WARNING"] = "1"
        cmd = [
            "git",
            "filter-branch",
            "-f",
            "--msg-filter",
            f"{shutil.which('python3') or 'python3'} {filter_path} {mapping_path}",
            f"HEAD~{count}..HEAD",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(repo),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            if proc.stdout.strip():
                LOG.error("git filter-branch stdout:\n%s", proc.stdout.strip())
            if proc.stderr.strip():
                LOG.error("git filter-branch stderr:\n%s", proc.stderr.strip())
            raise RuntimeError("Failed to rewrite commit messages.")
        if proc.stdout.strip():
            LOG.debug("git filter-branch stdout:\n%s", proc.stdout.strip())
        if proc.stderr.strip():
            LOG.debug("git filter-branch stderr:\n%s", proc.stderr.strip())
    LOG.info("Commit message rewrite completed.")


def ensure_git_repo(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} path does not exist: {path}")
    proc = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, check=False)
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        raise RuntimeError(f"{label} is not a git repository: {path}")


def resolve_signoff_identity(target_repo: Path, requested: Optional[str]) -> str:
    if requested:
        return requested.strip()

    name = git(target_repo, "config", "--get", "user.name", check=False).stdout.strip()
    email = git(target_repo, "config", "--get", "user.email", check=False).stdout.strip()
    if name and email:
        return f"{name} <{email}>"

    return FALLBACK_SIGNOFF_IDENTITY


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automate b4 patchset fetch/apply and message post-processing."
    )
    parser.add_argument(
        "--target-repo",
        required=True,
        help="Path to target git repo where patches are applied (e.g. qcom-next).",
    )
    parser.add_argument(
        "--upstream-repo",
        required=True,
        help="Path to upstream git repo used for subject existence checks.",
    )
    parser.add_argument(
        "--patchset-link",
        required=True,
        help="Lore patchset link/msgid accepted by `b4 am`.",
    )
    parser.add_argument(
        "--primary-branch",
        default="master",
        help="Primary upstream branch for UPSTREAM prefix check (default: master).",
    )
    parser.add_argument(
        "--secondary-branch",
        default=None,
        help=(
            "Optional secondary upstream branch. "
            "FROMLIST is added only when missing in both branches."
        ),
    )
    parser.add_argument(
        "--mbox-basename",
        default="lore-patchset",
        help="Output basename for b4 mailbox files (default: lore-patchset).",
    )
    parser.add_argument(
        "--link-url-template",
        default="https://lore.kernel.org/r/{msgid}",
        help=(
            "Commit trailer URL template; must contain {msgid}. "
            "Default: https://lore.kernel.org/r/{msgid}"
        ),
    )
    parser.add_argument(
        "--add-signoff",
        default="",
        help=(
            "Ensure this Signed-off-by identity exists on each rewritten commit. "
            "Format: 'Name <email>'. Inserted before Link and deduplicated. "
            "Default: repo git user.name/user.email, fallback to "
            f"'{FALLBACK_SIGNOFF_IDENTITY}'."
        ),
    )
    parser.add_argument(
        "--no-fromlist-when-missing",
        action="store_true",
        help="Do not add FROMLIST prefix when commit is not found upstream.",
    )
    parser.add_argument(
        "--require-clean-target",
        action="store_true",
        help="Fail if target repo has uncommitted/untracked changes.",
    )
    parser.add_argument(
        "--keep-mbox-on-success",
        action="store_true",
        help="Keep fetched mbox/cover files even when patchset applies cleanly.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default: INFO).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    target_repo = Path(args.target_repo).resolve()
    upstream_repo = Path(args.upstream_repo).resolve()
    enable_fromlist = not args.no_fromlist_when_missing
    signoff_identity = resolve_signoff_identity(target_repo, args.add_signoff)
    requested_signoff = f"Signed-off-by: {signoff_identity}"

    ensure_git_repo(target_repo, "Target repo")
    ensure_git_repo(upstream_repo, "Upstream repo")

    if "{msgid}" not in args.link_url_template:
        raise ValueError("--link-url-template must contain '{msgid}'")

    if args.require_clean_target:
        st = git(target_repo, "status", "--porcelain").stdout.strip()
        if st:
            raise RuntimeError("Target repo is not clean. Commit/stash/clean first.")

    LOG.info("Target repo   : %s", target_repo)
    LOG.info("Upstream repo : %s", upstream_repo)
    LOG.info("Patchset link : %s", args.patchset_link)
    LOG.info("Primary branch: %s", args.primary_branch)
    LOG.info("Secondary br. : %s", args.secondary_branch or "<none>")
    LOG.info("Add sign-off  : %s", signoff_identity)

    mbox_path = fetch_patchset_with_b4(target_repo, args.patchset_link, args.mbox_basename)
    cover_path = target_repo / f"{args.mbox_basename}.cover"
    patch_entries = parse_patch_entries_from_mbox(mbox_path)
    patch_count = len(patch_entries)
    LOG.info("Detected %d patches in series.", patch_count)

    apply_mbox(target_repo, mbox_path)
    commit_hashes = get_last_n_commits(target_repo, patch_count)

    primary_subjects = load_branch_subject_set(upstream_repo, args.primary_branch)
    secondary_subjects = (
        load_branch_subject_set(upstream_repo, args.secondary_branch)
        if args.secondary_branch
        else None
    )

    rewrite_plan = build_rewrite_plan(
        target_repo=target_repo,
        commit_hashes=commit_hashes,
        patch_entries=patch_entries,
        link_url_template=args.link_url_template,
        upstream_primary_subjects=primary_subjects,
        upstream_secondary_subjects=secondary_subjects,
        enable_fromlist_when_missing=enable_fromlist,
        add_signed_off_by=requested_signoff,
    )
    rewrite_commits(target_repo, rewrite_plan, patch_count)

    if not args.keep_mbox_on_success:
        for p in [mbox_path, cover_path]:
            if p.exists():
                p.unlink()
                LOG.info("Removed artifact after success: %s", p)
    else:
        LOG.info("Keeping fetched artifacts as requested.")

    head_log = git(target_repo, "log", "--oneline", f"-n{patch_count}").stdout.strip()
    LOG.info("Top %d commits after automation:\n%s", patch_count, head_log)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOG.error("Automation failed: %s", exc)
        raise SystemExit(1)
