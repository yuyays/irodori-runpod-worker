from __future__ import annotations

import asyncio
import base64
import os
import sys
import types
import unittest
from unittest.mock import patch

from handler import (
    SynthesisInput,
    handler,
    main,
    parse_job,
    run_speech,
    temporary_voice,
)


def valid_job(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "text": "これはテストです。",
        "reference_audio_base64": base64.b64encode(b"RIFF-audio").decode("ascii"),
        "reference_filename": "voice.wav",
        "num_steps": 10,
    }
    payload.update(overrides)
    return {"input": payload}


class ParseJobTests(unittest.TestCase):
    def test_accepts_a_valid_job(self) -> None:
        result = parse_job(valid_job())

        self.assertEqual(result.text, "これはテストです。")
        self.assertEqual(result.reference_audio, b"RIFF-audio")
        self.assertEqual(result.reference_suffix, ".wav")
        self.assertEqual(result.num_steps, 10)

    def test_rejects_invalid_base64(self) -> None:
        with self.assertRaisesRegex(ValueError, "not valid base64"):
            parse_job(valid_job(reference_audio_base64="%%%"))

    def test_rejects_reference_audio_over_configured_limit(self) -> None:
        with patch.dict(os.environ, {"MAX_REFERENCE_AUDIO_BYTES": "2"}):
            with self.assertRaisesRegex(ValueError, "at most 2 bytes"):
                parse_job(
                    valid_job(
                        reference_audio_base64=base64.b64encode(b"abc").decode("ascii")
                    )
                )

    def test_rejects_unsupported_reference_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported audio extension"):
            parse_job(valid_job(reference_filename="voice.exe"))

    def test_rejects_num_steps_outside_safe_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 40"):
            parse_job(valid_job(num_steps=0))


class FakeRegistry:
    def __init__(self) -> None:
        self.written_id: str | None = None
        self.deleted_id: str | None = None

    def write_file(
        self, *, filename: str, data: bytes, voice_id: str
    ) -> None:
        self.written_id = voice_id

    def delete_file(self, voice_id: str) -> None:
        self.deleted_id = voice_id


class TemporaryVoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = FakeRegistry()
        self.request = SynthesisInput("text", b"audio", ".wav", 10)

    def test_deletes_voice_after_success(self) -> None:
        with temporary_voice(self.registry, self.request):
            pass

        self.assertEqual(self.registry.deleted_id, self.registry.written_id)

    def test_deletes_voice_after_failure(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "synthesis failed"):
            with temporary_voice(self.registry, self.request):
                raise RuntimeError("synthesis failed")

        self.assertEqual(self.registry.deleted_id, self.registry.written_id)


class StartupTests(unittest.TestCase):
    def test_registers_handler_before_importing_irodori_runtime(self) -> None:
        started_with: list[dict[str, object]] = []
        fake_runpod = types.SimpleNamespace(
            serverless=types.SimpleNamespace(
                start=lambda config: started_with.append(config)
            )
        )

        with patch.dict(sys.modules, {"runpod": fake_runpod}):
            main()

        self.assertEqual(started_with, [{"handler": handler}])
        self.assertNotIn("irodori_openai_tts.app", sys.modules)


class AsyncBridgeTests(unittest.TestCase):
    def test_runs_speech_on_a_dedicated_persistent_loop(self) -> None:
        async def identify_loop(request: str) -> tuple[str, int]:
            return request, id(asyncio.get_running_loop())

        async def invoke_from_runpod_loop() -> tuple[tuple[str, int], tuple[str, int]]:
            return (
                run_speech(identify_loop, "first"),
                run_speech(identify_loop, "second"),
            )

        first, second = asyncio.run(invoke_from_runpod_loop())

        self.assertEqual(first[0], "first")
        self.assertEqual(second[0], "second")
        self.assertEqual(first[1], second[1])


if __name__ == "__main__":
    unittest.main()
