"""Keep deployment specifics out of this public repository (#475).

SECURITY.md's standing rule keeps what *this deployment* runs on out of
tracked files. Most of it cannot be pattern-checked: *which* provider, port
or arrangement a deployment uses is a fact about the world, not a shape in
text, and stays with the ``secret-scanner`` agent and review. This module
enforces the part that can be checked without writing a deployment value
down:

* a key file path (anything under an ``.ssh`` directory other than the
  standard ``config`` / ``known_hosts`` / ``authorized_keys``),
* droplet sizing figures (vCPU and SSD tokens; a RAM floor is a software
  requirement and is allowed),
* a mail or backup provider name anywhere except the three files that carry
  a generic list of supported providers.

A failure prints ``path:line`` and the rule name, never the matched text:
CI logs are public too.

Known limit: inside the three generic-list files a provider name is not
checked, so a deployment-specific aside added there is for the scanner and
review to catch, not this test.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
THIS_FILE = Path(__file__).resolve()

# Where a *generic* list of supported providers is allowed (SECURITY.md,
# "What the rule allows"): the env template, the SMTP module's docstring and
# the RUNBOOK's secrets section.
GENERIC_LIST_FILES = frozenset(
    {
        ".env.example",
        "deltadewa/reporting/email_smtp.py",
        "docs/RUNBOOK.md",
    },
)

# Deliberately a broad list of peers, not just the providers a deployment
# might use, so the list itself says nothing about which one is in use.
# "Resend" is not listed: it is also an ordinary English word.
MAIL_PROVIDERS = (
    "brevo",
    "sendgrid",
    "mailgun",
    "postmark",
    "mailtrap",
    "amazon ses",
    "sparkpost",
    "mailjet",
    "smtp2go",
)
GIT_HOSTS = (
    "codeberg",
    "gitlab",
    "bitbucket",
    "sourcehut",
)

KEY_PATH = re.compile(
    r"(?:/root|~)/\.ssh/(?!(?:config|known_hosts|authorized_keys)\b)[\w.<>-]+",
)
SIZING = re.compile(r"\bvcpus?\b|\dvcpu|\bssd\b", re.IGNORECASE)
PROVIDER_NAME = re.compile(
    r"\b(?:"
    + "|".join(re.escape(n) for n in (*MAIL_PROVIDERS, *GIT_HOSTS))
    + r")\b",
    re.IGNORECASE,
)


def _tracked_text_files() -> list[tuple[str, list[str]]]:
    """Return ``(repo-relative path, lines)`` for every tracked text file."""
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout; nothing to enumerate")
    listing = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git, "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    files: list[tuple[str, list[str]]] = []
    for rel in listing.stdout.decode("utf-8").split("\0"):
        path = REPO_ROOT / rel
        if not rel or rel == "poetry.lock" or path.resolve() == THIS_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary, or a path git lists but the tree lacks
        files.append((rel, text.splitlines()))
    return files


def _violations(
    pattern: re.Pattern[str],
    *,
    skip_files: frozenset[str] = frozenset(),
) -> list[str]:
    """Return ``path:line`` for every line matching ``pattern``."""
    return [
        f"{rel}:{lineno}"
        for rel, lines in _tracked_text_files()
        if rel not in skip_files
        for lineno, line in enumerate(lines, start=1)
        if pattern.search(line)
    ]


def _fail_message(rule: str, hits: list[str]) -> str:
    return (
        f"{rule} in tracked files (SECURITY.md, 'What the rule allows'). "
        "Write it as 'see private ops doc'. Locations only, by design:\n  "
        + "\n  ".join(hits)
    )


def test_no_key_file_path_in_tracked_files() -> None:
    """The backup deploy key's path belongs in the private ops doc."""
    hits = _violations(KEY_PATH)
    assert not hits, _fail_message("key file path", hits)


def test_no_droplet_sizing_figures_in_tracked_files() -> None:
    """Droplet CPU/disk figures belong in the private ops doc."""
    hits = _violations(SIZING)
    assert not hits, _fail_message("droplet sizing figure", hits)


def test_provider_names_only_in_generic_list_files() -> None:
    """A provider name outside the generic lists says which one is in use."""
    hits = _violations(PROVIDER_NAME, skip_files=GENERIC_LIST_FILES)
    assert not hits, _fail_message("mail or backup provider name", hits)


# --- the patterns themselves, so a guard cannot quietly stop guarding -------


@pytest.mark.parametrize(
    "line",
    [
        "IdentityFile /root/.ssh/some_key",
        "keygen -f ~/.ssh/id_example",
        "at /root/.ssh/<anything>",
    ],
)
def test_key_path_pattern_matches_a_key_file(line: str) -> None:
    assert KEY_PATH.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "# /root/.ssh/config",
        "a ~/.ssh/config alias",
        "/root/.ssh/known_hosts",
        "<deploy-key-path>",
    ],
)
def test_key_path_pattern_ignores_standard_files_and_placeholders(
    line: str,
) -> None:
    assert not KEY_PATH.search(line)


@pytest.mark.parametrize(
    "line",
    ["2 vCPU / 4 GB", "slug s-2vcpu-4gb", "80 GB SSD", "two vCPUs"],
)
def test_sizing_pattern_matches_cpu_and_disk_figures(line: str) -> None:
    assert SIZING.search(line)


@pytest.mark.parametrize(
    "line",
    ["at least 4 GB RAM", "Ubuntu 24.04 LTS", "program data is small"],
)
def test_sizing_pattern_allows_a_ram_floor(line: str) -> None:
    assert not SIZING.search(line)


def test_provider_pattern_matches_whole_names_only() -> None:
    assert PROVIDER_NAME.search("delivered via Mailgun")
    assert PROVIDER_NAME.search("pushed to a Codeberg repo")
    assert not PROVIDER_NAME.search("resend the email")
    assert not PROVIDER_NAME.search("a postmarked envelope")
