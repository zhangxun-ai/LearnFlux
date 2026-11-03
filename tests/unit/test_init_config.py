"""New-install configuration checks using isolated temporary destinations."""

import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys

import commentjson
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/init_config.py"
TEMPLATE = ROOT / "config/config.example.jsonc"
initialize_config = runpy.run_path(str(SCRIPT))["initialize_config"]


def test_new_install_has_local_listener_unique_token_and_private_file(tmp_path):
    first = tmp_path / "first/config.jsonc"
    second = tmp_path / "second/config.jsonc"
    assert initialize_config(first, TEMPLATE)
    assert initialize_config(second, TEMPLATE)
    a, b = (commentjson.loads(path.read_text()) for path in (first, second))
    assert a["api"]["host"] == b["api"]["host"] == "127.0.0.1"
    assert len(a["api"]["auth_token"]) >= 48
    assert a["api"]["auth_token"] != b["api"]["auth_token"]
    assert a["api"]["browser_local_auto_login"] is True
    assert a["cloud_asr"]["enabled"] is False
    if os.name == "posix":
        assert stat.S_IMODE(first.stat().st_mode) == 0o600


def test_existing_config_and_permissions_remain_untouched(tmp_path):
    path = tmp_path / "config.jsonc"
    before = '{"api": {"host": "custom", "auth_token": "private-existing"}}\n'
    path.write_text(before)
    path.chmod(0o640)
    assert not initialize_config(path, TEMPLATE)
    assert path.read_text() == before
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o640


@pytest.mark.parametrize("dangling", [False, True])
def test_symlink_destination_is_not_followed(tmp_path, dangling):
    original = tmp_path / "original.jsonc"
    if not dangling:
        original.write_text("original settings")
    destination = tmp_path / "config.jsonc"
    destination.symlink_to(original)
    with pytest.raises(ValueError, match="symbolic link"):
        initialize_config(destination, TEMPLATE)
    if not dangling:
        assert original.read_text() == "original settings"
    else:
        assert not original.exists()


def test_directory_destination_is_not_replaced(tmp_path):
    with pytest.raises(ValueError, match="regular file"):
        initialize_config(tmp_path, TEMPLATE)


def test_invalid_template_does_not_leave_partial_configuration(tmp_path):
    template = tmp_path / "template.jsonc"
    template.write_text('{"api": {"host": "127.0.0.1"}}')
    destination = tmp_path / "config.jsonc"
    with pytest.raises(ValueError, match="auth_token"):
        initialize_config(destination, template)
    assert not destination.exists()


def test_cli_never_prints_the_generated_token_and_repeat_is_noop(tmp_path):
    destination = tmp_path / "config.jsonc"
    command = [sys.executable, str(SCRIPT), "--output", str(destination)]
    first = subprocess.run(command, text=True, capture_output=True, check=True)
    before = destination.read_bytes()
    token = commentjson.loads(before.decode())["api"]["auth_token"]
    second = subprocess.run(command, text=True, capture_output=True, check=True)
    assert destination.read_bytes() == before
    assert token not in first.stdout + first.stderr + second.stdout + second.stderr
    assert "Keeping existing configuration unchanged" in second.stdout
