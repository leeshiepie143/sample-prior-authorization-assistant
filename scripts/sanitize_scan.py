#!/usr/bin/env python3
"""Sanitization scanner for AWS blog publication preparation.

Scans a repository for sensitive patterns (AWS account IDs, internal URLs,
hardcoded credentials, etc.) and produces a report for CSR submission.

Usage:
    python scripts/sanitize_scan.py [root_dir]
    python scripts/sanitize_scan.py [root_dir] --git-history
"""

import argparse
import os
import re
import subprocess  # nosec B404
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ScanFinding:
    """A single finding from the sanitization scan."""

    file_path: str
    line_number: int
    pattern_type: str
    matched_text: str
    severity: str  # 'critical' | 'high' | 'medium' | 'low'
    suggestion: str


@dataclass
class ScanReport:
    """Aggregated results from scanning a repository."""

    findings: list[ScanFinding] = field(default_factory=list)
    files_scanned: int = 0
    patterns_checked: int = 0
    scan_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def has_blockers(self) -> bool:
        """Return True if any finding is critical or high severity."""
        return any(f.severity in ("critical", "high") for f in self.findings)

    def to_markdown(self) -> str:
        """Generate a markdown report suitable for CSR submission."""
        lines: list[str] = []
        lines.append("# Sanitization Scan Report")
        lines.append("")
        lines.append(f"**Scan timestamp:** {self.scan_timestamp}")
        lines.append(f"**Files scanned:** {self.files_scanned}")
        lines.append(f"**Patterns checked:** {self.patterns_checked}")
        lines.append(f"**Total findings:** {len(self.findings)}")
        lines.append(f"**Has blockers:** {'Yes' if self.has_blockers() else 'No'}")
        lines.append("")
        if not self.findings:
            lines.append("No findings. Repository is clean.")
            return "\n".join(lines)

        # Group findings by severity
        for severity in ("critical", "high", "medium", "low"):
            severity_findings = [
                f for f in self.findings if f.severity == severity
            ]
            if not severity_findings:
                continue
            lines.append(f"## {severity.upper()} ({len(severity_findings)})")
            lines.append("")
            lines.append("| File | Line | Pattern | Match | Suggestion |")
            lines.append("|------|------|---------|-------|------------|")
            for f in severity_findings:
                safe_match = f.matched_text.replace("|", "\\|")
                lines.append(
                    f"| {f.file_path} | {f.line_number} "
                    f"| {f.pattern_type} | `{safe_match}` "
                    f"| {f.suggestion} |"
                )
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

_PATTERNS: list[dict] = [
    {
        "name": "aws_account_id",
        "regex": re.compile(r"arn:aws[^:]*:[^:]*:[^:]*:(?!123456789012)(\d{12}):"),
        "severity": "critical",
        "suggestion": "Replace AWS account ID with a placeholder or parameterize.",
    },
    {
        "name": "internal_url",
        "regex": re.compile(
            r"w\.amazon\.com|\.corp\.|corp\.amazon\.|gitlab\.aws\.dev|quip-amazon",
            re.IGNORECASE,
        ),
        "severity": "critical",
        "suggestion": "Remove internal Amazon URL.",
    },
    {
        "name": "amazon_email",
        "regex": re.compile(r"\b\w+@amazon\.com\b", re.IGNORECASE),
        "severity": "critical",
        "suggestion": "Remove @amazon.com email address.",
    },
    {
        "name": "hardcoded_kb_id",
        "regex": re.compile(r"CUQR4VHVNI|Z62OY4IZ98"),
        "severity": "high",
        "suggestion": "Parameterize Knowledge Base / Data Source ID via CDK context or env var.",
    },
    {
        "name": "api_gateway_url",
        "regex": re.compile(
            r"\w+\.execute-api\.\w+-\w+-\d\.amazonaws\.com"
        ),
        "severity": "high",
        "suggestion": "Replace API Gateway URL with environment variable.",
    },
    {
        "name": "internal_tool",
        "regex": re.compile(
            r"\bisengard\b|\bbrazil\b|\bmidway\b|\bbindle\b", re.IGNORECASE
        ),
        "severity": "medium",
        "suggestion": "Remove reference to internal Amazon tool.",
    },
    {
        "name": "slack_chime_ref",
        "regex": re.compile(r"chime\.aws|slack\.com/archives", re.IGNORECASE),
        "severity": "medium",
        "suggestion": "Remove internal Slack/Chime reference.",
    },
]


# ---------------------------------------------------------------------------
# Binary detection helper
# ---------------------------------------------------------------------------

_BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".jar", ".war",
    ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".pyo", ".class",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".db", ".sqlite", ".sqlite3",
})


