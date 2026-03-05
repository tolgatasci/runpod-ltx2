#!/usr/bin/env bash
set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/ComfyUI}"
LTX2_HOME="${LTX2_HOME:-/opt/ltx2}"
WORKFLOW_DST="${COMFYUI_DIR}/user/default/workflows"

PERSISTENT_ROOT="${PERSISTENT_ROOT:-/runpod-volume}"
PERSIST_MODELS="${PERSIST_MODELS:-true}"
PERSIST_INPUT="${PERSIST_INPUT:-false}"
PERSIST_OUTPUT="${PERSIST_OUTPUT:-false}"
PERSIST_WORKFLOWS="${PERSIST_WORKFLOWS:-false}"
PERSIST_HF_CACHE="${PERSIST_HF_CACHE:-true}"

PERSIST_MODELS_SUBDIR="${PERSIST_MODELS_SUBDIR:-models}"
PERSIST_INPUT_SUBDIR="${PERSIST_INPUT_SUBDIR:-input}"
PERSIST_OUTPUT_SUBDIR="${PERSIST_OUTPUT_SUBDIR:-output}"
PERSIST_WORKFLOWS_SUBDIR="${PERSIST_WORKFLOWS_SUBDIR:-workflows}"
PERSIST_HF_SUBDIR="${PERSIST_HF_SUBDIR:-hf-cache}"

RUNTIME_ROOT="${RUNTIME_ROOT:-/tmp/ltx2-runtime}"
RUNTIME_MODELS_SUBDIR="${RUNTIME_MODELS_SUBDIR:-models}"
RUNTIME_INPUT_SUBDIR="${RUNTIME_INPUT_SUBDIR:-input}"
RUNTIME_OUTPUT_SUBDIR="${RUNTIME_OUTPUT_SUBDIR:-output}"
RUNTIME_WORKFLOWS_SUBDIR="${RUNTIME_WORKFLOWS_SUBDIR:-workflows}"
RUNTIME_TEMP_SUBDIR="${RUNTIME_TEMP_SUBDIR:-temp}"
RUNTIME_HF_SUBDIR="${RUNTIME_HF_SUBDIR:-hf-cache}"

RUNTIME_PRUNE_ENABLED="${RUNTIME_PRUNE_ENABLED:-true}"
PRUNE_INTERVAL_SECONDS="${PRUNE_INTERVAL_SECONDS:-300}"
INPUT_RETENTION_SECONDS="${INPUT_RETENTION_SECONDS:-900}"
OUTPUT_RETENTION_SECONDS="${OUTPUT_RETENTION_SECONDS:-900}"
TEMP_RETENTION_SECONDS="${TEMP_RETENTION_SECONDS:-900}"

