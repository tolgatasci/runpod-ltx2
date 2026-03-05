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
├── api/
│   ├── handler.py
│   └── worker_entry.py
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
LTX2_MODEL_SOURCE=hf://Lightricks/LTX-2/ltx-2-19b-distilled-fp8.safetensors
GEMMA_TEXT_ENCODER_SOURCE=hf://Comfy-Org/ltx-2/split_files/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors
SPATIAL_UPSCALER_SOURCE=hf://Lightricks/LTX-2/ltx-2-spatial-upscaler-x2-1.0.safetensors
TEMPORAL_UPSCALER_SOURCE=hf://Lightricks/LTX-2/ltx-2-temporal-upscaler-x2-1.0.safetensors
IC_LORA_UNION_SOURCE=hf://Lightricks/LTX-2-19b-IC-LoRA-Union-Control/ltx-2-19b-ic-lora-union-control-ref0.5.safetensors
CAMERA_MOTION_LORA_SOURCE=hf://Lightricks/LTX-2-19b-LoRA-Camera-Control-Static/ltx-2-19b-lora-camera-control-static.safetensors
```

Varsayilanlar otomatik gelir:

- `PERSISTENT_ROOT=/runpod-volume`
- `PERSIST_MODELS=true`
- `PERSIST_HF_CACHE=true`
- `PERSIST_INPUT=false`
- `PERSIST_OUTPUT=false`
- `PERSIST_WORKFLOWS=false`
- `MODELS_AUTO_DOWNLOAD=true`
- `DOWNLOAD_ONCE=true`
- `REQUIRE_ALL_MODELS=false`
- `HF_HUB_ENABLE_HF_TRANSFER=1`
- `CLEANUP_JOB_INPUTS=true`
- `CLEANUP_JOB_OUTPUTS=true`

3. Build + run:

```bash
docker compose up --build
```

4. Arayuz:

- `http://localhost:8188`

## RunPod deploy

Onerilen ayarlar:

- Image: `ghcr.io/tolgatasci/runpod-ltx2:latest`
- GPU: `A100 80GB` veya `H100`
- Disk: `150GB`
- Exposed Port: `8188`
- Network Volume mount path: varsayilan `/runpod-volume` (farkliysa `PERSISTENT_ROOT` ile degistir)

RunPod `Environment Variables` alaninda sadece model kaynaklarini girmen yeterli:

```bash
LTX2_MODEL_SOURCE=hf://Lightricks/LTX-2/ltx-2-19b-distilled-fp8.safetensors
GEMMA_TEXT_ENCODER_SOURCE=hf://Comfy-Org/ltx-2/split_files/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors
SPATIAL_UPSCALER_SOURCE=hf://Lightricks/LTX-2/ltx-2-spatial-upscaler-x2-1.0.safetensors
TEMPORAL_UPSCALER_SOURCE=hf://Lightricks/LTX-2/ltx-2-temporal-upscaler-x2-1.0.safetensors
IC_LORA_UNION_SOURCE=hf://Lightricks/LTX-2-19b-IC-LoRA-Union-Control/ltx-2-19b-ic-lora-union-control-ref0.5.safetensors
CAMERA_MOTION_LORA_SOURCE=hf://Lightricks/LTX-2-19b-LoRA-Camera-Control-Static/ltx-2-19b-lora-camera-control-static.safetensors
```

Container ilk acilista model kaynaklari tanimliysa model bootstrap scripti indirir. Sonraki acilislarda model dosyalari ve marker (`.ltx2_models_ready`) network volume icinde kaldigi icin tekrar indirme yapmaz.

Default davranis: network volume'da sadece modeller ve HF cache kalici tutulur. `input/output/workflow` klasorleri runtime storage'da acilir ve otomatik prune/cleanup ile temizlenir.

## GitHub Build (GHCR)

Repo icinde otomatik Docker build workflow'u var:

- `.github/workflows/docker-image.yml`

Tetikleme:

- `main` branch'e push
- `v*` tag push
- manuel (`workflow_dispatch`)

Olusan image tag'leri:

- `ghcr.io/tolgatasci/runpod-ltx2:latest` (default branch)
- `ghcr.io/tolgatasci/runpod-ltx2:main`
- `ghcr.io/tolgatasci/runpod-ltx2:sha-<commit>`

RunPod'da direkt bu image'i kullanabilirsin. Eger GHCR package private ise package visibility'yi `public` yapman veya RunPod'a pull auth vermen gerekir.

## Yatay / dikey cikis

- Yatay: `1920x1080`, `24 fps`
- Dikey: `1080x1920`, `24 fps`

Not: LTX-2 tarafinda width/height degerleri 32'ye bolunebilir tutulmali.

## Kalite presetleri

- Iteration pass: distilled fp8, 8 steps, 1280x720, 97 frames
- Final pass: full fp8, 24 steps, 1920x1080, 161 frames
- Upscale: spatial x2 + temporal x2

## API (opsiyonel)

Repo icinde serverless worker hazir:

- `api/handler.py`
- `api/worker_entry.py`

Serverless mod acmak icin env:

```bash
RUNPOD_SERVERLESS=true
```

Bu modda worker request uzerinden kalite ayarlarini degistirebilirsin:

- `ping=true` (workflow calistirmadan health-check)
- `duration_seconds` (otomatik `frames` hesaplar)
- `fps`
- `steps`
- `seed`
- `width`, `height`
- `cfg`, `denoise`
- `positive_prompt`, `negative_prompt`
- `node_overrides` (node bazli net kontrol)
- `input_image_base64` veya `input_image_url` (runtime'da otomatik input dosyasina cevrilir)

Ornek RunPod request payload:

```json
{
  "input": {
    "prompt": {
      "3": {
        "class_type": "KSampler",
        "inputs": {
          "steps": 16,
          "cfg": 3.5,
          "seed": 12345
        }
      }
    },
    "input_image_base64": "data:image/png;base64,iVBORw0KGgoAAA...",
    "duration_seconds": 6.5,
    "fps": 24,
    "steps": 28,
    "seed": 987654321,
    "width": 1920,
    "height": 1080,
    "wait": true,
    "cleanup_outputs": true,
    "cleanup_inputs": true
  }
}
```

Not: Worker artik UI workflow (`nodes`) geldiğinde default olarak API prompt'a otomatik cevirir (`auto_convert_ui=true` varsayilan).

- Dilersen bu davranisi kapatabilirsin: `auto_convert_ui=false`
- Hala API graph vermek istersen `prompt` veya `workflow_api` kullanabilirsin (ornek: `workflow_api=image_to_video.api.json`).
- ComfyUI `/prompt` 400 donerse hata detayi artik response icinde gorunur (node_errors dahil).

Ek notlar:
- `wait=true` iken job bitince output dosyalari default olarak silinir (`CLEANUP_JOB_OUTPUTS=true`).
- `preserve_outputs=true` gonderirsen o request icin silme kapatilir.
- `return_output_base64=true` ile uygun boyuttaki output dosyalari response icinde base64 donulebilir (`MAX_INLINE_OUTPUT_MB` limiti ile).
