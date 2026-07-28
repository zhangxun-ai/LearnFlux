"""Local filesystem browsing helpers for self-hosted path import UX.

Used so users can *select* a machine folder instead of typing an absolute path
into a browser prompt. Only lists directories + media counts; never copies files.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".m4v",
    ".mp3",
    ".m4a",
    ".wav",
    ".aac",
    ".flac",
}
DOCUMENT_EXTS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".log",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
}


def default_browse_roots() -> List[Dict[str, str]]:
    roots: List[Dict[str, str]] = []
    home = Path.home()
    if home.is_dir():
        roots.append({"name": "个人主目录", "path": str(home)})
    cwd = Path.cwd()
    if cwd.is_dir() and str(cwd.resolve()) != str(home.resolve()):
        roots.append({"name": "当前工作目录", "path": str(cwd)})
    volumes = Path("/Volumes")
    if volumes.is_dir():
        for child in sorted(volumes.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() and not child.name.startswith("."):
                roots.append({"name": f"磁盘 · {child.name}", "path": str(child)})
    # Deduplicate by resolved path.
    seen = set()
    unique: List[Dict[str, str]] = []
    for item in roots:
        key = str(Path(item["path"]).resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


class LocalFolderPickCancelled(Exception):
    """User dismissed the native folder chooser."""


class LocalFolderPickUnavailable(Exception):
    """Native folder chooser cannot run in this environment."""


def pick_local_directory_native(prompt: str = "选择要导入的本机课程文件夹") -> str:
    """Open the OS-native folder picker on the machine running the API.

    For local self-hosted use this matches Finder/Explorer UX. Remote headless
    servers should fall back to browse UI.
    """
    system = platform.system()
    prompt_text = (prompt or "选择文件夹").replace('"', '\\"')
    try:
        if system == "Darwin":
            script = (
                f'POSIX path of (choose folder with prompt "{prompt_text}")'
            )
            completed = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            if completed.returncode != 0:
                # User cancel is typically -128 from AppleScript.
                if (
                    completed.returncode in {1, -128, 255}
                    or "-128" in stderr
                    or "User canceled" in stderr
                    or "用户已取消" in stderr
                ):
                    raise LocalFolderPickCancelled("已取消选择文件夹")
                raise LocalFolderPickUnavailable(
                    stderr or stdout or "无法打开系统文件夹选择器"
                )
            path = stdout.rstrip("/").strip()
            if not path:
                raise LocalFolderPickCancelled("已取消选择文件夹")
            return str(Path(path).expanduser().resolve())

        if system == "Windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                f"$d.Description = '{prompt_text}'; "
                "$d.ShowNewFolderButton = $false; "
                "if ($d.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 1 }; "
                "Write-Output $d.SelectedPath"
            )
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            if completed.returncode != 0:
                raise LocalFolderPickCancelled("已取消选择文件夹")
            path = (completed.stdout or "").strip()
            if not path:
                raise LocalFolderPickCancelled("已取消选择文件夹")
            return str(Path(path).expanduser().resolve())

        # Linux desktop (best-effort).
        for command in (
            ["zenity", "--file-selection", "--directory", f"--title={prompt}"],
            ["kdialog", "--getexistingdirectory", str(Path.home())],
        ):
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    check=False,
                )
            except FileNotFoundError:
                continue
            if completed.returncode != 0:
                raise LocalFolderPickCancelled("已取消选择文件夹")
            path = (completed.stdout or "").strip()
            if path:
                return str(Path(path).expanduser().resolve())

        raise LocalFolderPickUnavailable(
            "当前环境无法打开系统文件夹选择器，请使用目录浏览"
        )
    except (LocalFolderPickCancelled, LocalFolderPickUnavailable):
        raise
    except subprocess.TimeoutExpired as exc:
        raise LocalFolderPickUnavailable("选择文件夹超时") from exc
    except OSError as exc:
        raise LocalFolderPickUnavailable(f"无法打开系统文件夹选择器：{exc}") from exc


def browse_local_directory(path: str = "") -> Dict[str, Any]:
    """Return parent, children directories, and media counts for ``path``."""
    raw = (path or "").strip()
    if not raw:
        home = Path.home()
        target = home if home.is_dir() else Path.cwd()
    else:
        target = Path(raw).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        else:
            target = target.resolve()

    if not target.exists():
        raise FileNotFoundError(f"路径不存在：{target}")
    if not target.is_dir():
        raise NotADirectoryError(f"不是文件夹：{target}")
    if not os.access(target, os.R_OK | os.X_OK):
        raise PermissionError(f"没有权限访问：{target}")

    entries: List[Dict[str, Any]] = []
    media_files = 0
    video_files = 0
    document_files = 0

    try:
        children = list(target.iterdir())
    except OSError as exc:
        raise PermissionError(f"无法读取目录：{target} ({exc})") from exc

    for child in sorted(
        children,
        key=lambda item: (not item.is_dir(), item.name.lower()),
    ):
        name = child.name
        if name.startswith("."):
            continue
        try:
            if child.is_dir():
                if name in {"__MACOSX", "node_modules", ".git", ".Trash"}:
                    continue
                entries.append(
                    {
                        "name": name,
                        "path": str(child),
                        "type": "dir",
                    }
                )
                continue
            if not child.is_file():
                continue
            ext = child.suffix.lower()
            if ext in VIDEO_EXTS:
                media_files += 1
                video_files += 1
            elif ext in DOCUMENT_EXTS:
                media_files += 1
                document_files += 1
        except OSError:
            continue

    parent: Optional[str]
    try:
        parent_path = target.parent
        parent = str(parent_path) if parent_path != target else None
    except Exception:
        parent = None

    return {
        "path": str(target),
        "name": target.name or str(target),
        "parent": parent,
        "entries": entries,
        "media_count": media_files,
        "video_count": video_files,
        "document_count": document_files,
        "roots": default_browse_roots(),
    }