is_true() {
  case "${1,,}" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

resolve_persistent_root() {
  local requested="$1"
  local candidate=""

  if [ "${requested}" != "auto" ] && [ -n "${requested}" ]; then
    mkdir -p "${requested}" 2>/dev/null || true
    if [ -d "${requested}" ] && [ -w "${requested}" ]; then
      echo "${requested}"
      return 0
    fi
  fi

  for candidate in /runpod-volume /workspace; do
    if [ -d "${candidate}" ] && [ -w "${candidate}" ]; then
      echo "${candidate}"
      return 0
    fi
  done

  echo "/runpod-volume"
}

link_dir() {
  local target="$1"
  local source="$2"
  local current=""

  mkdir -p "$(dirname "${target}")" "${source}"

  if [ -L "${target}" ]; then
    current="$(readlink "${target}" || true)"
    if [ "${current}" = "${source}" ]; then
      return 0
    fi
    rm -f "${target}"
    ln -s "${source}" "${target}"
    return 0
  fi

  if [ -d "${target}" ]; then
    cp -an "${target}/." "${source}/" 2>/dev/null || true
    rm -rf "${target}"
  elif [ -e "${target}" ]; then
    rm -f "${target}"
  fi

  ln -s "${source}" "${target}"
}

choose_dir() {
  local persist_flag="$1"
  local persist_path="$2"
  local runtime_path="$3"

  if [ "${PERSIST_READY}" = "true" ] && is_true "${persist_flag}"; then
    echo "${persist_path}"
  else
    echo "${runtime_path}"
  fi
}

prune_dir() {
  local dir="$1"
  local retention_seconds="$2"
  local retention_minutes=""

  if [ ! -d "${dir}" ]; then
    return 0
  fi

  if ! [[ "${retention_seconds}" =~ ^[0-9]+$ ]]; then
    return 0
  fi

  if [ "${retention_seconds}" -le 0 ]; then
    return 0
  fi

  retention_minutes=$(( (retention_seconds + 59) / 60 ))
  find "${dir}" -type f -mmin +"${retention_minutes}" -delete 2>/dev/null || true
  find "${dir}" -type d -mindepth 1 -empty -delete 2>/dev/null || true
}

start_runtime_pruner() {
  if ! is_true "${RUNTIME_PRUNE_ENABLED}"; then
    return 0
  fi

  if ! [[ "${PRUNE_INTERVAL_SECONDS}" =~ ^[0-9]+$ ]] || [ "${PRUNE_INTERVAL_SECONDS}" -lt 30 ]; then
    PRUNE_INTERVAL_SECONDS=300
  fi

  (
    while true; do
      prune_dir "${COMFYUI_INPUT_DIR}" "${INPUT_RETENTION_SECONDS}"
      prune_dir "${COMFYUI_OUTPUT_DIR}" "${OUTPUT_RETENTION_SECONDS}"
      prune_dir "${COMFYUI_TEMP_DIR}" "${TEMP_RETENTION_SECONDS}"
      sleep "${PRUNE_INTERVAL_SECONDS}"
    done
  ) &

  echo "[entrypoint] runtime pruner enabled (interval=${PRUNE_INTERVAL_SECONDS}s)."
}

echo "[entrypoint] preparing ComfyUI folders..."
PERSISTENT_ROOT="$(resolve_persistent_root "${PERSISTENT_ROOT}")"
mkdir -p "${COMFYUI_DIR}" "${WORKFLOW_DST}" "${RUNTIME_ROOT}"
mkdir -p "${PERSISTENT_ROOT}" 2>/dev/null || true

PERSIST_READY="false"
if [ -d "${PERSISTENT_ROOT}" ] && [ -w "${PERSISTENT_ROOT}" ]; then
  PERSIST_READY="true"
  echo "[entrypoint] persistent root is writable: ${PERSISTENT_ROOT}"
else
  echo "[entrypoint] warning: PERSISTENT_ROOT='${PERSISTENT_ROOT}' not writable. Using runtime storage only."
fi

MODELS_DIR="$(choose_dir "${PERSIST_MODELS}" "${PERSISTENT_ROOT}/${PERSIST_MODELS_SUBDIR}" "${RUNTIME_ROOT}/${RUNTIME_MODELS_SUBDIR}")"
INPUT_DIR="$(choose_dir "${PERSIST_INPUT}" "${PERSISTENT_ROOT}/${PERSIST_INPUT_SUBDIR}" "${RUNTIME_ROOT}/${RUNTIME_INPUT_SUBDIR}")"
OUTPUT_DIR="$(choose_dir "${PERSIST_OUTPUT}" "${PERSISTENT_ROOT}/${PERSIST_OUTPUT_SUBDIR}" "${RUNTIME_ROOT}/${RUNTIME_OUTPUT_SUBDIR}")"
WORKFLOWS_DIR="$(choose_dir "${PERSIST_WORKFLOWS}" "${PERSISTENT_ROOT}/${PERSIST_WORKFLOWS_SUBDIR}" "${RUNTIME_ROOT}/${RUNTIME_WORKFLOWS_SUBDIR}")"
HF_CACHE_DIR="$(choose_dir "${PERSIST_HF_CACHE}" "${PERSISTENT_ROOT}/${PERSIST_HF_SUBDIR}" "${RUNTIME_ROOT}/${RUNTIME_HF_SUBDIR}")"
TEMP_DIR="${RUNTIME_ROOT}/${RUNTIME_TEMP_SUBDIR}"

link_dir "${COMFYUI_DIR}/models" "${MODELS_DIR}"
link_dir "${COMFYUI_DIR}/input" "${INPUT_DIR}"
link_dir "${COMFYUI_DIR}/output" "${OUTPUT_DIR}"
link_dir "${COMFYUI_DIR}/temp" "${TEMP_DIR}"
link_dir "${WORKFLOW_DST}" "${WORKFLOWS_DIR}"

export COMFYUI_MODELS_DIR="${MODELS_DIR}"
export COMFYUI_INPUT_DIR="${INPUT_DIR}"
export COMFYUI_OUTPUT_DIR="${OUTPUT_DIR}"
export COMFYUI_TEMP_DIR="${TEMP_DIR}"
export COMFYUI_WORKFLOWS_DIR="${WORKFLOWS_DIR}"
export HF_HOME="${HF_HOME:-${HF_CACHE_DIR}}"
mkdir -p "${HF_HOME}"

ensure_placeholder_video() {
  local placeholder="${COMFYUI_INPUT_DIR}/LTX-2_V2V_00014-audio.mp4"
  if [ -f "${placeholder}" ]; then
    return 0
  fi

  echo "[entrypoint] creating placeholder video input: $(basename "${placeholder}")"
  ffmpeg -hide_banner -loglevel error \
    -f lavfi -i color=c=black:s=64x64:d=1 \
    -f lavfi -i anullsrc=r=44100:cl=mono \
    -shortest \
    -c:v libx264 -pix_fmt yuv420p \
    -c:a aac -b:a 64k \
    "${placeholder}" || true
}

ensure_placeholder_video

if [ -d "${LTX2_HOME}/workflows" ] && compgen -G "${LTX2_HOME}/workflows/*.json" > /dev/null; then
  cp -n "${LTX2_HOME}"/workflows/*.json "${COMFYUI_WORKFLOWS_DIR}/" 2>/dev/null || true
fi

if [ "${MODELS_AUTO_DOWNLOAD:-true}" = "true" ]; then
  echo "[entrypoint] model auto-download is enabled."
  "${LTX2_HOME}/scripts/download_models.sh"
else
  echo "[entrypoint] MODELS_AUTO_DOWNLOAD=false, skipping model bootstrap."
fi

start_runtime_pruner

COMFY_ARGS=(
  --listen "${COMFYUI_LISTEN:-0.0.0.0}"
  --port "${COMFYUI_PORT:-8188}"
  --highvram
)

start_comfyui_background() {
  cd "${COMFYUI_DIR}"
  python3 main.py "${COMFY_ARGS[@]}" &
  COMFYUI_PID=$!
  echo "[entrypoint] ComfyUI started in background (pid=${COMFYUI_PID})"
}

wait_for_comfyui() {
  local health_url="http://127.0.0.1:${COMFYUI_PORT:-8188}/"
  local retries="${COMFYUI_HEALTH_RETRIES:-120}"
  local sleep_s="${COMFYUI_HEALTH_SLEEP_SECONDS:-2}"
  local i

  for ((i=1; i<=retries; i++)); do
    if curl -fsS "${health_url}" >/dev/null 2>&1; then
      echo "[entrypoint] ComfyUI is ready."
      return 0
    fi
    sleep "${sleep_s}"
  done

  echo "[entrypoint] ComfyUI did not become healthy in time." >&2
  return 1
}

if [ "${RUNPOD_SERVERLESS:-false}" = "true" ]; then
  echo "[entrypoint] RUNPOD_SERVERLESS=true, starting worker mode."
  start_comfyui_background
  wait_for_comfyui
  cd "${LTX2_HOME}"
  exec python3 -m api.worker_entry
fi

echo "[entrypoint] starting ComfyUI on ${COMFYUI_LISTEN:-0.0.0.0}:${COMFYUI_PORT:-8188}"
cd "${COMFYUI_DIR}"
exec python3 main.py "${COMFY_ARGS[@]}"
