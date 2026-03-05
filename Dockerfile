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
    HF_HUB_ENABLE_HF_TRANSFER=1

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

RUN python3 -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 \
    && python3 -m pip install -r requirements.txt

RUN git clone --depth 1 https://github.com/Lightricks/ComfyUI-LTXVideo custom_nodes/ComfyUI-LTXVideo \
    && git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite custom_nodes/VideoHelperSuite

RUN set -eux; \
    for req in custom_nodes/*/requirements.txt; do \
      if [ -f "$req" ]; then python3 -m pip install -r "$req"; fi; \
    done

WORKDIR ${LTX2_HOME}

COPY requirements.txt ${LTX2_HOME}/requirements.txt
RUN python3 -m pip install -r ${LTX2_HOME}/requirements.txt

COPY workflows ${LTX2_HOME}/workflows
COPY scripts ${LTX2_HOME}/scripts
COPY start.sh /start.sh

RUN chmod +x /start.sh ${LTX2_HOME}/scripts/download_models.sh

EXPOSE 8188

CMD ["/start.sh"]
