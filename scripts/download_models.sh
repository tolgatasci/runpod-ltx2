#!/usr/bin/env bash
set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/ComfyUI}"
MODEL_ROOT="${COMFYUI_MODELS_DIR:-${COMFYUI_DIR}/models}"
MARKER_FILE="${MODEL_ROOT}/.ltx2_models_ready"
SOURCE_MANIFEST_FILE="${MODEL_ROOT}/.ltx2_model_sources"
DOWNLOAD_ONCE="${DOWNLOAD_ONCE:-true}"
REQUIRE_ALL_MODELS="${REQUIRE_ALL_MODELS:-false}"
FORCE_MODEL_REDOWNLOAD="${FORCE_MODEL_REDOWNLOAD:-false}"
WGET_TRIES="${WGET_TRIES:-20}"
WGET_TIMEOUT="${WGET_TIMEOUT:-30}"
GEMMA_BUNDLE_DIR="${MODEL_ROOT}/text_encoders/gemma-3-12b-it-qat-q4_0-unquantized"
GEMMA_PRIMARY_PATH="${MODEL_ROOT}/text_encoders/gemma_text_encoder.safetensors"
GEMMA_COMPAT_PATH="${GEMMA_BUNDLE_DIR}/model.safetensors"
GEMMA_TOKENIZER_PATH="${GEMMA_BUNDLE_DIR}/tokenizer.model"
GEMMA_PREPROCESSOR_PATH="${GEMMA_BUNDLE_DIR}/preprocessor_config.json"
CHECKPOINT_PATH="${MODEL_ROOT}/checkpoints/ltx-2-19b-distilled.safetensors"
SPATIAL_UPSCALER_PATH="${MODEL_ROOT}/latent_upscale_models/ltx-2-spatial-upscaler-x2-1.0.safetensors"
IC_LORA_PATH="${MODEL_ROOT}/loras/ltx-2-19b-ic-lora-union-ref0.5.safetensors"

mkdir -p "${MODEL_ROOT}"/{checkpoints,text_encoders,tokenizer,upscale_models,latent_upscale_models,loras,controlnet}

ensure_gemma_compat_paths() {
  mkdir -p "${GEMMA_BUNDLE_DIR}"
  if [ -f "${GEMMA_PRIMARY_PATH}" ] && [ ! -e "${GEMMA_COMPAT_PATH}" ]; then
    ln -sf ../gemma_text_encoder.safetensors "${GEMMA_COMPAT_PATH}"
  fi
  if [ -f "${GEMMA_COMPAT_PATH}" ] && [ ! -e "${GEMMA_PRIMARY_PATH}" ]; then
    ln -sf gemma-3-12b-it-qat-q4_0-unquantized/model.safetensors "${GEMMA_PRIMARY_PATH}"
  fi
}

ensure_gemma_compat_paths

FORCE_RECHECK=0
FORCE_GEMMA_REFRESH=0

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
local_path = os.path.realpath(local_path)
os.makedirs(out_dir, exist_ok=True)
dst_path = os.path.join(out_dir, out_name)

def unlink_existing(path: str) -> None:
    # Remove both regular files and dangling symlinks.
    if not os.path.lexists(path):
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)

unlink_existing(dst_path)

try:
    os.link(local_path, dst_path)
except OSError:
    unlink_existing(dst_path)
    # Avoid external symlinks in models/, ComfyUI can ignore them.
    shutil.copy2(local_path, dst_path)
PY
}

fetch_hf_repo() {
  local source="$1"
  local destination_dir="$2"

  local ref="${source#hf://}"
  local org rest repo extra
  org="${ref%%/*}"
  rest="${ref#*/}"

  if [ -z "${org}" ] || [ -z "${rest}" ] || [ "${org}" = "${ref}" ]; then
    echo "[models] invalid hf repo format: ${source}" >&2
    return 1
  fi

  repo="${org}/${rest%%/*}"
  extra=""
  if [ "${rest}" != "${rest%%/*}" ]; then
    extra="${rest#*/}"
  fi

  if [ -n "${extra}" ]; then
    echo "[models] hf repo download expects repository root (hf://org/repo): ${source}" >&2
    return 1
  fi

  python3 - "${repo}" "${destination_dir}" <<'PY'
import os
import sys
from huggingface_hub import snapshot_download

repo_id, out_dir = sys.argv[1:3]
token = os.environ.get("HF_TOKEN")
os.makedirs(out_dir, exist_ok=True)
snapshot_download(
    repo_id=repo_id,
    local_dir=out_dir,
    local_dir_use_symlinks=False,
    token=token,
    resume_download=True,
)
PY
}

