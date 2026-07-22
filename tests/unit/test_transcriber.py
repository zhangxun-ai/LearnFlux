"""Unit tests for the backward-compatible Transcriber facade."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from video_transcript_api.transcriber import Transcriber
from video_transcript_api.transcriber import transcriber as transcriber_module
from video_transcript_api.transcriber.contracts import (
    TranscriptionContext,
    TranscriptionResult,
)


class TestTranscriber(unittest.TestCase):
    """Test provider selection and legacy result compatibility."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_config = {
            "capswriter": {
                "server_url": "ws://localhost:6006",
            },
            "storage": {
                "output_dir": self.temp_dir,
            },
        }
        self.test_audio_file = os.path.join(self.temp_dir, "test_audio.mp3")
        Path(self.test_audio_file).write_bytes(b"fake audio")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @staticmethod
    def _result(provider="capswriter"):
        return TranscriptionResult(
            transcript="This is the transcribed text.",
            txt_path="/tmp/test_output.txt",
            funasr_json_data={"segments": []},
            generated_files=(Path("/tmp/test_output.txt"),),
            provider=provider,
            model="test-model" if provider == "local_whisper" else None,
            elapsed_seconds=1.0,
        )

    @patch("video_transcript_api.transcriber.transcriber.LocalWhisperProvider")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_missing_local_config_selects_capswriter(
        self, capswriter_provider_cls, local_provider_cls
    ):
        progress_callback = MagicMock()
        provider = capswriter_provider_cls.return_value
        provider.transcribe.return_value = self._result()
        transcriber = Transcriber(
            config=self.test_config,
            progress_callback=progress_callback,
        )

        result = transcriber.transcribe(self.test_audio_file, "test_output")

        capswriter_provider_cls.assert_called_once_with(
            config=self.test_config,
            output_dir=transcriber.output_dir,
            progress_callback=progress_callback,
        )
        local_provider_cls.assert_not_called()
        provider.transcribe.assert_called_once_with(
            self.test_audio_file, "test_output"
        )
        self.assertEqual(
            result,
            {
                "transcript": "This is the transcribed text.",
                "txt_path": "/tmp/test_output.txt",
                "funasr_json_data": {"segments": []},
                "generated_files": [Path("/tmp/test_output.txt")],
            },
        )

    @patch("video_transcript_api.transcriber.transcriber.LocalWhisperProvider")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_disabled_local_config_selects_capswriter(
        self, capswriter_provider_cls, local_provider_cls
    ):
        config = {**self.test_config, "local_whisper": {"enabled": False}}
        provider = capswriter_provider_cls.return_value
        provider.transcribe.return_value = self._result()

        Transcriber(config=config).transcribe(self.test_audio_file, "result")

        capswriter_provider_cls.assert_called_once()
        local_provider_cls.assert_not_called()

    @patch("video_transcript_api.transcriber.transcriber.LocalWhisperProvider")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_enabled_local_config_selects_only_local_provider(
        self, capswriter_provider_cls, local_provider_cls
    ):
        config = {**self.test_config, "local_whisper": {"enabled": True}}
        provider = local_provider_cls.return_value
        provider.transcribe.return_value = self._result("local_whisper")
        transcriber = Transcriber(config=config)

        result = transcriber.transcribe(self.test_audio_file, "local_output")

        local_provider_cls.assert_called_once_with(
            config=config,
            output_dir=transcriber.output_dir,
        )
        capswriter_provider_cls.assert_not_called()
        provider.transcribe.assert_called_once_with(
            self.test_audio_file, "local_output"
        )
        self.assertEqual(result["transcript"], "This is the transcribed text.")
        self.assertNotIn("provider", result)
        self.assertNotIn("model", result)
        self.assertNotIn("elapsed_seconds", result)

    @patch("video_transcript_api.transcriber.transcriber.LocalWhisperProvider")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_local_strategy_forces_local_provider_when_disabled_in_config(
        self, capswriter_provider_cls, local_provider_cls
    ):
        config = {**self.test_config, "local_whisper": {"enabled": False}}
        provider = local_provider_cls.return_value
        provider.transcribe.return_value = self._result("local_whisper")

        Transcriber(config=config, strategy="local").transcribe(
            self.test_audio_file, "local_output"
        )

        local_provider_cls.assert_called_once()
        capswriter_provider_cls.assert_not_called()

    @patch("video_transcript_api.transcriber.transcriber.LocalWhisperProvider")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_missing_file_is_rejected_before_provider_selection(
        self, capswriter_provider_cls, local_provider_cls
    ):
        transcriber = Transcriber(config=self.test_config)

        with self.assertRaises(FileNotFoundError):
            transcriber.transcribe("/nonexistent/audio.mp3", "test_output")

        capswriter_provider_cls.assert_not_called()
        local_provider_cls.assert_not_called()

    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_default_output_base_uses_audio_stem(self, capswriter_provider_cls):
        provider = capswriter_provider_cls.return_value
        provider.transcribe.return_value = self._result()
        transcriber = Transcriber(config=self.test_config)

        transcriber.transcribe(self.test_audio_file)

        provider.transcribe.assert_called_once_with(self.test_audio_file, "test_audio")

    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_provider_exception_is_propagated(self, capswriter_provider_cls):
        expected_error = RuntimeError("provider failed")
        capswriter_provider_cls.return_value.transcribe.side_effect = expected_error
        transcriber = Transcriber(config=self.test_config)

        with self.assertRaises(RuntimeError) as raised:
            transcriber.transcribe(self.test_audio_file, "test_output")

        self.assertIs(raised.exception, expected_error)

    @patch("video_transcript_api.transcriber.transcriber.LocalWhisperProvider")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    @patch("video_transcript_api.transcriber.transcriber.load_config")
    def test_invalid_strategy_fails_before_config_or_provider_construction(
        self, load_config_mock, capswriter_provider_cls, local_provider_cls
    ):
        with self.assertRaises(ValueError):
            Transcriber(strategy="unsupported")

        load_config_mock.assert_not_called()
        capswriter_provider_cls.assert_not_called()
        local_provider_cls.assert_not_called()

    @patch("video_transcript_api.transcriber.transcriber.LocalWhisperProvider")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_cloud_strategy_requires_context_before_provider_construction(
        self, capswriter_provider_cls, local_provider_cls
    ):
        factory = MagicMock()
        transcriber = Transcriber(
            config=self.test_config,
            strategy="cloud",
            cloud_provider_factory=factory,
        )

        with self.assertRaises(RuntimeError, msg="cloud context is required"):
            transcriber.transcribe(self.test_audio_file, "cloud_output")

        factory.assert_not_called()
        capswriter_provider_cls.assert_not_called()
        local_provider_cls.assert_not_called()

    @patch("video_transcript_api.transcriber.transcriber.LocalWhisperProvider")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_cloud_strategy_requires_an_injected_factory(
        self, capswriter_provider_cls, local_provider_cls
    ):
        transcriber = Transcriber(config=self.test_config, strategy="cloud")

        with self.assertRaises(RuntimeError, msg="cloud factory is required"):
            transcriber.transcribe(
                self.test_audio_file,
                "cloud_output",
                context=TranscriptionContext("task-1", "bilibili", "media-1"),
            )

        capswriter_provider_cls.assert_not_called()
        local_provider_cls.assert_not_called()

    @patch("video_transcript_api.transcriber.transcriber.LocalWhisperProvider")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterProvider")
    def test_cloud_strategy_uses_injected_factory_and_passes_context(
        self, capswriter_provider_cls, local_provider_cls
    ):
        progress_callback = MagicMock()
        context = TranscriptionContext("task-1", "bilibili", "media-1")
        cloud_provider = MagicMock()
        cloud_provider.transcribe.return_value = self._result("cloud")
        factory = MagicMock(return_value=cloud_provider)
        transcriber = Transcriber(
            config=self.test_config,
            progress_callback=progress_callback,
            strategy="cloud",
            cloud_provider_factory=factory,
        )

        result = transcriber.transcribe(
            self.test_audio_file, "cloud_output", context=context
        )

        factory.assert_called_once_with(
            config=self.test_config,
            output_dir=transcriber.output_dir,
            progress_callback=progress_callback,
            context=context,
        )
        cloud_provider.transcribe.assert_called_once_with(
            self.test_audio_file, "cloud_output", context=context
        )
        capswriter_provider_cls.assert_not_called()
        local_provider_cls.assert_not_called()
        self.assertEqual(result["transcript"], "This is the transcribed text.")

    def test_cloud_provider_exception_does_not_log_sensitive_text(self):
        """Cloud provider errors may include signed URLs or remote task metadata."""
        sentinel = "signed-secret-sentinel"
        expected_error = RuntimeError(f"cloud provider failed: {sentinel}")
        cloud_provider = MagicMock()
        cloud_provider.transcribe.side_effect = expected_error
        transcriber = Transcriber(
            config=self.test_config,
            strategy="cloud",
            cloud_provider_factory=MagicMock(return_value=cloud_provider),
        )
        log_messages = []
        sink_id = transcriber_module.logger.add(
            log_messages.append,
            format="{message}",
        )

        try:
            with self.assertRaises(RuntimeError) as raised:
                transcriber.transcribe(
                    self.test_audio_file,
                    "cloud_output",
                    context=TranscriptionContext("task-1", "bilibili", "media-1"),
                )
        finally:
            transcriber_module.logger.remove(sink_id)

        self.assertIs(raised.exception, expected_error)
        self.assertNotIn(sentinel, "".join(log_messages))

    def test_local_whisper_keeps_timestamps_beyond_one_thousand_seconds(self):
        """The legacy private helper must preserve second-based timestamps."""
        payload = {
            "duration": 2010.8,
            "segments": [
                {"start": 999.36, "end": 1001.0, "text": "Before boundary"},
                {"start": 1002.0, "end": 1005.0, "text": "After boundary"},
            ],
        }

        result = Transcriber._whisper_json_to_funasr(payload, "lesson.mp3")

        self.assertEqual(result["duration"], 2010.8)
        self.assertEqual(result["segments"][0]["end_time"], 1001.0)
        self.assertEqual(result["segments"][1]["start_time"], 1002.0)


if __name__ == "__main__":
    unittest.main()
