# ltx2-runpod-docker

Production odakli LTX-2 + ComfyUI + RunPod pipeline reposu.

## Mimari

```text
RunPod GPU
  -> Docker Container
  -> ComfyUI
  -> LTX-2 Video Model
  -> IC-LoRA Controls
  -> Reference Image
  -> Upscale Pass (Spatial + Temporal)
  -> Final Video
```

## Pipeline

```text
Image -> Conditioning
  -> IC-LoRA (depth / pose / canny)
  -> LTX-2 generation
  -> Spatial upscaler
  -> Temporal upscaler
  -> Frame interpolation
  -> Final video
```

## Repo yapisi

```text
ltx2-runpod-docker/
├── Dockerfile
├── start.sh
├── requirements.txt
├── workflows/
│   ├── image_to_video.json
│   └── cinematic_i2v.json
├── scripts/
│   └── download_models.sh
├── docker-compose.yml
└── README.md
```

`workflows/` altindaki dosyalar, `ComfyUI-LTXVideo` reposundaki resmi ornek graph'larin bu yapidaki adlarla kopyalanmis halidir.

## Hızlı başlangıç (local GPU)

1. `.env` olustur:

```bash
cp .env.example .env
```

2. Ortam degiskenlerini doldur:

```bash
HF_TOKEN=hf_xxx
LTX2_MODEL_SOURCE=hf://org-or-user/repo/path/to/ltx2_model.safetensors
GEMMA_TEXT_ENCODER_SOURCE=hf://org-or-user/repo/path/to/gemma_encoder.safetensors
SPATIAL_UPSCALER_SOURCE=hf://org-or-user/repo/path/to/spatial_upscaler.safetensors
TEMPORAL_UPSCALER_SOURCE=hf://org-or-user/repo/path/to/temporal_upscaler.safetensors
IC_LORA_UNION_SOURCE=hf://org-or-user/repo/path/to/ic_lora_union.safetensors
CAMERA_MOTION_LORA_SOURCE=hf://org-or-user/repo/path/to/camera_motion_lora.safetensors
```

Varsayilanlar otomatik gelir:

- `PERSISTENT_ROOT=/runpod-volume`
- `MODELS_AUTO_DOWNLOAD=true`
- `DOWNLOAD_ONCE=true`
- `REQUIRE_ALL_MODELS=false`
- `HF_HUB_ENABLE_HF_TRANSFER=1`

3. Build + run:

```bash
docker compose up --build
```

4. Arayuz:

- `http://localhost:8188`

## RunPod deploy

Onerilen ayarlar:

- Image: `ghcr.io/YOUR_GITHUB/ltx2-runpod:latest`
- GPU: `A100 80GB` veya `H100`
- Disk: `150GB`
- Exposed Port: `8188`
- Network Volume mount path: varsayilan `/runpod-volume` (farkliysa `PERSISTENT_ROOT` ile degistir)

RunPod `Environment Variables` alaninda sadece model kaynaklarini girmen yeterli:

```bash
LTX2_MODEL_SOURCE=...
GEMMA_TEXT_ENCODER_SOURCE=...
SPATIAL_UPSCALER_SOURCE=...
TEMPORAL_UPSCALER_SOURCE=...
IC_LORA_UNION_SOURCE=...
CAMERA_MOTION_LORA_SOURCE=...
```

Container ilk acilista model kaynaklari tanimliysa model bootstrap scripti indirir. Sonraki acilislarda model dosyalari ve marker (`.ltx2_models_ready`) network volume icinde kaldigi icin tekrar indirme yapmaz.

Ilk kurulumdan sonra en hizli acilis icin opsiyonel olarak `MODELS_AUTO_DOWNLOAD=false` yapabilirsin.

## Yatay / dikey cikis

- Yatay: `1920x1080`, `24 fps`
- Dikey: `1080x1920`, `24 fps`

Not: LTX-2 tarafinda width/height degerleri 32'ye bolunebilir tutulmali.

## Kalite presetleri

- Iteration pass: distilled fp8, 8 steps, 1280x720, 97 frames
- Final pass: full fp8, 24 steps, 1920x1080, 161 frames
- Upscale: spatial x2 + temporal x2

## API (opsiyonel)

`requirements.txt` icinde `runpod` paketi ekli. Sonraki adimda serverless worker endpoint (`text-to-video`, `image-to-video`, `seed`, `fps`, `duration`) eklenebilir.
