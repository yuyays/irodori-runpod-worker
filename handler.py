from __future__ import annotations

import asyncio
import base64
import binascii
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_TEXT_CHARS = 500
MAX_REFERENCE_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_BYTES = 7 * 1024 * 1024
# Mirrors VOICE_EXTENSIONS in the pinned Irodori server revision.
ALLOWED_REFERENCE_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}
_SYNTHESIS_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="irodori")
_SYNTHESIS_LOOP: asyncio.AbstractEventLoop | None = None


@dataclass(frozen=True)
class SynthesisInput:
    text: str
    reference_audio: bytes
    reference_suffix: str
    num_steps: int
    seed: int | None = None
    cfg_scale_speaker: float = 5.0
    speaker_kv_scale: float | None = None
    chunking_enabled: bool = False


def parse_job(job: dict[str, Any]) -> SynthesisInput:
    payload = job.get("input")
    if not isinstance(payload, dict):
        raise ValueError("job.input must be an object")

    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("input.text must be a non-empty string")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"input.text must be at most {MAX_TEXT_CHARS} characters")

    encoded_audio = payload.get("reference_audio_base64")
    if not isinstance(encoded_audio, str) or not encoded_audio:
        raise ValueError("input.reference_audio_base64 must be a non-empty base64 string")
    try:
        reference_audio = base64.b64decode(encoded_audio, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("input.reference_audio_base64 is not valid base64") from error

    configured_max_reference_bytes = int(
        os.environ.get("MAX_REFERENCE_AUDIO_BYTES", MAX_REFERENCE_BYTES)
    )
    if configured_max_reference_bytes <= 0:
        raise ValueError("MAX_REFERENCE_AUDIO_BYTES must be greater than zero")
    max_reference_bytes = min(configured_max_reference_bytes, MAX_REFERENCE_BYTES)
    if not reference_audio:
        raise ValueError("reference audio must not be empty")
    if len(reference_audio) > max_reference_bytes:
        raise ValueError(f"reference audio must be at most {max_reference_bytes} bytes")

    filename = payload.get("reference_filename", "reference.wav")
    if not isinstance(filename, str):
        raise ValueError("input.reference_filename must be a string")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_REFERENCE_SUFFIXES:
        raise ValueError("input.reference_filename has an unsupported audio extension")

    num_steps = payload.get("num_steps", 10)
    if isinstance(num_steps, bool) or not isinstance(num_steps, int):
        raise ValueError("input.num_steps must be an integer")
    if not 1 <= num_steps <= 40:
        raise ValueError("input.num_steps must be between 1 and 40")

    seed = payload.get("seed")
    if seed is not None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("input.seed must be an integer")
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError("input.seed must be between 0 and 4294967295")

    cfg_scale_speaker = payload.get("cfg_scale_speaker", 5.0)
    if (
        isinstance(cfg_scale_speaker, bool)
        or not isinstance(cfg_scale_speaker, (int, float))
    ):
        raise ValueError("input.cfg_scale_speaker must be a number")
    if not 0.0 <= cfg_scale_speaker <= 20.0:
        raise ValueError("input.cfg_scale_speaker must be between 0 and 20")
    cfg_scale_speaker = float(cfg_scale_speaker)

    speaker_kv_scale = payload.get("speaker_kv_scale")
    if speaker_kv_scale is not None:
        if (
            isinstance(speaker_kv_scale, bool)
            or not isinstance(speaker_kv_scale, (int, float))
        ):
            raise ValueError("input.speaker_kv_scale must be a number")
        if not 0.5 <= speaker_kv_scale <= 2.0:
            raise ValueError("input.speaker_kv_scale must be between 0.5 and 2")
        speaker_kv_scale = float(speaker_kv_scale)

    chunking_enabled = payload.get("chunking_enabled", False)
    if not isinstance(chunking_enabled, bool):
        raise ValueError("input.chunking_enabled must be a boolean")

    return SynthesisInput(
        text=text,
        reference_audio=reference_audio,
        reference_suffix=suffix,
        num_steps=num_steps,
        seed=seed,
        cfg_scale_speaker=cfg_scale_speaker,
        speaker_kv_scale=speaker_kv_scale,
        chunking_enabled=chunking_enabled,
    )


@contextmanager
def temporary_voice(registry: Any, request: SynthesisInput) -> Iterator[str]:
    voice_id = f"runpod-{uuid.uuid4()}"
    registry.write_file(
        filename=f"reference{request.reference_suffix}",
        data=request.reference_audio,
        voice_id=voice_id,
    )
    try:
        yield voice_id
    finally:
        registry.delete_file(voice_id)


def _run_speech_in_worker(async_speech: Any, speech_request: Any) -> Any:
    global _SYNTHESIS_LOOP
    if _SYNTHESIS_LOOP is None:
        _SYNTHESIS_LOOP = asyncio.new_event_loop()
    return _SYNTHESIS_LOOP.run_until_complete(async_speech(speech_request))


def run_speech(async_speech: Any, speech_request: Any) -> Any:
    return _SYNTHESIS_EXECUTOR.submit(
        _run_speech_in_worker,
        async_speech,
        speech_request,
    ).result()


def handler(job: dict[str, Any]) -> dict[str, Any]:
    request = parse_job(job)

    from irodori_openai_tts.app import (
        IrodoriOptions,
        SpeechRequest,
        create_speech,
        voice_registry,
    )

    with temporary_voice(voice_registry, request) as voice_id:
        speech_request = SpeechRequest(
            model="irodori-tts",
            input=request.text,
            voice=voice_id,
            response_format="wav",
            irodori=IrodoriOptions(
                num_steps=request.num_steps,
                seed=request.seed,
                cfg_scale_speaker=request.cfg_scale_speaker,
                speaker_kv_scale=request.speaker_kv_scale,
                chunking_enabled=request.chunking_enabled,
                max_seconds=30.0,
            ),
        )
        response = run_speech(create_speech, speech_request)
        audio = bytes(response.body)
        if len(audio) > MAX_OUTPUT_BYTES:
            raise ValueError(
                f"generated audio exceeds the {MAX_OUTPUT_BYTES}-byte response limit"
            )
        return {
            "audio_base64": base64.b64encode(audio).decode("ascii"),
            "content_type": "audio/wav",
            "seed": response.headers.get("x-irodori-seed"),
            "size_bytes": len(audio),
        }


def main() -> None:
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