fetch_hf_url() {
  local source="$1"
  local destination="$2"

  python3 - "${source}" "$(dirname "${destination}")" "$(basename "${destination}")" <<'PY'
import os
import shutil
import sys
from urllib.parse import urlparse

from huggingface_hub import hf_hub_download

url, out_dir, out_name = sys.argv[1:4]
token = os.environ.get("HF_TOKEN")

parsed = urlparse(url)
if parsed.netloc != "huggingface.co":
    raise ValueError("not_hf_url")

parts = [part for part in parsed.path.split("/") if part]
if len(parts) < 5 or parts[2] != "resolve":
    raise ValueError("unsupported_hf_url_format")

repo_id = f"{parts[0]}/{parts[1]}"
revision = parts[3]
filename = "/".join(parts[4:])
local_path = hf_hub_download(repo_id=repo_id, filename=filename, revision=revision, token=token)
local_path = os.path.realpath(local_path)

os.makedirs(out_dir, exist_ok=True)
dst_path = os.path.join(out_dir, out_name)

if os.path.lexists(dst_path):
    if os.path.isdir(dst_path) and not os.path.islink(dst_path):
        shutil.rmtree(dst_path)
    else:
        os.unlink(dst_path)

try:
    os.link(local_path, dst_path)
except OSError:
    if os.path.lexists(dst_path):
        os.unlink(dst_path)
    shutil.copy2(local_path, dst_path)
PY
}

