#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
DOCKER_WORKFLOW_NAME = "Docker"


class ReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckResult:
    label: str
    command: tuple[str, ...]


def run(
    command: Iterable[str],
    *,
    cwd: Path = ROOT,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command_tuple = tuple(command)
    return subprocess.run(
        command_tuple,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=check,
    )


def git_output(*args: str) -> str:
    result = run(("git", *args), capture=True)
    return result.stdout.strip()


def normalize_version(raw: str) -> tuple[str, str]:
    value = raw.strip()
    if value.startswith("v"):
        value = value[1:]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", value):
        raise ReleaseError("Version must look like 0.7.2 or v0.7.2.")
    return value, f"v{value}"


def parse_github_repo_slug(remote_url: str) -> str:
    value = remote_url.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https", "ssh"} and parsed.hostname == "github.com":
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        if re.fullmatch(r"[^/\s]+/[^/\s]+", path):
            return path

    patterns = (
        r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return match.group(1)
    raise ReleaseError(f"Cannot parse GitHub repo from remote URL: {remote_url}")


def resolve_repo_slug(explicit_repo: str | None, remote: str) -> str:
    if explicit_repo:
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", explicit_repo):
            raise ReleaseError("--repo must look like owner/name.")
        return explicit_repo
    remote_url = git_output("remote", "get-url", remote)
    return parse_github_repo_slug(remote_url)


def read_project_version(path: Path = PYPROJECT) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    if not match:
        raise ReleaseError(f"Cannot find version in {path}.")
    return match.group(1)


def replace_project_version(version: str, path: Path = PYPROJECT) -> bool:
    text = path.read_text(encoding="utf-8")
    replaced, count = re.subn(
        r'(?m)^version\s*=\s*"[^"]+"\s*$',
        f'version = "{version}"',
        text,
        count=1,
    )
    if count != 1:
        raise ReleaseError(f"Cannot replace version in {path}.")
    if replaced == text:
        return False
    path.write_text(replaced, encoding="utf-8", newline="")
    return True


def ensure_clean_worktree() -> None:
    status = git_output("status", "--porcelain")
    if status:
        raise ReleaseError(
            "Working tree is not clean. Commit or stash local changes before releasing."
        )


def ensure_branch(expected: str) -> None:
    current = git_output("branch", "--show-current")
    if current != expected:
        raise ReleaseError(f"Release must run on {expected!r}; current branch is {current!r}.")


def ensure_tag_absent(tag: str) -> None:
    result = run(("git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"), capture=True, check=False)
    if result.returncode == 0:
        raise ReleaseError(f"Tag already exists locally: {tag}")


def latest_version_tag() -> str | None:
    result = run(("git", "describe", "--tags", "--abbrev=0", "--match", "v*"), capture=True, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def commit_subjects_since(previous_tag: str | None) -> list[str]:
    revision_range = f"{previous_tag}..HEAD" if previous_tag else "HEAD"
    result = run(
        ("git", "log", "--pretty=format:%s", revision_range),
        capture=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def default_checks() -> list[CheckResult]:
    checks = [
        CheckResult("python -m unittest discover -s tests -v", (sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")),
        CheckResult("python -m sagaquill --help", (sys.executable, "-m", "sagaquill", "--help")),
    ]
    bash = shutil.which("bash")
    if bash:
        checks.append(CheckResult("bash -n scripts/install-linux.sh", (bash, "-n", "scripts/install-linux.sh")))
        checks.append(CheckResult("bash -n scripts/bootstrap-linux.sh", (bash, "-n", "scripts/bootstrap-linux.sh")))
    return checks


def run_checks(skip_checks: bool) -> list[str]:
    if skip_checks:
        print("Skipping verification checks.")
        return []
    completed: list[str] = []
    for check in default_checks():
        print(f"Running: {check.label}")
        run(check.command)
        completed.append(check.label)
    return completed


def build_release_body(
    *,
    repo: str,
    tag: str,
    previous_tag: str | None,
    checks: list[str],
    notes_file: Path | None,
) -> str:
    if notes_file:
        return notes_file.read_text(encoding="utf-8").strip() + "\n"

    subjects = commit_subjects_since(previous_tag)
    lines: list[str] = []
    lines.append("## Changes")
    if previous_tag:
        lines.append(f"- Changes since `{previous_tag}`.")
    else:
        lines.append("- Initial public release.")
    for subject in subjects:
        lines.append(f"- {subject}")

    lines.append("")
    lines.append("## Verified")
    if checks:
        for check in checks:
            lines.append(f"- `{check}`")
    else:
        lines.append("- Verification checks were skipped for this release.")

    lines.append("")
    lines.append("## Docker")
    lines.append(f"- `ghcr.io/{repo}:{tag}`")
    lines.append(f"- `ghcr.io/{repo}:latest`")
    lines.append("")
    return "\n".join(lines)


def commit_and_tag(version: str, tag: str) -> None:
    run(("git", "add", str(PYPROJECT.relative_to(ROOT))))
    run(("git", "commit", "-m", f"Bump version to {tag}"))
    run(("git", "tag", tag))
    current = read_project_version()
    if current != version:
        raise ReleaseError(f"Version changed unexpectedly: expected {version}, got {current}")


def push_release(remote: str, branch: str, tag: str) -> None:
    run(("git", "push", remote, f"HEAD:{branch}"))
    run(("git", "push", remote, tag))


def read_token(token_file: Path | None) -> str:
    if token_file:
        token = token_file.read_text(encoding="utf-8").strip()
    else:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        raise ReleaseError("Missing GitHub token. Set GITHUB_TOKEN/GH_TOKEN or pass --token-file.")
    return token


def github_json(
    method: str,
    url: str,
    token: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sagaquill-release-script",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise ReleaseError(f"GitHub API {method} {url} failed: HTTP {exc.code}: {details}") from exc


def create_or_update_release(
    *,
    repo: str,
    tag: str,
    branch: str,
    title: str,
    body: str,
    token: str,
    draft: bool,
    prerelease: bool,
) -> str:
    base = f"https://api.github.com/repos/{repo}"
    existing: dict[str, object] | None = None
    try:
        existing = github_json("GET", f"{base}/releases/tags/{tag}", token)
    except ReleaseError as exc:
        if "HTTP 404" not in str(exc):
            raise

    payload: dict[str, object] = {
        "tag_name": tag,
        "target_commitish": branch,
        "name": title,
        "body": body,
        "draft": draft,
        "prerelease": prerelease,
    }
    if existing:
        release_id = existing["id"]
        updated = github_json("PATCH", f"{base}/releases/{release_id}", token, payload)
        return str(updated.get("html_url", ""))
    created = github_json("POST", f"{base}/releases", token, payload)
    return str(created.get("html_url", ""))


def wait_for_docker(repo: str, tag: str, token: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    url = f"https://api.github.com/repos/{repo}/actions/runs?per_page=20"
    while time.time() < deadline:
        payload = github_json("GET", url, token)
        runs = payload.get("workflow_runs", [])
        if isinstance(runs, list):
            for run_payload in runs:
                if not isinstance(run_payload, dict):
                    continue
                if run_payload.get("name") != DOCKER_WORKFLOW_NAME:
                    continue
                if run_payload.get("head_branch") != tag:
                    continue
                status = run_payload.get("status")
                conclusion = run_payload.get("conclusion")
                if status == "completed" and conclusion == "success":
                    print(f"Docker workflow completed for {tag}.")
                    return
                if status == "completed":
                    raise ReleaseError(f"Docker workflow completed with conclusion={conclusion}.")
        print(f"Waiting for Docker workflow for {tag}...")
        time.sleep(10)
    raise ReleaseError(f"Timed out waiting for Docker workflow for {tag}.")


def print_plan(repo: str, version: str, tag: str, branch: str, remote: str, dry_run: bool) -> None:
    mode = "DRY RUN" if dry_run else "RELEASE"
    print(f"{mode}: {repo} {tag}")
    print(f"- branch: {branch}")
    print(f"- remote: {remote}")
    print(f"- pyproject version: {read_project_version()} -> {version}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cut a SagaQuill GitHub release.")
    parser.add_argument("version", help="Release version, e.g. 0.7.2 or v0.7.2.")
    parser.add_argument("--repo", help="GitHub repo slug, e.g. owner/name. Defaults to origin URL.")
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="Git remote to push. Default: origin.")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Release branch. Default: main.")
    parser.add_argument("--token-file", type=Path, help="File containing a GitHub token. Token is never printed.")
    parser.add_argument("--title", help="Release title. Default: '<tag> - SagaQuill Release'.")
    parser.add_argument("--notes-file", type=Path, help="Markdown file used as the release body.")
    parser.add_argument("--skip-checks", action="store_true", help="Skip test and syntax checks.")
    parser.add_argument("--skip-push", action="store_true", help="Create local commit/tag only.")
    parser.add_argument("--skip-github-release", action="store_true", help="Do not create or update GitHub Release.")
    parser.add_argument("--draft", action="store_true", help="Create the GitHub Release as a draft.")
    parser.add_argument("--prerelease", action="store_true", help="Mark the GitHub Release as a prerelease.")
    parser.add_argument("--wait-docker", action="store_true", help="Wait for the Docker tag workflow to pass.")
    parser.add_argument("--wait-timeout", type=int, default=900, help="Docker workflow wait timeout in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the release plan without changes.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        version, tag = normalize_version(args.version)
        repo = resolve_repo_slug(args.repo, args.remote)
        title = args.title or f"{tag} - SagaQuill Release"

        ensure_branch(args.branch)
        ensure_clean_worktree()
        ensure_tag_absent(tag)
        print_plan(repo, version, tag, args.branch, args.remote, args.dry_run)
        previous_tag = latest_version_tag()
        if args.dry_run:
            print("Dry run completed. No files, commits, tags, or releases were changed.")
            return 0

        changed = replace_project_version(version)
        if not changed:
            raise ReleaseError(f"pyproject.toml is already at version {version}.")
        checks = run_checks(args.skip_checks)
        commit_and_tag(version, tag)

        if not args.skip_push:
            push_release(args.remote, args.branch, tag)
        else:
            print("Skipping git push.")

        if not args.skip_github_release:
            token = read_token(args.token_file)
            body = build_release_body(
                repo=repo,
                tag=tag,
                previous_tag=previous_tag,
                checks=checks,
                notes_file=args.notes_file,
            )
            url = create_or_update_release(
                repo=repo,
                tag=tag,
                branch=args.branch,
                title=title,
                body=body,
                token=token,
                draft=args.draft,
                prerelease=args.prerelease,
            )
            print(f"GitHub Release: {url}")
            if args.wait_docker:
                wait_for_docker(repo, tag, token, args.wait_timeout)
        else:
            print("Skipping GitHub Release creation.")

        print(f"Released {tag}.")
        return 0
    except (ReleaseError, subprocess.CalledProcessError) as exc:
        print(f"release.py: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
