"""Build a credential-safe source ZIP for a GitHub release."""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_FILES = (
    ".gitignore",
    ".python-version",
    "README.md",
    "LOCAL_SETUP.md",
    "app.py",
    "state.py",
    "run.py",
    "config.example.py",
    "requirements.txt",
    "scripts/build_release.py",
    "tests/test_bot.py",
    "tests/test_config.py",
    "tests/test_deployment_config.py",
    "tests/test_release_package.py",
)
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?\Z")


def build_release_archive(version: str, output_dir: Path | None = None) -> Path:
    """Package only the project files needed to run/test the bot.

    The explicit file allowlist is intentional: local config.py, session files,
    databases, virtual environments, and other runtime data can never enter the
    published ZIP by accident.
    """
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must look like 1.2.3 or 1.2.3-rc1")

    destination_dir = output_dir or PROJECT_ROOT / "dist"
    destination_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"TGIbot-local-v{version}.zip"
    archive_path = destination_dir / archive_name
    top_level = f"TGIbot-local-v{version}"

    missing = [relative for relative in RELEASE_FILES if not (PROJECT_ROOT / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"Release files are missing: {', '.join(missing)}")

    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for relative in RELEASE_FILES:
            source = PROJECT_ROOT / relative
            archive.write(source, arcname=(Path(top_level) / relative).as_posix())

    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", default="1.0.0", help="release version (default: 1.0.0)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "dist",
        help="where to write the ZIP (default: ./dist)",
    )
    args = parser.parse_args()

    try:
        archive_path = build_release_archive(args.version, args.output_dir)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Created {archive_path}")


if __name__ == "__main__":
    main()
