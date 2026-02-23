# ============================================================
# RunPod Serverless: LTX-2 (19B) Video Generation
# GPU: A100 80GB (recommended) / L40S 48GB (FP8)
# ============================================================

FROM runpod/pytorch:2.7.0-py3.12-cuda12.9.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    PYTHONUNBUFFERED=1 \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    MODELS_DIR=/models \
    LTX2_PIPELINE=two_stage \
    LTX2_FP8=true \
    LTX2_LORA_STRENGTH=0.8

# ─── System dependencies ───
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    git \
    git-lfs \
    aria2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ─── Python dependencies (pinned versions) ───
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ─── Install LTX-2 from source ───
RUN git clone https://github.com/Lightricks/LTX-2.git /tmp/ltx2 && \
    cd /tmp/ltx2 && \
    pip install --no-cache-dir ./ltx-core && \
    pip install --no-cache-dir ./ltx-pipelines && \
    rm -rf /tmp/ltx2/.git

# ─── Download model files ───
# FP8 checkpoint (~27GB) + distilled LoRA (~7.7GB) + spatial upscaler (~1GB)
# + component directories (text_encoder/Gemma-3, vae, audio_vae, etc.)
RUN mkdir -p ${MODELS_DIR} && \
    pip install --no-cache-dir huggingface_hub[cli] && \
    huggingface-cli download Lightricks/LTX-2 \
        ltx-2-19b-dev-fp8.safetensors \
        ltx-2-19b-distilled-fp8.safetensors \
        ltx-2-19b-distilled-lora-384.safetensors \
        ltx-2-spatial-upscaler-x2-1.0.safetensors \
        model_index.json \
        --local-dir ${MODELS_DIR}/ltx-2 && \
    huggingface-cli download Lightricks/LTX-2 \
        --include "audio_vae/*" "connectors/*" "latent_upsampler/*" \
                  "scheduler/*" "text_encoder/*" "tokenizer/*" \
                  "transformer/*" "vae/*" "vocoder/*" \
        --local-dir ${MODELS_DIR}/ltx-2

# ─── Symlink model files to expected paths ───
RUN ln -sf ${MODELS_DIR}/ltx-2/ltx-2-19b-dev-fp8.safetensors ${MODELS_DIR}/ltx-2-19b-dev-fp8.safetensors && \
    ln -sf ${MODELS_DIR}/ltx-2/ltx-2-19b-distilled-fp8.safetensors ${MODELS_DIR}/ltx-2-19b-distilled-fp8.safetensors && \
    ln -sf ${MODELS_DIR}/ltx-2/ltx-2-19b-distilled-lora-384.safetensors ${MODELS_DIR}/ltx-2-19b-distilled-lora-384.safetensors && \
    ln -sf ${MODELS_DIR}/ltx-2/ltx-2-spatial-upscaler-x2-1.0.safetensors ${MODELS_DIR}/ltx-2-spatial-upscaler-x2-1.0.safetensors && \
    ln -sf ${MODELS_DIR}/ltx-2/text_encoder ${MODELS_DIR}/gemma-3

# ─── Copy handler ───
COPY handler.py .

# ─── Healthcheck ───
HEALTHCHECK --interval=30s --timeout=10s CMD python -c "import torch; assert torch.cuda.is_available()"

CMD ["python", "-u", "handler.py"]
