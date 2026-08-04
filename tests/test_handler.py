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
        result = parse_job(
            valid_job(
                seed=200,
                cfg_scale_speaker=6.0,
                speaker_kv_scale=1.2,
                chunking_enabled=True,
            )
        )

        self.assertEqual(result.text, "これはテストです。")
        self.assertEqual(result.reference_audio, b"RIFF-audio")
        self.assertEqual(result.reference_suffix, ".wav")
        self.assertEqual(result.num_steps, 10)
        self.assertEqual(result.seed, 200)
        self.assertEqual(result.cfg_scale_speaker, 6.0)
        self.assertEqual(result.speaker_kv_scale, 1.2)
        self.assertTrue(result.chunking_enabled)

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

    def test_uses_safe_quality_control_defaults(self) -> None:
        result = parse_job(valid_job())

        self.assertIsNone(result.seed)
        self.assertEqual(result.cfg_scale_speaker, 5.0)
        self.assertIsNone(result.speaker_kv_scale)
        self.assertFalse(result.chunking_enabled)

    def test_rejects_invalid_quality_controls(self) -> None:
        cases = (
            ({"seed": -1}, "seed must be between"),
            ({"cfg_scale_speaker": 21}, "cfg_scale_speaker must be between"),
            ({"cfg_scale_speaker": 10**400}, "cfg_scale_speaker must be between"),
            ({"speaker_kv_scale": 2.1}, "speaker_kv_scale must be between"),
            ({"speaker_kv_scale": 10**400}, "speaker_kv_scale must be between"),
            ({"chunking_enabled": "true"}, "chunking_enabled must be a boolean"),
        )

        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    parse_job(valid_job(**overrides))


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


class HandlerContractTests(unittest.TestCase):
    def test_forwards_quality_controls_to_irodori(self) -> None:
        registry = FakeRegistry()
        captured_requests: list[object] = []

        class FakeOptions:
            def __init__(self, **values: object) -> None:
                self.__dict__.update(values)

        class FakeSpeechRequest:
            def __init__(self, **values: object) -> None:
                self.__dict__.update(values)
                captured_requests.append(self)

        fake_app = types.ModuleType("irodori_openai_tts.app")
        fake_app.IrodoriOptions = FakeOptions
        fake_app.SpeechRequest = FakeSpeechRequest
        fake_app.create_speech = object()
        fake_app.voice_registry = registry
        response = types.SimpleNamespace(
            body=b"RIFF-output",
            headers={"x-irodori-seed": "200"},
        )

        with (
            patch.dict(sys.modules, {"irodori_openai_tts.app": fake_app}),
            patch("handler.run_speech", return_value=response),
        ):
            result = handler(
                valid_job(
                    num_steps=40,
                    seed=200,
                    cfg_scale_speaker=6.0,
                    speaker_kv_scale=1.2,
                    chunking_enabled=True,
                )
            )

        options = captured_requests[0].irodori
        self.assertEqual(options.num_steps, 40)
        self.assertEqual(options.seed, 200)
        self.assertEqual(options.cfg_scale_speaker, 6.0)
        self.assertEqual(options.speaker_kv_scale, 1.2)
        self.assertTrue(options.chunking_enabled)
        self.assertEqual(options.max_seconds, 30.0)
        self.assertEqual(result["seed"], "200")


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
