FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_DIR=/ComfyUI \
    LTX2_HOME=/opt/ltx2 \
    PERSISTENT_ROOT=/runpod-volume \
    MODELS_AUTO_DOWNLOAD=true \
    DOWNLOAD_ONCE=true \
    REQUIRE_ALL_MODELS=false \
    RUNPOD_SERVERLESS=false \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    PERSIST_MODELS=true \
    PERSIST_INPUT=false \
    PERSIST_OUTPUT=false \
    PERSIST_WORKFLOWS=false \
    PERSIST_HF_CACHE=true \
    RUNTIME_ROOT=/tmp/ltx2-runtime \
    RUNTIME_PRUNE_ENABLED=true \
    PRUNE_INTERVAL_SECONDS=300 \
    INPUT_RETENTION_SECONDS=900 \
    OUTPUT_RETENTION_SECONDS=900 \
    TEMP_RETENTION_SECONDS=900 \
    CLEANUP_JOB_INPUTS=true \
    CLEANUP_JOB_OUTPUTS=true \
    MAX_INPUT_IMAGE_MB=30 \
    MAX_INLINE_OUTPUT_MB=30 \
    LTX2_MODEL_SOURCE=hf://Lightricks/LTX-2/ltx-2-19b-distilled-fp8.safetensors \
    GEMMA_TEXT_ENCODER_SOURCE=hf://Comfy-Org/ltx-2/split_files/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors \
    GEMMA_TOKENIZER_SOURCE=hf://Lightricks/LTX-2/tokenizer/tokenizer.model \
    GEMMA_PREPROCESSOR_SOURCE=hf://Lightricks/LTX-2/tokenizer/preprocessor_config.json \
    SPATIAL_UPSCALER_SOURCE=hf://Lightricks/LTX-2/ltx-2-spatial-upscaler-x2-1.0.safetensors \
    TEMPORAL_UPSCALER_SOURCE=hf://Lightricks/LTX-2/ltx-2-temporal-upscaler-x2-1.0.safetensors \
    IC_LORA_UNION_SOURCE=hf://Lightricks/LTX-2-19b-IC-LoRA-Union-Control/ltx-2-19b-ic-lora-union-control-ref0.5.safetensors \
    CAMERA_MOTION_LORA_SOURCE=hf://Lightricks/LTX-2-19b-LoRA-Camera-Control-Static/ltx-2-19b-lora-camera-control-static.safetensors

WORKDIR /

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    python3 \
    python3-pip \
    ffmpeg \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /runpod-volume

RUN python3 -m pip install --upgrade pip setuptools wheel

RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_DIR}

WORKDIR ${COMFYUI_DIR}

RUN sed -i 's/comfy-aimdo>=0.2.7/comfy-aimdo>=0.2.6,<0.2.7/g' requirements.txt \
    && python3 -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 \
    && python3 -m pip install -r requirements.txt

RUN git clone --depth 1 https://github.com/Lightricks/ComfyUI-LTXVideo custom_nodes/ComfyUI-LTXVideo \
    && git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite custom_nodes/VideoHelperSuite

COPY custom_nodes ${COMFYUI_DIR}/custom_nodes

RUN set -eux; \
    for req in custom_nodes/*/requirements.txt; do \
      if [ -f "$req" ]; then python3 -m pip install -r "$req"; fi; \
    done

WORKDIR ${LTX2_HOME}

COPY requirements.txt ${LTX2_HOME}/requirements.txt
RUN python3 -m pip install -r ${LTX2_HOME}/requirements.txt

COPY workflows ${LTX2_HOME}/workflows
COPY scripts ${LTX2_HOME}/scripts
COPY api ${LTX2_HOME}/api
COPY start.sh /start.sh

RUN chmod +x /start.sh ${LTX2_HOME}/scripts/download_models.sh

EXPOSE 8188

CMD ["/start.sh"]
