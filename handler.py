#!/usr/bin/env python3
"""
RunPod Serverless Handler for LTX-2 (19B) Video Generation
Lightricks LTX-2: Text-to-Video + Image-to-Video

Supports:
  - Text-to-Video (T2V)
  - Image-to-Video (I2V) with single/multi keyframe conditioning
  - Two-stage pipeline (base + spatial upscaler)
  - FP8 quantization for lower VRAM
  - Distilled model (8 steps) for faster inference
"""

import os
import sys
import time
import base64
import tempfile
import traceback

import runpod

# ─── Global Pipeline (loaded once on cold start) ───
PIPELINE = None
PIPELINE_TYPE = None  # "two_stage" or "distilled"

# ─── Model paths (pre-downloaded in Docker image) ───
MODELS_DIR = os.environ.get("MODELS_DIR", "/models")
CHECKPOINT = os.path.join(MODELS_DIR, "ltx-2-19b-dev-fp8.safetensors")
DISTILLED_CHECKPOINT = os.path.join(MODELS_DIR, "ltx-2-19b-distilled-fp8.safetensors")
DISTILLED_LORA = os.path.join(MODELS_DIR, "ltx-2-19b-distilled-lora-384.safetensors")
SPATIAL_UPSCALER = os.path.join(MODELS_DIR, "ltx-2-spatial-upscaler-x2-1.0.safetensors")
TEMPORAL_UPSCALER = os.path.join(MODELS_DIR, "ltx-2-temporal-upscaler-x2-1.0.safetensors")
GEMMA_ROOT = os.path.join(MODELS_DIR, "gemma-3")

# ─── Pipeline mode from env (default: two_stage) ───
DEFAULT_PIPELINE = os.environ.get("LTX2_PIPELINE", "two_stage")
ENABLE_FP8 = os.environ.get("LTX2_FP8", "true").lower() == "true"
DISTILLED_LORA_STRENGTH = float(os.environ.get("LTX2_LORA_STRENGTH", "0.8"))


def get_pipeline(pipeline_type=None):
    """Load pipeline (singleton). Cold start ~60-120s depending on model size."""
    global PIPELINE, PIPELINE_TYPE

    target_type = pipeline_type or DEFAULT_PIPELINE

    if PIPELINE is not None and PIPELINE_TYPE == target_type:
        return PIPELINE

    print(f"[LTX-2] Loading pipeline: {target_type} (FP8={ENABLE_FP8})")
    start = time.time()

    if target_type == "distilled":
        from ltx_pipelines.distilled import DistilledPipeline

        ckpt = DISTILLED_CHECKPOINT if os.path.exists(DISTILLED_CHECKPOINT) else CHECKPOINT
        PIPELINE = DistilledPipeline(
            checkpoint_path=ckpt,
            spatial_upsampler_path=SPATIAL_UPSCALER if os.path.exists(SPATIAL_UPSCALER) else None,
            gemma_root=GEMMA_ROOT,
            fp8transformer=ENABLE_FP8,
        )
    else:
        from ltx_pipelines.ti2vid_two_stages import TI2VidTwoStagesPipeline

        distilled_lora_list = []
        if os.path.exists(DISTILLED_LORA):
            distilled_lora_list = [(DISTILLED_LORA, DISTILLED_LORA_STRENGTH)]

        PIPELINE = TI2VidTwoStagesPipeline(
            checkpoint_path=CHECKPOINT,
            distilled_lora=distilled_lora_list,
            spatial_upsampler_path=SPATIAL_UPSCALER if os.path.exists(SPATIAL_UPSCALER) else None,
            gemma_root=GEMMA_ROOT,
            loras=[],
            fp8transformer=ENABLE_FP8,
        )

    PIPELINE_TYPE = target_type
    elapsed = time.time() - start
    print(f"[LTX-2] Pipeline loaded in {elapsed:.1f}s")
    return PIPELINE


def save_base64_to_temp(b64_string, suffix=".jpg"):
    """Decode base64 string and save to temp file."""
    data = base64.b64decode(b64_string)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


