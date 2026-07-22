from __future__ import annotations

import logging

import pytest

from video_transcript_api.transcriber.online_runtime import OnlineRuntimeSettings
from video_transcript_api.transcriber.object_store import (
    LocalObjectStore,
    ObjectStoreError,
    S3ObjectStore,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def upload_file(self, filename, bucket, key, **kwargs):
        self.calls.append(
            ("upload_file", {"bucket": bucket, "key": key, **kwargs})
        )

    def head_object(self, **kwargs):
        self.calls.append(("head_object", kwargs))
        return {"ContentLength": 5, "ETag": '"opaque-etag"'}

    def download_file(self, bucket, key, filename):
        self.calls.append(("download_file", {"bucket": bucket, "key": key}))

    def delete_object(self, **kwargs):
        self.calls.append(("delete_object", kwargs))

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.calls.append(
            (
                "generate_presigned_url",
                {"operation": operation, "key": Params["Key"], "ttl": ExpiresIn},
            )
        )
        return "https://object.invalid/private?Signature=sensitive-value"


def test_local_object_store_round_trip_stays_under_private_root(tmp_path) -> None:
    root = tmp_path / "private-objects"
    store = LocalObjectStore(root)
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"media")
    key = store.new_key(
        owner_user_id="user-1", task_id="task-1", category="source", suffix=".mp4"
    )

    metadata = store.put_file(key, source)
    destination = tmp_path / "downloaded.mp4"
    store.download_to(key, destination)

    assert destination.read_bytes() == b"media"
    assert metadata.key == key and metadata.size == 5
    assert root.resolve() in (root / key).resolve().parents
    assert "lesson" not in key
    store.delete(key)
    assert store.head(key) is None


def test_s3_store_uses_private_generated_key_and_short_presign(tmp_path) -> None:
    client = FakeS3Client()
    store = S3ObjectStore(
        client=client,
        bucket="private-media",
        presign_ttl_seconds=300,
    )
    source = tmp_path / "customer-filename.mp3"
    source.write_bytes(b"media")
    key = store.new_key(
        owner_user_id="user-1", task_id="task-1", category="asr", suffix=".mp3"
    )

    store.put_file(key, source)
    access = store.presign_get(key)

    upload = client.calls[0]
    presign = client.calls[-1]
    assert upload[0] == "upload_file"
    assert upload[1]["key"] == key
    assert upload[1].get("ExtraArgs") in (None, {"ACL": "private"})
    assert "customer-filename" not in key
    assert presign[1]["operation"] == "get_object"
    assert presign[1]["ttl"] == 300
    assert access.expires_in_seconds == 300


def test_object_key_traversal_and_public_acl_are_rejected(tmp_path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"x")
    local = LocalObjectStore(tmp_path / "objects")

    with pytest.raises(ObjectStoreError, match="invalid_object_key"):
        local.put_file("../outside", source)
    with pytest.raises(ObjectStoreError, match="public_acl_forbidden"):
        S3ObjectStore(
            client=FakeS3Client(),
            bucket="private-media",
            acl="public-read",
        )


def test_signed_url_and_credentials_are_absent_from_repr_and_logs(
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    store = S3ObjectStore(
        client=FakeS3Client(),
        bucket="private-media",
        presign_ttl_seconds=120,
    )
    access = store.presign_put("source/opaque/key")

    rendered = repr(store) + repr(access) + caplog.text
    assert "sensitive-value" not in rendered
    assert "Signature=" not in rendered
    assert "private-media" not in repr(store)


def test_runtime_selects_s3_store_from_validated_settings(monkeypatch) -> None:
    from video_transcript_api.api import context

    settings = OnlineRuntimeSettings(object_backend="s3")
    selected = object()
    monkeypatch.setattr(context, "get_online_runtime_settings", lambda: settings)
    monkeypatch.setattr(
        context.S3ObjectStore,
        "from_settings",
        classmethod(lambda cls, current: selected),
    )
    context.get_transcription_object_store.cache_clear()
    try:
        assert context.get_transcription_object_store() is selected
    finally:
        context.get_transcription_object_store.cache_clear()
