#!/usr/bin/env bash
set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/ComfyUI}"
LTX2_HOME="${LTX2_HOME:-/opt/ltx2}"
WORKFLOW_DST="${COMFYUI_DIR}/user/default/workflows"
PERSISTENT_ROOT="${PERSISTENT_ROOT:-/runpod-volume}"
PERSIST_MODELS_SUBDIR="${PERSIST_MODELS_SUBDIR:-models}"
PERSIST_INPUT_SUBDIR="${PERSIST_INPUT_SUBDIR:-input}"
PERSIST_OUTPUT_SUBDIR="${PERSIST_OUTPUT_SUBDIR:-output}"
PERSIST_WORKFLOWS_SUBDIR="${PERSIST_WORKFLOWS_SUBDIR:-workflows}"

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

echo "[entrypoint] preparing ComfyUI folders..."
mkdir -p "${COMFYUI_DIR}/models" "${COMFYUI_DIR}/input" "${COMFYUI_DIR}/output" "${WORKFLOW_DST}"

mkdir -p "${PERSISTENT_ROOT}" 2>/dev/null || true

if [ -d "${PERSISTENT_ROOT}" ] && [ -w "${PERSISTENT_ROOT}" ]; then
  echo "[entrypoint] using persistent storage at ${PERSISTENT_ROOT}"
  MODELS_DIR="${PERSISTENT_ROOT}/${PERSIST_MODELS_SUBDIR}"
  INPUT_DIR="${PERSISTENT_ROOT}/${PERSIST_INPUT_SUBDIR}"
  OUTPUT_DIR="${PERSISTENT_ROOT}/${PERSIST_OUTPUT_SUBDIR}"
  WORKFLOWS_DIR="${PERSISTENT_ROOT}/${PERSIST_WORKFLOWS_SUBDIR}"

  link_dir "${COMFYUI_DIR}/models" "${MODELS_DIR}"
  link_dir "${COMFYUI_DIR}/input" "${INPUT_DIR}"
  link_dir "${COMFYUI_DIR}/output" "${OUTPUT_DIR}"
  link_dir "${WORKFLOW_DST}" "${WORKFLOWS_DIR}"

  export COMFYUI_MODELS_DIR="${MODELS_DIR}"
  export HF_HOME="${HF_HOME:-${PERSISTENT_ROOT}/hf-cache}"
  mkdir -p "${HF_HOME}"
else
  echo "[entrypoint] warning: PERSISTENT_ROOT='${PERSISTENT_ROOT}' is not writable. Falling back to container storage."
  export COMFYUI_MODELS_DIR="${COMFYUI_DIR}/models"
fi

if [ -d "${LTX2_HOME}/workflows" ] && compgen -G "${LTX2_HOME}/workflows/*.json" > /dev/null; then
  cp -n "${LTX2_HOME}"/workflows/*.json "${WORKFLOW_DST}/" 2>/dev/null || true
fi

if [ "${MODELS_AUTO_DOWNLOAD:-true}" = "true" ]; then
  echo "[entrypoint] model auto-download is enabled."
  "${LTX2_HOME}/scripts/download_models.sh"
else
  echo "[entrypoint] MODELS_AUTO_DOWNLOAD=false, skipping model bootstrap."
fi

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
