from pathlib import Path

import pytest

from video_transcript_api.reading import assets


PNG = b"\x89PNG\r\n\x1a\n" + b"payload"


def test_asset_write_read_and_delete_are_owner_scoped(tmp_path):
    item = assets.ParsedAsset.from_bytes(PNG, "image/png", alt="diagram")

    written = assets.write_document_assets(
        tmp_path, "owner-a", "doc-1", [item]
    )

    assert written == {item.safe_name}
    stored, mime = assets.resolve_document_asset(
        tmp_path, "owner-a", "doc-1", item.safe_name
    )
    assert stored.read_bytes() == PNG
    assert mime == "image/png"
    with pytest.raises(assets.ReadingAssetError, match="asset_not_found"):
        assets.resolve_document_asset(
            tmp_path, "owner-b", "doc-1", item.safe_name
        )
    assert assets.delete_document_assets(
        tmp_path, "owner-a", "doc-1"
    ) is True
    assert not stored.exists()


def test_assets_reject_active_or_mismatched_content(tmp_path):
    with pytest.raises(assets.ReadingAssetError, match="unsupported_asset_type"):
        assets.ParsedAsset.from_bytes(b"<svg></svg>", "image/svg+xml")

    with pytest.raises(assets.ReadingAssetError, match="asset_signature_mismatch"):
        assets.ParsedAsset.from_bytes(b"not png", "image/png")

    with pytest.raises(assets.ReadingAssetError, match="invalid_asset_name"):
        assets.resolve_document_asset(
            tmp_path, "owner-a", "doc-1", "../secret.png"
        )


def test_asset_directory_validation_rejects_unmanaged_path(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(assets.ReadingAssetError, match="unmanaged_asset_path"):
        assets.validate_document_asset_dir(outside, data_root=tmp_path / "data")

