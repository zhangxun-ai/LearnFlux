#!/usr/bin/env python3
"""Create a private local configuration once, without replacing user settings."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import secrets


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def initialize_config(destination: Path, template: Path) -> bool:
    """Create configuration with a unique token, returning False if it exists."""
    if destination.is_symlink():
        raise ValueError("Configuration path must not be a symbolic link")
    if destination.exists():
        if not destination.is_file():
            raise ValueError("Configuration path must be a regular file")
        return False
    if destination.parent.is_symlink():
        raise ValueError("Configuration directory must not be a symbolic link")

    content = template.read_text(encoding="utf-8")
    content, replacements = re.subn(
        r'("auth_token"\s*:\s*)"[^"\\]*"',
        lambda match: f'{match[1]}"{secrets.token_urlsafe(48)}"',
        content,
    )
    if replacements != 1:
        raise ValueError("Configuration template must contain exactly one auth_token")
    content, replacements = re.subn(
        r'("host"\s*:\s*)"[^"\\]*"',
        lambda match: f'{match[1]}"127.0.0.1"',
        content,
        count=1,
    )
    if replacements != 1:
        raise ValueError("Configuration template must contain an API host")

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if destination.is_symlink() or not destination.is_file():
            raise ValueError("Configuration path changed during initialization") from None
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "config/config.jsonc")
    parser.add_argument("--template", type=Path, default=PROJECT_ROOT / "config/config.example.jsonc")
    arguments = parser.parse_args()
    try:
        created = initialize_config(arguments.output, arguments.template)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Configuration initialization failed: {error}\n")
    if created:
        print("Created private configuration with a random access token and local-only listener.")
    else:
        print("Keeping existing configuration unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
