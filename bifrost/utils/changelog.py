import re
from pathlib import Path
from flask import current_app


def get_latest_version_info():
    """
    Parses the CHANGELOG.md file to extract the latest version and date.
    Expected format: ## [0.6.2] - 2026-01-29
    """
    try:
        # Try to locate CHANGELOG.md relative to the root or current working directory
        root_path = Path.cwd()
        changelog_path = root_path / "CHANGELOG.md"

        if not changelog_path.exists():
            # Fallback for different execution contexts
            changelog_path = Path(__file__).parent.parent.parent / "CHANGELOG.md"

        if not changelog_path.exists():
            return "0.0.0", "Unknown Date"

        with open(changelog_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Regex to find the first version header
        # Matches lines starting with "## [X.Y.Z] - YYYY-MM-DD"
        match = re.search(r"^## \[(?P<version>[^\]]+)\] - (?P<date>\d{4}-\d{2}-\d{2})", content, re.MULTILINE)

        if match:
            return match.group("version"), match.group("date")

    except Exception as e:
        print(f"Warning: Could not parse changelog: {e}")

    return "0.0.0", "Unknown Date"