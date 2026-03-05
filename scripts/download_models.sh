#!/usr/bin/env bash
set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/ComfyUI}"
MODEL_ROOT="${COMFYUI_MODELS_DIR:-${COMFYUI_DIR}/models}"
MARKER_FILE="${MODEL_ROOT}/.ltx2_models_ready"
DOWNLOAD_ONCE="${DOWNLOAD_ONCE:-true}"
REQUIRE_ALL_MODELS="${REQUIRE_ALL_MODELS:-false}"
WGET_TRIES="${WGET_TRIES:-20}"
WGET_TIMEOUT="${WGET_TIMEOUT:-30}"

if [ "${DOWNLOAD_ONCE}" = "true" ] && [ -f "${MARKER_FILE}" ]; then
  echo "[models] marker file exists, skipping download."
  exit 0
fi

mkdir -p "${MODEL_ROOT}"/{checkpoints,text_encoders,upscale_models,loras,controlnet}

fetch_http() {
  local source="$1"
  local destination="$2"
  local part_file="${destination}.part"
  local wget_args=(
    --continue
    --tries="${WGET_TRIES}"
    --timeout="${WGET_TIMEOUT}"
    --retry-connrefused
    -O "${part_file}"
  )

  if [[ "${source}" == *"huggingface.co"* ]] && [ -n "${HF_TOKEN:-}" ]; then
    wget --header="Authorization: Bearer ${HF_TOKEN}" "${wget_args[@]}" "${source}"
  else
    wget "${wget_args[@]}" "${source}"
  fi

  mv "${part_file}" "${destination}"
}

fetch_hf() {
  local source="$1"
  local destination="$2"

  local ref="${source#hf://}"
  local repo file
  repo="$(echo "${ref}" | cut -d'/' -f1-2)"
  file="$(echo "${ref}" | cut -d'/' -f3-)"

  if [ -z "${repo}" ] || [ -z "${file}" ] || [ "${file}" = "${ref}" ]; then
    echo "[models] invalid hf:// format: ${source}" >&2
    return 1
  fi

  python3 - "${repo}" "${file}" "$(dirname "${destination}")" "$(basename "${destination}")" <<'PY'
import os
import shutil
import sys
from huggingface_hub import hf_hub_download

repo_id, filename, out_dir, out_name = sys.argv[1:5]
token = os.environ.get("HF_TOKEN")

local_path = hf_hub_download(repo_id=repo_id, filename=filename, token=token)
os.makedirs(out_dir, exist_ok=True)
shutil.copy2(local_path, os.path.join(out_dir, out_name))
PY
}

fetch_model() {
  local source="$1"
  local destination="$2"

  if [[ "${source}" =~ ^https?:// ]]; then
    fetch_http "${source}" "${destination}"
  elif [[ "${source}" =~ ^hf:// ]]; then
    fetch_hf "${source}" "${destination}"
  elif [ -f "${source}" ]; then
    cp "${source}" "${destination}"
  else
    echo "[models] unsupported source '${source}'" >&2
    return 1
  fi
}

MODEL_LABELS=(
  "LTX-2 19B distilled fp8"
  "Gemma text encoder"
  "Spatial upscaler"
  "Temporal upscaler"
  "IC-LoRA union control"
  "Camera motion LoRA"
)

MODEL_ENV_KEYS=(
  "LTX2_MODEL_SOURCE"
  "GEMMA_TEXT_ENCODER_SOURCE"
  "SPATIAL_UPSCALER_SOURCE"
  "TEMPORAL_UPSCALER_SOURCE"
  "IC_LORA_UNION_SOURCE"
  "CAMERA_MOTION_LORA_SOURCE"
)

MODEL_PATHS=(
  "checkpoints/ltx2_19b_distilled_fp8.safetensors"
  "text_encoders/gemma_text_encoder.safetensors"
  "upscale_models/spatial_upscaler_x2.safetensors"
  "upscale_models/temporal_upscaler_x2.safetensors"
  "controlnet/ic_lora_union.safetensors"
  "loras/camera_motion_lora.safetensors"
)

missing=0
failed=0

for i in "${!MODEL_ENV_KEYS[@]}"; do
  env_key="${MODEL_ENV_KEYS[$i]}"
  model_label="${MODEL_LABELS[$i]}"
  relative_path="${MODEL_PATHS[$i]}"
  destination="${MODEL_ROOT}/${relative_path}"
  source="${!env_key:-}"

  mkdir -p "$(dirname "${destination}")"

  if [ -f "${destination}" ]; then
    echo "[models] exists: ${relative_path}"
    continue
  fi

  if [ -z "${source}" ]; then
    echo "[models] missing source for ${model_label}. Set ${env_key}."
    missing=$((missing + 1))
    continue
  fi

  echo "[models] downloading ${model_label} -> ${relative_path}"
  if ! fetch_model "${source}" "${destination}"; then
    echo "[models] failed to download ${model_label}" >&2
    rm -f "${destination}"
    failed=$((failed + 1))
  fi
done

if [ "${failed}" -gt 0 ] && [ "${REQUIRE_ALL_MODELS}" = "true" ]; then
  echo "[models] one or more model downloads failed and REQUIRE_ALL_MODELS=true." >&2
  exit 1
fi

if [ "${missing}" -gt 0 ] && [ "${REQUIRE_ALL_MODELS}" = "true" ]; then
  echo "[models] missing model sources and REQUIRE_ALL_MODELS=true." >&2
  exit 1
fi

if [ "${missing}" -eq 0 ] && [ "${failed}" -eq 0 ] && [ "${DOWNLOAD_ONCE}" = "true" ]; then
  touch "${MARKER_FILE}"
  echo "[models] all configured models are ready."
else
  echo "[models] completed with missing=${missing}, failed=${failed}."
fi
