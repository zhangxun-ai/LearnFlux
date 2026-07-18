"""
Transcriber unit tests.

Covers:
- Successful transcription flow
- Error handling when transcription fails
- File not found handling

All console output must be in English only (no emoji, no Chinese).
"""

import os
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


from video_transcript_api.transcriber import Transcriber


class TestTranscriber(unittest.TestCase):
    """Test transcriber core flow."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_config = {
            "capswriter": {
                "server_url": "ws://localhost:6006"
            },
            "storage": {
                "output_dir": self.temp_dir
            }
        }

        # Create a fake audio file
        self.test_audio_file = os.path.join(self.temp_dir, "test_audio.mp3")
        with open(self.test_audio_file, "w", encoding="utf-8") as f:
            f.write("fake audio")

    def tearDown(self):
        """Clean up test files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch("video_transcript_api.transcriber.transcriber.CapsWriterClient")
    def test_transcribe_success(self, mock_client_cls):
        """Successful transcription should return transcript text."""
        # Create a fake .txt output file
        txt_path = os.path.join(self.temp_dir, "test_output.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("This is the transcribed text.")

        # Mock client
        mock_client = MagicMock()
        mock_client.transcribe_file.return_value = (True, [Path(txt_path)])
        mock_client_cls.return_value = mock_client

        transcriber = Transcriber(config=self.test_config)
        result = transcriber.transcribe(self.test_audio_file, "test_output")

        mock_client.transcribe_file.assert_called_once_with(self.test_audio_file)
        self.assertIn("transcript", result)
        self.assertEqual(result["transcript"], "This is the transcribed text.")

    @patch("video_transcript_api.transcriber.transcriber.CapsWriterClient")
    def test_transcribe_failure(self, mock_client_cls):
        """Failed transcription should raise RuntimeError."""
        mock_client = MagicMock()
        mock_client.transcribe_file.return_value = (False, [])
        mock_client_cls.return_value = mock_client

        transcriber = Transcriber(config=self.test_config)

        with self.assertRaises(RuntimeError):
            transcriber.transcribe(self.test_audio_file, "test_output")

    @patch("video_transcript_api.transcriber.transcriber.CapsWriterClient")
    def test_transcribe_file_not_found(self, mock_client_cls):
        """Non-existent audio file should raise FileNotFoundError."""
        mock_client_cls.return_value = MagicMock()

        transcriber = Transcriber(config=self.test_config)

        with self.assertRaises(FileNotFoundError):
            transcriber.transcribe("/nonexistent/audio.mp3", "test_output")

    @patch("subprocess.run")
    @patch("video_transcript_api.transcriber.transcriber.CapsWriterClient")
    def test_local_whisper_returns_segment_timestamps(self, mock_client_cls, mock_run):
        """Local Whisper JSON output should be converted into seekable segments."""
        binary_path = os.path.join(self.temp_dir, "mlx_whisper")
        with open(binary_path, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        os.chmod(binary_path, 0o755)

        config = {
            **self.test_config,
            "local_whisper": {
                "enabled": True,
                "binary": binary_path,
                "model": "test-model",
                "timeout": 10,
            },
        }

        def fake_run(cmd, **kwargs):
            json_path = os.path.join(self.temp_dir, "local_output.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "text": "First sentence. Second sentence.",
                        "segments": [
                            {"start": 0.0, "end": 1.5, "text": "First sentence."},
                            {"start": 1.5, "end": 3.0, "text": "Second sentence."},
                        ],
                    },
                    f,
                )
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_client_cls.return_value = MagicMock()
        mock_run.side_effect = fake_run
        transcriber = Transcriber(config=config)
        transcriber.output_dir = self.temp_dir

        result = transcriber.transcribe(self.test_audio_file, "local_output")

        command = mock_run.call_args.args[0]
        self.assertIn("--output-format", command)
        self.assertIn("json", command)
        self.assertEqual(result["transcript"], "First sentence. Second sentence.")
        self.assertEqual(result["funasr_json_data"]["segments"][0]["start_time"], 0.0)
        self.assertEqual(result["funasr_json_data"]["segments"][1]["end_time"], 3.0)

    def test_local_whisper_keeps_timestamps_beyond_one_thousand_seconds(self):
        """Whisper timestamps are seconds even for long media."""
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


if __name__ == '__main__':
    unittest.main()
