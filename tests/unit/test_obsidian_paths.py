from pathlib import Path

import pytest


def test_resolve_vault_path_accepts_only_safe_relative_paths(tmp_path):
    from video_transcript_api.obsidian.paths import VaultPathError, resolve_vault_path

    vault = tmp_path / "vault"
    (vault / "raw" / "课程").mkdir(parents=True)

    assert resolve_vault_path(vault, "raw/课程") == (vault / "raw" / "课程").resolve()
    for unsafe in ("/tmp/file", "../outside", "raw/../.obsidian", "raw/\x00bad"):
        with pytest.raises(VaultPathError):
            resolve_vault_path(vault, unsafe)


def test_resolve_vault_path_rejects_symlink_escape(tmp_path):
    from video_transcript_api.obsidian.paths import VaultPathError, resolve_vault_path

    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (vault / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(VaultPathError):
        resolve_vault_path(vault, "escape/file.md")


def test_list_directories_hides_dot_directories_and_escaped_links(tmp_path):
    from video_transcript_api.obsidian.paths import list_vault_directories

    vault = tmp_path / "vault"
    (vault / "raw" / "课程A").mkdir(parents=True)
    (vault / "raw" / ".private").mkdir()
    (vault / ".obsidian").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "raw" / "escaped").symlink_to(outside, target_is_directory=True)

    assert list_vault_directories(vault, root="raw") == ["raw", "raw/课程A"]
    assert list_vault_directories(vault, root="vault", query="课程") == ["raw/课程A"]


def test_create_directory_requires_one_safe_name(tmp_path):
    from video_transcript_api.obsidian.paths import VaultPathError, create_vault_directory

    vault = tmp_path / "vault"
    (vault / "课程").mkdir(parents=True)

    created = create_vault_directory(vault, "课程", "笔记")
    assert created == "课程/笔记"
    assert (vault / created).is_dir()

    for unsafe in ("../笔记", "子目录/笔记", ".hidden"):
        with pytest.raises(VaultPathError):
            create_vault_directory(vault, "课程", unsafe)


def test_sanitize_filename_preserves_unicode_and_removes_reserved_characters():
    from video_transcript_api.obsidian.paths import sanitize_markdown_filename

    assert sanitize_markdown_filename(' 第01课：A/B? "重点". ') == "第01课：A-B- -重点-.md"
    assert sanitize_markdown_filename("  ...  ", fallback="lesson") == "lesson.md"


def _managed_markdown(identity: dict[str, str], body: str = "body") -> str:
    fields = "\n".join(f"{key}: {value}" for key, value in identity.items())
    return f"---\n{fields}\n---\n\n{body}\n"


def test_find_managed_files_uses_exact_stable_identity(tmp_path):
    from video_transcript_api.obsidian.paths import find_managed_markdown_files

    vault = tmp_path / "vault"
    target = vault / "raw" / "课程"
    target.mkdir(parents=True)
    identity = {
        "type": "transcript",
        "source": "LearnFlux",
        "vta_collection_id": "course-1",
        "vta_source_id": "lesson-1",
    }
    (target / "renamed.md").write_text(_managed_markdown(identity), encoding="utf-8")
    (target / "other.md").write_text(
        _managed_markdown({**identity, "vta_source_id": "lesson-2"}), encoding="utf-8"
    )

    assert find_managed_markdown_files(vault, "raw/课程", identity) == [
        "raw/课程/renamed.md"
    ]
    assert find_managed_markdown_files(vault, "raw/课程", {**identity, "vta_source_id": "none"}) == []

    (target / "duplicate.md").write_text(_managed_markdown(identity), encoding="utf-8")
    assert len(find_managed_markdown_files(vault, "raw/课程", identity)) == 2


def test_find_managed_files_recovers_legacy_brand_identity(tmp_path):
    from video_transcript_api.obsidian.paths import find_managed_markdown_files

    vault = tmp_path / "vault"
    target = vault / "notes"
    target.mkdir(parents=True)
    current_identity = {
        "type": "study-note",
        "source": "LearnFlux",
        "vta_view_token": "view-1",
    }
    legacy_identity = {**current_identity, "source": "VideoTranscriptAPI"}
    (target / "existing.md").write_text(
        _managed_markdown(legacy_identity), encoding="utf-8"
    )

    assert find_managed_markdown_files(vault, "notes", current_identity) == [
        "notes/existing.md"
    ]


def test_allocate_path_recovers_identity_and_protects_unknown_same_name(tmp_path):
    from video_transcript_api.obsidian.paths import allocate_managed_markdown_path

    vault = tmp_path / "vault"
    directory = vault / "raw" / "课程"
    directory.mkdir(parents=True)
    identity = {
        "type": "transcript",
        "source": "LearnFlux",
        "vta_view_token": "view-1",
    }
    (directory / "第1课.md").write_text("user file", encoding="utf-8")

    allocated = allocate_managed_markdown_path(vault, "raw/课程", "第1课", identity)
    assert allocated == "raw/课程/第1课 (2).md"

    (directory / "renamed.md").write_text(_managed_markdown(identity), encoding="utf-8")
    assert allocate_managed_markdown_path(vault, "raw/课程", "第1课", identity) == (
        "raw/课程/renamed.md"
    )


def test_atomic_write_replaces_in_same_directory_and_cleans_temp_file(tmp_path, monkeypatch):
    import video_transcript_api.obsidian.paths as paths

    vault = tmp_path / "vault"
    directory = vault / "notes"
    directory.mkdir(parents=True)
    target = directory / "lesson.md"
    target.write_text("old", encoding="utf-8")
    replaced = {}
    real_replace = paths.os.replace

    def capture_replace(source, destination):
        replaced["source_parent"] = Path(source).parent
        replaced["destination"] = Path(destination)
        real_replace(source, destination)

    monkeypatch.setattr(paths.os, "replace", capture_replace)
    paths.atomic_write_text(vault, "notes/lesson.md", "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert replaced == {"source_parent": directory, "destination": target}
    assert list(directory.glob(".vta-*.tmp")) == []