def handler(job):
    """
    RunPod serverless handler.

    Input parameters:
        prompt (str, required): Text description of desired video
        negative_prompt (str, optional): What to avoid
        mode (str, optional): "t2v" or "i2v" (default: "t2v")
        pipeline_type (str, optional): "two_stage" or "distilled" (default: env LTX2_PIPELINE)

        # Video settings
        width (int, optional): Video width, must be divisible by 32 (default: 768)
        height (int, optional): Video height, must be divisible by 32 (default: 512)
        num_frames (int, optional): Number of frames, must be (8n+1) (default: 121)
        frame_rate (float, optional): FPS (default: 25.0)
        num_inference_steps (int, optional): Denoising steps (default: 40, 8 for distilled)
        seed (int, optional): Random seed for reproducibility

        # Guidance
        cfg_scale (float, optional): Text adherence 1.0-5.0 (default: 3.0)
        stg_scale (float, optional): Temporal coherence 0.5-1.5 (default: 1.0)
        rescale_scale (float, optional): Variance matching 0.5-0.7 (default: 0.7)
        stg_blocks (list[int], optional): Transformer blocks to perturb (default: [29])

        # Image-to-Video (mode="i2v")
        image_base64 (str): First frame image as base64
        image_end_base64 (str, optional): Last frame image as base64
        image_strength (float, optional): Conditioning strength 0.0-1.0 (default: 1.0)

    Returns:
        video_base64 (str): Generated video as base64 encoded MP4
        duration_s (float): Video duration in seconds
        resolution (str): "WxH"
        num_frames (int): Frame count
        frame_rate (float): FPS
        inference_time_s (float): Total generation time
        seed (int): Used seed
    """
    try:
        inp = job["input"]
        prompt = inp.get("prompt", "")
        if not prompt:
            return {"error": "prompt is required"}

        mode = inp.get("mode", "t2v")
        pipeline_type = inp.get("pipeline_type", None)
        negative_prompt = inp.get("negative_prompt", "")

        # Video settings
        width = inp.get("width", 768)
        height = inp.get("height", 512)
        num_frames = inp.get("num_frames", 121)
        frame_rate = inp.get("frame_rate", 25.0)
        seed = inp.get("seed", None)

        # Validate dimensions
        if width % 32 != 0:
            return {"error": f"width must be divisible by 32, got {width}"}
        if height % 32 != 0:
            return {"error": f"height must be divisible by 32, got {height}"}
        if (num_frames - 1) % 8 != 0:
            return {"error": f"num_frames must be (8n+1), e.g. 9,17,25,...,121. Got {num_frames}"}

        # Inference steps
        is_distilled = (pipeline_type == "distilled") or (
            pipeline_type is None and DEFAULT_PIPELINE == "distilled"
        )
        default_steps = 8 if is_distilled else 40
        num_inference_steps = inp.get("num_inference_steps", default_steps)

        # Guidance params
        cfg_scale = inp.get("cfg_scale", 1.0 if is_distilled else 3.0)
        stg_scale = inp.get("stg_scale", 0.0 if is_distilled else 1.0)
        rescale_scale = inp.get("rescale_scale", 0.0 if is_distilled else 0.7)
        stg_blocks = inp.get("stg_blocks", [29])

        print(f"[LTX-2] mode={mode} pipeline={pipeline_type or DEFAULT_PIPELINE} "
              f"res={width}x{height} frames={num_frames} steps={num_inference_steps}")

        # Load pipeline
        pipeline = get_pipeline(pipeline_type)

        # Prepare image conditioning for I2V
        images = []
        temp_files = []

        if mode == "i2v":
            image_b64 = inp.get("image_base64", "")
            if not image_b64:
                return {"error": "image_base64 is required for i2v mode"}

            strength = inp.get("image_strength", 1.0)
            img_path = save_base64_to_temp(image_b64, suffix=".jpg")
            temp_files.append(img_path)
            images.append((img_path, 0, strength))

            # Optional end frame
            image_end_b64 = inp.get("image_end_base64", "")
            if image_end_b64:
                end_strength = inp.get("image_end_strength", 1.0)
                end_path = save_base64_to_temp(image_end_b64, suffix=".jpg")
                temp_files.append(end_path)
                images.append((end_path, num_frames - 1, end_strength))

        # Output path
        output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
        temp_files.append(output_path)

        # Build guidance params
        from ltx_core.components.guiders import MultiModalGuiderParams

        guider_params = MultiModalGuiderParams(
            cfg_scale=cfg_scale,
            stg_scale=stg_scale,
            rescale_scale=rescale_scale,
            modality_scale=cfg_scale,
            stg_blocks=stg_blocks,
        )

        # Generate
        gen_start = time.time()

        call_kwargs = {
            "prompt": prompt,
            "output_path": output_path,
            "height": height,
            "width": width,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
            "num_inference_steps": num_inference_steps,
            "video_guider_params": guider_params,
            "audio_guider_params": guider_params,
        }

        if seed is not None:
            call_kwargs["seed"] = seed

        if negative_prompt:
            call_kwargs["negative_prompt"] = negative_prompt

        if images:
            call_kwargs["images"] = images

        pipeline(**call_kwargs)

        gen_time = time.time() - gen_start
        print(f"[LTX-2] Generation done in {gen_time:.1f}s")

        # Read output video
        if not os.path.exists(output_path):
            return {"error": "Video generation failed - no output file produced"}

        file_size = os.path.getsize(output_path)
        if file_size == 0:
            return {"error": "Video generation failed - output file is empty"}

        with open(output_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode("utf-8")

        duration_s = num_frames / frame_rate

        return {
            "video_base64": video_b64,
            "duration_s": round(duration_s, 2),
            "resolution": f"{width}x{height}",
            "num_frames": num_frames,
            "frame_rate": frame_rate,
            "inference_time_s": round(gen_time, 1),
            "seed": seed,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "pipeline": pipeline_type or DEFAULT_PIPELINE,
            "mode": mode,
        }

    except Exception as e:
        traceback.print_exc()
        return {"error": str(e), "traceback": traceback.format_exc()}

    finally:
        # Cleanup temp files
        for tmp in temp_files:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass


if __name__ == "__main__":
    print("[LTX-2] Starting RunPod Serverless Handler...")
    print(f"[LTX-2] Pipeline: {DEFAULT_PIPELINE} | FP8: {ENABLE_FP8}")
    print(f"[LTX-2] Models dir: {MODELS_DIR}")

    # Pre-warm pipeline on startup
    try:
        get_pipeline()
        print("[LTX-2] Pipeline pre-warmed successfully")
    except Exception as e:
        print(f"[LTX-2] Pipeline pre-warm failed (will retry on first request): {e}")

    runpod.serverless.start({"handler": handler})
