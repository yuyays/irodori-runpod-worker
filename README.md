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
    "num_steps": 40,
    "seed": 200,
    "cfg_scale_speaker": 5.0,
    "speaker_kv_scale": 1.2,
    "chunking_enabled": false
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

The adapter exposes bounded inference controls for controlled quality
experiments:

- `num_steps`: integer from 1 to 40; defaults to `10`
- `seed`: optional integer from 0 to 4294967295; omitted uses a random seed
- `cfg_scale_speaker`: number from 0 to 20; defaults to `5.0`
- `speaker_kv_scale`: optional number from 0.5 to 2.0
- `chunking_enabled`: boolean; defaults to `false`

Text is limited to 500 characters, decoded reference audio to 5 MiB, generated
WAV audio to 7 MiB, and generated duration to 30 seconds so requests and
responses remain below RunPod's payload limits.

For a v3 baseline, keep the reference audio and target text fixed, use the same
seed, and compare `num_steps` values `10`, `20`, and `40`. Repeat the matrix with
multiple seeds before drawing quality conclusions. Test chunking separately
because it changes text segmentation rather than only sampling quality.

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
