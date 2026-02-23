# LTX-2 RunPod Serverless

[Lightricks LTX-2](https://huggingface.co/Lightricks/LTX-2) (19B) video generation model on RunPod Serverless.

**Supports:** Text-to-Video (T2V) + Image-to-Video (I2V) + FP8 quantization + Distilled (8-step) mode

## Quick Start

### 1. Build & Push Docker Image

```bash
docker build -t your-dockerhub/ltx2-runpod:latest .
docker push your-dockerhub/ltx2-runpod:latest
```

### 2. Create RunPod Serverless Endpoint

- **Docker Image:** `your-dockerhub/ltx2-runpod:latest`
- **GPU:** A100 80GB (recommended) or L40S 48GB (FP8)
- **Container Disk:** 100GB+
- **Volume:** Not needed (models baked into image)

### 3. Test

```bash
export RUNPOD_API_KEY="your_key"
export RUNPOD_LTX2_ENDPOINT_ID="your_endpoint_id"
python test_local.py              # Text-to-Video
python test_local.py distilled    # Fast mode (8 steps)
python test_local.py i2v image.jpg  # Image-to-Video
```

## API Reference

### Input Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | str | **required** | Text description |
| `negative_prompt` | str | "" | What to avoid |
| `mode` | str | "t2v" | "t2v" or "i2v" |
| `pipeline_type` | str | env | "two_stage" or "distilled" |
| `width` | int | 768 | Must be divisible by 32 |
| `height` | int | 512 | Must be divisible by 32 |
| `num_frames` | int | 121 | Must be (8n+1): 9,17,25,...,121 |
| `frame_rate` | float | 25.0 | FPS |
| `num_inference_steps` | int | 40/8 | 40 for two_stage, 8 for distilled |
| `seed` | int | None | Random seed |
| `cfg_scale` | float | 3.0 | Text adherence (1.0-5.0) |
| `stg_scale` | float | 1.0 | Temporal coherence (0.5-1.5) |
| `rescale_scale` | float | 0.7 | Variance matching (0.5-0.7) |
| `image_base64` | str | - | First frame for I2V (base64) |
| `image_end_base64` | str | - | Last frame for I2V (base64) |
| `image_strength` | float | 1.0 | Image conditioning strength |

### Output

| Field | Type | Description |
|-------|------|-------------|
| `video_base64` | str | MP4 video as base64 |
| `duration_s` | float | Video duration |
| `resolution` | str | "WxH" |
| `num_frames` | int | Frame count |
| `frame_rate` | float | FPS |
| `inference_time_s` | float | Generation time |
| `seed` | int | Used seed |
| `file_size_mb` | float | Output file size |

### Example: Text-to-Video

```python
import requests, base64

resp = requests.post(
    f"https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync",
    json={"input": {
        "prompt": "A cinematic shot of ancient ruins at sunset, slow pan",
        "width": 768, "height": 512,
        "num_frames": 81,  # ~3.2s at 25fps
        "seed": 42
    }},
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=300
)
output = resp.json()["output"]
with open("video.mp4", "wb") as f:
    f.write(base64.b64decode(output["video_base64"]))
```

### Example: Image-to-Video

```python
with open("input.jpg", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

resp = requests.post(
    f"https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync",
    json={"input": {
        "prompt": "The scene slowly comes to life, gentle camera movement",
        "mode": "i2v",
        "image_base64": img_b64,
        "num_frames": 81,
        "seed": 42
    }},
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=300
)
```

## Frame Count Guide

| Frames | Duration @25fps | Use Case |
|--------|-----------------|----------|
| 25 | 1.0s | Quick motion |
| 41 | 1.6s | Short clip |
| 81 | 3.2s | Standard |
| 121 | 4.8s | Long scene |
| 161 | 6.4s | Extended |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODELS_DIR` | /models | Model files location |
| `LTX2_PIPELINE` | two_stage | Default pipeline type |
| `LTX2_FP8` | true | Enable FP8 quantization |
| `LTX2_LORA_STRENGTH` | 0.8 | Distilled LoRA strength |

## Model Files (auto-downloaded in Docker build)

| File | Size | Purpose |
|------|------|---------|
| `ltx-2-19b-dev-fp8.safetensors` | 27.1 GB | Main model (FP8) |
| `ltx-2-19b-distilled-fp8.safetensors` | 27.1 GB | Distilled model |
| `ltx-2-19b-distilled-lora-384.safetensors` | 7.7 GB | LoRA for two-stage |
| `ltx-2-spatial-upscaler-x2-1.0.safetensors` | 1.0 GB | 2x resolution upscaler |
| `text_encoder/` (Gemma 3) | ~5 GB | Text understanding |
| `vae/`, `audio_vae/`, `vocoder/` | ~2 GB | Video/Audio encoding |

**Total image size: ~80-90 GB**

## VRAM Usage

| Config | VRAM | Speed |
|--------|------|-------|
| Two-stage FP8 (40 steps) | ~40-50 GB | ~120s for 121 frames |
| Distilled FP8 (8 steps) | ~30-40 GB | ~30s for 121 frames |
