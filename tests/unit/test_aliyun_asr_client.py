"""Unit tests for the production Aliyun Bailian ASR protocol client."""

from io import BytesIO

import pytest
import requests


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, outcomes):
        self._outcomes = iter(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        return self._call("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._call("POST", url, kwargs)

    def _call(self, method, url, kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.mark.unit
def test_credentials_load_only_from_explicit_environment_mapping():
    from video_transcript_api.transcriber.aliyun_client import (
        AliyunCredentials,
        PreflightError,
    )

    credentials = AliyunCredentials.from_environ(
        {
            "DASHSCOPE_API_KEY": "api-secret",
            "DASHSCOPE_WORKSPACE_ID": "workspace-1",
            "DASHSCOPE_API_HOST": (
                "https://workspace-1.cn-beijing.maas.aliyuncs.com"
            ),
        }
    )

    assert credentials.api_key == "api-secret"
    assert credentials.workspace_id == "workspace-1"
    assert credentials.api_host == (
        "https://workspace-1.cn-beijing.maas.aliyuncs.com"
    )

    with pytest.raises(PreflightError) as error:
        AliyunCredentials.from_environ({})

    assert error.value.code == "missing_credentials"
    assert str(error.value) == "missing_credentials"


@pytest.mark.unit
def test_client_rejects_non_workspace_https_origin_without_disclosure():
    from video_transcript_api.transcriber.aliyun_client import (
        AliyunASRClient,
        PreflightError,
    )

    invalid_origins = [
        ("unsafe/workspace", None),
        ("-", None),
        ("workspace-1", "http://workspace-1.cn-beijing.maas.aliyuncs.com"),
        ("workspace-1", "https://other.cn-beijing.maas.aliyuncs.com"),
        (
            "workspace-1",
            "https://workspace-1.cn-beijing.maas.aliyuncs.com/secret-path",
        ),
        (
            "workspace-1",
            "https://user@workspace-1.cn-beijing.maas.aliyuncs.com:443",
        ),
    ]

    sentinel = "secret-path"
    for workspace_id, api_host in invalid_origins:
        with pytest.raises(PreflightError) as error:
            AliyunASRClient(
                api_key="api-secret",
                workspace_id=workspace_id,
                api_host=api_host,
                session=object(),
            )

        assert error.value.code == "invalid_host"
        assert str(error.value) == "invalid_host"
        assert sentinel not in str(error.value)


@pytest.mark.unit
def test_upload_audio_stages_one_object_and_rejects_incomplete_policy():
    from video_transcript_api.transcriber.aliyun_client import (
        AliyunASRClient,
        AliyunASRError,
    )

    policy = {
        "policy": "encoded-policy",
        "signature": "signed-value",
        "upload_dir": "uploads/temporary",
        "upload_host": "https://signed-upload.example",
        "oss_access_key_id": "temporary-access-id",
        "x_oss_object_acl": "private",
        "x_oss_forbid_overwrite": "true",
    }
    session = _FakeSession([_FakeResponse({"data": policy}), _FakeResponse({})])
    client = AliyunASRClient("api-secret", "workspace-1", session=session)
    audio = BytesIO(b"audio")

    staged_uri = client.upload_audio(audio, "sample.wav")

    assert staged_uri == "oss://uploads/temporary/sample.wav"
    assert session.calls[0] == {
        "method": "GET",
        "url": "https://dashscope.aliyuncs.com/api/v1/uploads",
        "headers": {
            "Authorization": "Bearer api-secret",
            "Content-Type": "application/json",
        },
        "params": {"action": "getPolicy", "model": "fun-asr-2025-11-07"},
        "timeout": 30,
    }
    assert session.calls[1] == {
        "method": "POST",
        "url": "https://signed-upload.example",
        "data": {
            "OSSAccessKeyId": "temporary-access-id",
            "Signature": "signed-value",
            "policy": "encoded-policy",
            "x-oss-object-acl": "private",
            "x-oss-forbid-overwrite": "true",
            "key": "uploads/temporary/sample.wav",
            "success_action_status": "200",
        },
        "files": {
            "file": ("sample.wav", audio, "application/octet-stream"),
        },
        "timeout": 120,
        "allow_redirects": False,
    }

    invalid_session = _FakeSession([_FakeResponse({"data": {"policy": "only"}})])
    invalid_client = AliyunASRClient(
        "api-secret", "workspace-1", session=invalid_session
    )
    with pytest.raises(AliyunASRError) as error:
        invalid_client.upload_audio(BytesIO(b"audio"), "sample.wav")

    assert error.value.code == "invalid_response"
    assert [call["method"] for call in invalid_session.calls] == ["GET"]


@pytest.mark.unit
def test_submit_posts_one_fixed_model_task_and_requires_known_identity():
    from video_transcript_api.transcriber.aliyun_client import (
        AliyunASRClient,
        AliyunASRError,
    )

    session = _FakeSession(
        [
            _FakeResponse(
                {"output": {"task_id": "task-1", "task_status": "PENDING"}}
            )
        ]
    )
    client = AliyunASRClient("api-secret", "workspace-1", session=session)

    result = client.submit(
        "oss://uploads/temporary/sample.wav",
        ["zh", "en"],
        diarization_enabled=True,
        speaker_count=2,
    )

    assert result == {"task_id": "task-1", "status": "PENDING"}
    assert session.calls == [
        {
            "method": "POST",
            "url": (
                "https://workspace-1.cn-beijing.maas.aliyuncs.com"
                "/api/v1/services/audio/asr/transcription"
            ),
            "headers": {
                "Authorization": "Bearer api-secret",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
                "X-DashScope-OssResourceResolve": "enable",
                "X-DashScope-WorkSpace": "workspace-1",
            },
            "json": {
                "model": "fun-asr-2025-11-07",
                "input": {"file_urls": ["oss://uploads/temporary/sample.wav"]},
                "parameters": {
                    "language_hints": ["zh", "en"],
                    "diarization_enabled": True,
                    "speaker_count": 2,
                },
            },
            "timeout": 30,
            "allow_redirects": False,
        }
    ]

    invalid_client = AliyunASRClient(
        "api-secret",
        "workspace-1",
        session=_FakeSession(
            [_FakeResponse({"output": {"task_id": "", "task_status": "UNKNOWN"}})]
        ),
    )
    with pytest.raises(AliyunASRError) as error:
        invalid_client.submit("oss://uploads/temporary/sample.wav", ["zh"])

    assert error.value.code == "invalid_response"


@pytest.mark.unit
def test_submit_timeout_is_safe_and_never_retries(caplog):
    from video_transcript_api.transcriber.aliyun_client import (
        AliyunASRClient,
        PotentiallyAcceptedError,
    )

    sentinel = "SENTINEL_SIGNED_REQUEST_DETAIL"
    session = _FakeSession([requests.exceptions.Timeout(sentinel)])
    client = AliyunASRClient("api-secret", "workspace-1", session=session)

    with pytest.raises(PotentiallyAcceptedError) as error:
        client.submit("oss://uploads/temporary/sample.wav", ["zh"])

    assert error.value.code == "submission_unknown"
    assert str(error.value) == "submission_unknown"
    assert sentinel not in str(error.value)
    assert sentinel not in caplog.text
    assert len(session.calls) == 1
    assert session.calls[0]["method"] == "POST"


@pytest.mark.unit
def test_poll_timeout_queries_only_the_same_task_id():
    from video_transcript_api.transcriber.aliyun_client import (
        AliyunASRClient,
        PollTimeoutError,
    )

    running = _FakeResponse(
        {"output": {"task_id": "task-1", "task_status": "RUNNING"}}
    )
    session = _FakeSession([running, running])
    clock_values = iter([0.0, 0.4, 0.9, 1.1])
    sleeps = []
    client = AliyunASRClient(
        "api-secret",
        "workspace-1",
        session=session,
        clock=lambda: next(clock_values),
        sleep=sleeps.append,
    )

    with pytest.raises(PollTimeoutError) as error:
        client.poll("task-1", poll_interval_seconds=0.5, timeout_seconds=1)

    assert error.value.code == "polling_unknown"
    task_url = (
        "https://workspace-1.cn-beijing.maas.aliyuncs.com/api/v1/tasks/task-1"
    )
    assert [(call["method"], call["url"]) for call in session.calls] == [
        ("GET", task_url),
        ("GET", task_url),
    ]
    assert sleeps == [0.5]

    network_session = _FakeSession(
        [requests.exceptions.Timeout("SENTINEL_POLL_REQUEST")]
    )
    network_client = AliyunASRClient(
        "api-secret",
        "workspace-1",
        session=network_session,
        clock=lambda: 0,
    )
    with pytest.raises(PollTimeoutError) as network_error:
        network_client.poll("task-1", timeout_seconds=1)

    assert network_error.value.code == "polling_unknown"
    assert str(network_error.value) == "polling_unknown"
    assert [(call["method"], call["url"]) for call in network_session.calls] == [
        ("GET", task_url)
    ]

    ssl_session = _FakeSession(
        [requests.exceptions.SSLError("SENTINEL_POLL_SSL")]
    )
    ssl_client = AliyunASRClient(
        "api-secret", "workspace-1", session=ssl_session, clock=lambda: 0
    )
    with pytest.raises(PollTimeoutError) as ssl_error:
        ssl_client.poll("task-1", timeout_seconds=1)
    assert ssl_error.value.code == "polling_unknown"
    assert str(ssl_error.value) == "polling_unknown"


@pytest.mark.unit
def test_poll_success_downloads_only_successful_transcript_and_normalizes_it():
    from video_transcript_api.transcriber.aliyun_client import (
        AliyunASRClient,
        AliyunASRError,
    )

    signed_url = "https://signed.example/transcript.json?token=secret"
    skipped_url = "https://signed.example/failed.json?token=other-secret"
    session = _FakeSession(
        [
            _FakeResponse(
                {
                    "output": {
                        "task_status": "SUCCEEDED",
                        "results": [
                            {
                                "subtask_status": "FAILED",
                                "transcription_url": skipped_url,
                            },
                            {
                                "subtask_status": "SUCCEEDED",
                                "transcription_url": signed_url,
                            },
                        ],
                    },
                    "usage": {"duration": 12.5},
                }
            ),
            _FakeResponse(
                {
                    "transcripts": [
                        {
                            "text": "Hello world",
                            "sentences": [
                                {
                                    "text": "Hello world",
                                    "begin_time": 100,
                                    "end_time": 900,
                                    "speaker_id": 1,
                                    "words": [
                                        {
                                            "text": "Hello",
                                            "begin_time": 100,
                                            "end_time": 400,
                                            "speaker_id": 1,
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ),
        ]
    )
    client = AliyunASRClient(
        "api-secret", "workspace-1", session=session, clock=lambda: 0
    )

    result = client.poll("task-1", timeout_seconds=30)

    assert result == {
        "task_id": "task-1",
        "status": "SUCCEEDED",
        "usage_seconds": 12.5,
        "results": [
            {"status": "FAILED"},
            {
                "status": "SUCCEEDED",
                "transcript": {
                    "text": "Hello world",
                    "sentences": [
                        {
                            "text": "Hello world",
                            "start_time": 0.1,
                            "end_time": 0.9,
                            "speaker": 1,
                            "words": [
                                {
                                    "text": "Hello",
                                    "start_time": 0.1,
                                    "end_time": 0.4,
                                    "speaker": 1,
                                }
                            ],
                        }
                    ],
                },
            },
        ],
    }
    assert [(call["method"], call["url"]) for call in session.calls] == [
        (
            "GET",
            "https://workspace-1.cn-beijing.maas.aliyuncs.com/api/v1/tasks/task-1",
        ),
        ("GET", signed_url),
    ]
    rendered = repr(result)
    assert "https://" not in rendered
    assert "token=secret" not in rendered

    failed_session = _FakeSession(
        [_FakeResponse({"output": {"task_status": "FAILED", "results": []}})]
    )
    failed_client = AliyunASRClient(
        "api-secret", "workspace-1", session=failed_session, clock=lambda: 0
    )
    with pytest.raises(AliyunASRError) as failed_error:
        failed_client.poll("task-failed", timeout_seconds=30)

    assert failed_error.value.code == "provider_failed"
    assert str(failed_error.value) == "provider_failed"

    expired_url = "https://signed.example/expired.json?token=EXPIRED_SENTINEL"
    expired_session = _FakeSession(
        [
            _FakeResponse(
                {
                    "output": {
                        "task_status": "SUCCEEDED",
                        "results": [
                            {
                                "subtask_status": "SUCCEEDED",
                                "transcription_url": expired_url,
                            }
                        ],
                    },
                    "usage": {"duration": 7.5},
                }
            ),
            _FakeResponse({}, status_code=403),
        ]
    )
    expired_client = AliyunASRClient(
        "api-secret", "workspace-1", session=expired_session, clock=lambda: 0
    )
    with pytest.raises(AliyunASRError) as expired_error:
        expired_client.poll("task-expired", timeout_seconds=30)

    assert expired_error.value.code == "result_expired"
    assert expired_error.value.usage_seconds == 7.5
    assert str(expired_error.value) == "result_expired"
    assert "EXPIRED_SENTINEL" not in str(expired_error.value)

    empty_session = _FakeSession(
        [
            _FakeResponse(
                {
                    "output": {"task_status": "SUCCEEDED", "results": []},
                    "usage": {"duration": 1},
                }
            )
        ]
    )
    empty_client = AliyunASRClient(
        "api-secret", "workspace-1", session=empty_session, clock=lambda: 0
    )
    with pytest.raises(AliyunASRError) as empty_error:
        empty_client.poll("task-empty", timeout_seconds=30)

    assert empty_error.value.code == "invalid_response"

    invalid_usage_session = _FakeSession(
        [
            _FakeResponse(
                {
                    "output": {
                        "task_status": "SUCCEEDED",
                        "results": [
                            {
                                "subtask_status": "SUCCEEDED",
                                "transcription_url": signed_url,
                            }
                        ],
                    },
                    "usage": {"duration": True},
                }
            ),
            _FakeResponse({"transcripts": [{"text": "Valid text"}]}),
        ]
    )
    invalid_usage_client = AliyunASRClient(
        "api-secret",
        "workspace-1",
        session=invalid_usage_session,
        clock=lambda: 0,
    )
    with pytest.raises(AliyunASRError) as usage_error:
        invalid_usage_client.poll("task-invalid-usage", timeout_seconds=30)

    assert usage_error.value.code == "invalid_response"

    silent_session = _FakeSession(
        [
            _FakeResponse(
                {
                    "output": {
                        "task_status": "SUCCEEDED",
                        "results": [
                            {
                                "subtask_status": "SUCCEEDED",
                                "transcription_url": signed_url,
                            }
                        ],
                    }
                }
            ),
            _FakeResponse({"transcripts": [{"text": ""}]}),
        ]
    )
    silent_client = AliyunASRClient(
        "api-secret", "workspace-1", session=silent_session, clock=lambda: 0
    )

    silent_result = silent_client.poll("task-silent", timeout_seconds=30)

    assert silent_result["results"][0]["transcript"]["text"] == ""