fetch_model() {
  local source="$1"
  local destination="$2"

  if [[ "${source}" =~ ^https?://huggingface\.co/ ]]; then
    if ! fetch_hf_url "${source}" "${destination}"; then
      echo "[models] falling back to wget for ${source}" >&2
      fetch_http "${source}" "${destination}"
    fi
  elif [[ "${source}" =~ ^https?:// ]]; then
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
  "Gemma tokenizer"
  "Gemma preprocessor config"
  "Spatial upscaler"
  "Temporal upscaler"
  "IC-LoRA union control"
  "Camera motion LoRA"
)

MODEL_ENV_KEYS=(
  "LTX2_MODEL_SOURCE"
  "GEMMA_TEXT_ENCODER_SOURCE"
  "GEMMA_TOKENIZER_SOURCE"
  "GEMMA_PREPROCESSOR_SOURCE"
  "SPATIAL_UPSCALER_SOURCE"
  "TEMPORAL_UPSCALER_SOURCE"
  "IC_LORA_UNION_SOURCE"
  "CAMERA_MOTION_LORA_SOURCE"
)

MODEL_PATHS=(
  "checkpoints/ltx-2-19b-distilled.safetensors"
  "text_encoders/gemma_text_encoder.safetensors"
  "text_encoders/gemma-3-12b-it-qat-q4_0-unquantized/tokenizer.model"
  "text_encoders/gemma-3-12b-it-qat-q4_0-unquantized/preprocessor_config.json"
  "latent_upscale_models/ltx-2-spatial-upscaler-x2-1.0.safetensors"
  "upscale_models/ltx-2-temporal-upscaler-x2-1.0.safetensors"
  "loras/ltx-2-19b-ic-lora-union-ref0.5.safetensors"
  "loras/ltx-2-19b-lora-camera-control-static.safetensors"
)

is_valid_model_file() {
  local path="$1"
  local resolved=""

  if [ -L "${path}" ]; then
    resolved="$(readlink -f "${path}" 2>/dev/null || true)"
    if [ -z "${resolved}" ] || [ ! -f "${resolved}" ]; then
      return 1
    fi
    case "${resolved}" in
      "${MODEL_ROOT}"/*) return 0 ;;
      *) return 1 ;;
    esac
  fi

  [ -f "${path}" ]
}

cleanup_external_model_symlinks() {
  local removed=0
  local symlink=""
  local resolved=""

  if [ ! -d "${MODEL_ROOT}" ]; then
    return 0
  fi

  while IFS= read -r -d '' symlink; do
    resolved="$(readlink -f "${symlink}" 2>/dev/null || true)"
    if [ -z "${resolved}" ] || [ ! -f "${resolved}" ]; then
      rm -f "${symlink}" || true
      removed=$((removed + 1))
      continue
    fi
    case "${resolved}" in
      "${MODEL_ROOT}"/*) ;;
      *)
        rm -f "${symlink}" || true
        removed=$((removed + 1))
        ;;
    esac
  done < <(find "${MODEL_ROOT}" -type l -print0 2>/dev/null)

  if [ "${removed}" -gt 0 ]; then
    echo "[models] removed ${removed} external/broken model symlink(s)."
    rm -f "${MARKER_FILE}" "${SOURCE_MANIFEST_FILE}" || true
  fi
}

write_source_manifest() {
  local manifest_path="$1"
  {
    echo "GEMMA_MODEL_FILENAME=${GEMMA_MODEL_FILENAME:-}"
    for key in "${MODEL_ENV_KEYS[@]}"; do
      echo "${key}=${!key:-}"
    done
  } > "${manifest_path}"
}

source_manifest_matches_current() {
  local tmp_file
  tmp_file="$(mktemp)"
  write_source_manifest "${tmp_file}"
  if cmp -s "${SOURCE_MANIFEST_FILE}" "${tmp_file}"; then
    rm -f "${tmp_file}"
    return 0
  fi
  rm -f "${tmp_file}"
  return 1
}

cleanup_external_model_symlinks

if [ "${FORCE_MODEL_REDOWNLOAD}" = "true" ]; then
  echo "[models] FORCE_MODEL_REDOWNLOAD=true, forcing refresh for all configured models."
  rm -f "${MARKER_FILE}" "${SOURCE_MANIFEST_FILE}" || true
  FORCE_RECHECK=1
fi

if [ "${DOWNLOAD_ONCE}" = "true" ] && [ -f "${MARKER_FILE}" ]; then
  missing_required=0
  for required in \
    "${CHECKPOINT_PATH}" \
    "${GEMMA_PRIMARY_PATH}" \
    "${GEMMA_COMPAT_PATH}" \
    "${GEMMA_TOKENIZER_PATH}" \
    "${GEMMA_PREPROCESSOR_PATH}" \
    "${SPATIAL_UPSCALER_PATH}" \
    "${IC_LORA_PATH}"; do
    if ! is_valid_model_file "${required}"; then
      echo "[models] marker exists but required file is missing: ${required#${MODEL_ROOT}/}"
      missing_required=1
    fi
  done

  if [ "${missing_required}" -eq 1 ]; then
    echo "[models] forcing model recheck."
    rm -f "${MARKER_FILE}"
    FORCE_RECHECK=1
  elif [ -f "${SOURCE_MANIFEST_FILE}" ]; then
    if source_manifest_matches_current; then
      echo "[models] marker file exists, skipping download."
      exit 0
    fi
    echo "[models] model source config changed, refreshing cached models."
    FORCE_RECHECK=1
  else
    # Old volume layout without source manifest: refresh only Gemma once.
    echo "[models] source manifest missing, refreshing Gemma text encoder once."
    FORCE_GEMMA_REFRESH=1
  fi
fi

missing=0
failed=0

for i in "${!MODEL_ENV_KEYS[@]}"; do
  env_key="${MODEL_ENV_KEYS[$i]}"
  model_label="${MODEL_LABELS[$i]}"
  relative_path="${MODEL_PATHS[$i]}"
  destination="${MODEL_ROOT}/${relative_path}"
  source="${!env_key:-}"

  mkdir -p "$(dirname "${destination}")"

  refresh_this_model=0
  if [ "${FORCE_RECHECK}" -eq 1 ]; then
    refresh_this_model=1
  elif [ "${FORCE_GEMMA_REFRESH}" -eq 1 ] && [ "${env_key}" = "GEMMA_TEXT_ENCODER_SOURCE" ]; then
    refresh_this_model=1
  fi

  if [ "${env_key}" = "GEMMA_TEXT_ENCODER_SOURCE" ] && [[ "${source}" =~ ^hf://[^/]+/[^/]+/?$ ]]; then
    if is_valid_model_file "${destination}" && [ "${refresh_this_model}" -eq 0 ]; then
      echo "[models] exists: ${relative_path}"
      continue
    fi
    if [ "${refresh_this_model}" -eq 1 ]; then
      rm -f "${destination}"
    fi
    echo "[models] downloading ${model_label} bundle -> $(dirname "${relative_path}")"
    if ! fetch_hf_repo "${source}" "$(dirname "${destination}")"; then
      echo "[models] failed to download ${model_label} bundle" >&2
      failed=$((failed + 1))
    fi
    continue
  fi

  if is_valid_model_file "${destination}" && [ "${refresh_this_model}" -eq 0 ]; then
    echo "[models] exists: ${relative_path}"
    continue
  fi

  if [ -z "${source}" ]; then
    echo "[models] missing source for ${model_label}. Set ${env_key}."
    missing=$((missing + 1))
    continue
  fi

  if [ -f "${destination}" ] && [ "${refresh_this_model}" -eq 1 ]; then
    rm -f "${destination}"
    echo "[models] refreshing ${model_label} -> ${relative_path}"
  else
    echo "[models] downloading ${model_label} -> ${relative_path}"
  fi
  if ! fetch_model "${source}" "${destination}"; then
    echo "[models] failed to download ${model_label}" >&2
    rm -f "${destination}"
    failed=$((failed + 1))
  fi
done

ensure_gemma_compat_paths

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
  write_source_manifest "${SOURCE_MANIFEST_FILE}"
  echo "[models] all configured models are ready."
else
  echo "[models] completed with missing=${missing}, failed=${failed}."
fi
