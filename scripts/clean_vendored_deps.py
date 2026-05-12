#!/usr/bin/env python3
"""Remove vendored Python dependencies from src/.

These packages belong in the Lambda layer (layers/python-deps/) and should
not be committed to the repository. The script is idempotent — it skips
items that have already been removed.

Usage:
    python scripts/clean_vendored_deps.py [--dry-run]
"""

import argparse
import glob
import os
import re
import shutil
import sys

# Root of the repository (one level up from scripts/)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
LAYER_REQUIREMENTS = os.path.join(
    REPO_ROOT, "layers", "python-deps", "requirements.txt"
)

# Vendored package directories to remove from src/
VENDORED_DIRS = [
    "boto3",
    "botocore",
    "pydantic",
    "pydantic_core",
    "marshmallow",
    "structlog",
    "dateutil",
    "urllib3",
    "bs4",
    "soupsieve",
    "jmespath",
    "s3transfer",
    "packaging",
    "dataclasses_json",
    "annotated_types",
    "typing_inspection",
    "bin",
]

# Standalone vendored files to remove from src/
VENDORED_FILES = [
    "six.py",
    "typing_extensions.py",
    "typing_inspect.py",
    "mypy_extensions.py",
    ".dockerignore",
    "requirements.txt",
]

# Application directories that must NOT be removed
APP_DIRS = {
    "api",
    "batch_metadata_invoker",
    "common",
    "extract_clinical_criteria",
    "extractors",
    "intelligent_policy_selector",
    "kb_sync",
    "knowledge",
    "merge_policy_criteria",
    "metadata_extractor",
    "metadata_processor",
    "orchestrator",
    "payor_validator",
    "policy_extractors",
    "reviewer",
    "s3_uploader",
    "security",
    "selector",
}

# Core packages that the layer requirements.txt must list
REQUIRED_LAYER_PACKAGES = [
    "boto3",
    "botocore",
    "pydantic",
    "dataclasses-json",
    "marshmallow",
    "structlog",
    "python-dateutil",
    "beautifulsoup4",
]


def _remove_dir(path: str, dry_run: bool) -> bool:
    """Remove a directory tree. Returns True if removed, False if not found."""
    if not os.path.isdir(path):
        return False
    if dry_run:
        print(f"  [dry-run] Would remove directory: {path}")
    else:
        shutil.rmtree(path)
        print(f"  Removed directory: {path}")
    return True


def _remove_file(path: str, dry_run: bool) -> bool:
    """Remove a single file. Returns True if removed, False if not found."""
    if not os.path.isfile(path):
        return False
    if dry_run:
        print(f"  [dry-run] Would remove file: {path}")
    else:
        os.remove(path)
        print(f"  Removed file: {path}")
    return True


def clean_vendored_deps(dry_run: bool = False) -> dict:
    """Remove vendored dependencies from src/.

    Returns a summary dict with counts of removed/skipped items.
    """
    removed = 0
    skipped = 0

    if not os.path.isdir(SRC_DIR):
        print(f"ERROR: src/ directory not found at {SRC_DIR}")
        sys.exit(1)

    # 1. Remove known vendored directories
    print("Removing vendored package directories...")
    for dirname in VENDORED_DIRS:
        path = os.path.join(SRC_DIR, dirname)
        if _remove_dir(path, dry_run):
            removed += 1
        else:
            skipped += 1

    # 2. Remove *.dist-info directories
    print("Removing *.dist-info directories...")
    dist_info_pattern = os.path.join(SRC_DIR, "*.dist-info")
    for path in sorted(glob.glob(dist_info_pattern)):
        if _remove_dir(path, dry_run):
            removed += 1

    # 3. Remove standalone vendored files
    print("Removing standalone vendored files...")
    for filename in VENDORED_FILES:
        path = os.path.join(SRC_DIR, filename)
        if _remove_file(path, dry_run):
            removed += 1
        else:
            skipped += 1

    # 4. Remove __pycache__ dirs (leftover from vendored packages)
    print("Removing __pycache__ directories...")
    for root, dirs, _files in os.walk(SRC_DIR):
        for d in dirs:
            if d == "__pycache__":
                path = os.path.join(root, d)
                if _remove_dir(path, dry_run):
                    removed += 1

    return {"removed": removed, "skipped": skipped}


def verify_layer_requirements() -> list[str]:
    """Check that layers/python-deps/requirements.txt lists all needed packages.

    Returns a list of missing package names (empty if all present).
    """
    if not os.path.isfile(LAYER_REQUIREMENTS):
        print(f"WARNING: Layer requirements file not found: {LAYER_REQUIREMENTS}")
        return REQUIRED_LAYER_PACKAGES[:]

    with open(LAYER_REQUIREMENTS, "r", encoding="utf-8") as f:
        content = f.read().lower()

    missing = []
    for pkg in REQUIRED_LAYER_PACKAGES:
        # Normalize: check that the package name appears (ignoring case/hyphens)
        normalized = pkg.lower().replace("-", "[-_]")
        if not re.search(normalized, content):
            missing.append(pkg)
    return missing


def verify_no_app_dirs_removed() -> list[str]:
    """Verify that all application directories still exist in src/.

    Returns a list of missing application directory names.
    """
    missing = []
    for dirname in sorted(APP_DIRS):
        path = os.path.join(SRC_DIR, dirname)
        if not os.path.isdir(path):
            missing.append(dirname)
    return missing


def main():
    parser = argparse.ArgumentParser(
        description="Remove vendored Python dependencies from src/"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without actually deleting",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Vendored Dependency Cleanup")
    print("=" * 60)

    if args.dry_run:
        print("(DRY RUN — no files will be deleted)\n")

    # Step 1: Clean vendored deps
    summary = clean_vendored_deps(dry_run=args.dry_run)
    print(f"\nCleanup complete: {summary['removed']} removed, {summary['skipped']} already absent")

    # Step 2: Verify layer requirements
    print("\n" + "-" * 60)
    print("Verifying layers/python-deps/requirements.txt...")
    missing_pkgs = verify_layer_requirements()
    if missing_pkgs:
        print(f"WARNING: Missing packages in layer requirements: {', '.join(missing_pkgs)}")
        print("  These vendored packages were removed but are not in the Lambda layer.")
    else:
        print("All required packages are listed in the Lambda layer requirements.")

    # Step 3: Verify application directories are intact
    print("\n" + "-" * 60)
    print("Verifying application directories are intact...")
    missing_dirs = verify_no_app_dirs_removed()
    if missing_dirs:
        print(f"ERROR: Application directories missing from src/: {', '.join(missing_dirs)}")
        sys.exit(1)
    else:
        print("All application directories are present in src/.")

    # Final status
    print("\n" + "=" * 60)
    if missing_pkgs:
        print("DONE (with warnings — review layer requirements)")
        sys.exit(0)
    else:
        print("DONE — src/ is clean.")
        sys.exit(0)


if __name__ == "__main__":
    main()
