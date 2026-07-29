# Irodori RunPod Worker

RunPod Serverless adapter for
[Aratako/Irodori-TTS-Server](https://github.com/Aratako/Irodori-TTS-Server).

The Docker image pins an exact upstream Irodori server commit. Update
`IRODORI_SERVER_REF` in `Dockerfile` deliberately when adopting an upstream
release.

## Request

Submit requests through RunPod's asynchronous `/run` endpoint:

```json
{
  "input": {
    "text": "これはテストです。",
    "reference_audio_base64": "<base64>",
    "reference_filename": "reference.webm",
    "num_steps": 10
  }
}
```

Successful jobs return:

```json
{
  "audio_base64": "<base64 WAV>",
  "content_type": "audio/wav",
  "seed": "1234",
  "size_bytes": 123456
}
```

Reference audio is written only to the worker's temporary filesystem and is
deleted in a `finally` block after every job.

The adapter intentionally exposes only the bounded `num_steps` option. Text is
limited to 500 characters, decoded reference audio to 5 MiB, generated WAV
audio to 7 MiB, and generated duration to 30 seconds so requests and responses
remain below RunPod's payload limits.

## RunPod endpoint settings

After the image is published, configure the endpoint with:

- minimum workers: `0`
- maximum workers: `1`
- GPUs per worker: `1`
- execution timeout: `1200` seconds
- idle timeout: `60` seconds
- FlashBoot: enabled

The first GHCR publication may default to private. In the GitHub package
settings, change `irodori-runpod-worker` visibility to **Public** before
creating the RunPod endpoint.

## Local checks

```bash
python -m unittest discover -s tests -v
docker build -t irodori-runpod-worker .
```