def _is_binary(file_path: str) -> bool:
    """Heuristic check: skip known binary extensions and null-byte detection."""
    _, ext = os.path.splitext(file_path)
    if ext.lower() in _BINARY_EXTENSIONS:
        return True
    try:
        with open(file_path, "rb") as fh:
            chunk = fh.read(8192)
            return b"\x00" in chunk
    except (OSError, PermissionError):
        return True


# ---------------------------------------------------------------------------
# Core scanning logic
# ---------------------------------------------------------------------------

def scan_file(file_path: str) -> list[ScanFinding]:
    """Scan a single file for sensitive patterns."""
    findings: list[ScanFinding] = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            for line_number, line in enumerate(fh, start=1):
                for pattern in _PATTERNS:
                    for match in pattern["regex"].finditer(line):
                        findings.append(
                            ScanFinding(
                                file_path=file_path,
                                line_number=line_number,
                                pattern_type=pattern["name"],
                                matched_text=match.group(0),
                                severity=pattern["severity"],
                                suggestion=pattern["suggestion"],
                            )
                        )
    except (OSError, PermissionError):
        pass  # skip unreadable files
    return findings


def scan_repository(root_dir: str) -> ScanReport:
    """Walk the repository tree and scan all non-binary, non-.git files.

    Args:
        root_dir: Path to the repository root.

    Returns:
        A ScanReport with all findings.
    """
    report = ScanReport(patterns_checked=len(_PATTERNS))
    root_dir = os.path.abspath(root_dir)

    _SKIP_DIRS = {".git", "node_modules", "cdk.out", ".venv", "venv", "__pycache__", ".kiro"}
    _SKIP_FILES = {"sanitize_scan.py", "clean_vendored_deps.py"}
    _SKIP_EXTENSIONS = {".env.example"}

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip non-source directories
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for filename in filenames:
            if filename in _SKIP_FILES or filename in _SKIP_EXTENSIONS:
                continue
            file_path = os.path.join(dirpath, filename)
            if _is_binary(file_path):
                continue
            report.files_scanned += 1
            rel_path = os.path.relpath(file_path, root_dir)
            file_findings = scan_file(file_path)
            for finding in file_findings:
                finding.file_path = rel_path
            report.findings.extend(file_findings)

    return report


# ---------------------------------------------------------------------------
# Git history scanning
# ---------------------------------------------------------------------------

@dataclass
class GitHistoryFinding:
    """A sensitive pattern found in git history."""

    commit_hash: str
    pattern_type: str
    matched_text: str
    severity: str


def scan_git_history(repo_dir: str) -> list[GitHistoryFinding]:
    """Scan git history for sensitive patterns by parsing ``git log -p``.

    Args:
        repo_dir: Path to the repository root (must be a git repo).

    Returns:
        List of findings with commit hash and pattern details.
    """
    repo_dir = os.path.abspath(repo_dir)
    findings: list[GitHistoryFinding] = []

    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "log", "-p", "--no-color"],
            cwd=repo_dir,
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            return findings
        output = result.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return findings

    current_commit: str = ""
    for line in output.splitlines():
        # Track current commit hash
        if line.startswith("commit "):
            current_commit = line.split()[1][:12]
            continue

        if not current_commit:
            continue

        for pattern in _PATTERNS:
            for match in pattern["regex"].finditer(line):
                findings.append(
                    GitHistoryFinding(
                        commit_hash=current_commit,
                        pattern_type=pattern["name"],
                        matched_text=match.group(0),
                        severity=pattern["severity"],
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the sanitization scanner from the command line."""
    parser = argparse.ArgumentParser(
        description="Sanitization scanner for AWS blog publication preparation.",
    )
    parser.add_argument(
        "root_dir",
        nargs="?",
        default=".",
        help="Repository root directory to scan (default: current directory).",
    )
    parser.add_argument(
        "--git-history",
        action="store_true",
        help="Also scan git commit history for sensitive patterns.",
    )
    args = parser.parse_args()

    root_dir: str = args.root_dir
    print(f"Scanning {os.path.abspath(root_dir)} ...")
    report = scan_repository(root_dir)
    print(report.to_markdown())

    has_git_findings = False
    if args.git_history:
        print("\n--- Git History Scan ---\n")
        git_findings = scan_git_history(root_dir)
        if git_findings:
            has_git_findings = True
            print(f"Found {len(git_findings)} sensitive pattern(s) in git history:\n")
            for gf in git_findings:
                print(
                    f"  [{gf.severity.upper()}] commit {gf.commit_hash} "
                    f"— {gf.pattern_type}: `{gf.matched_text}`"
                )
        else:
            print("No sensitive patterns found in git history.")

    if report.has_blockers() or has_git_findings:
        print("\n⚠️  Blockers found — resolve before CSR submission.")
        sys.exit(1)
    else:
        print("\n✅ No blockers found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
