#!/usr/bin/env python3
"""
Local test script for LTX-2 RunPod handler.
Usage: python test_local.py
"""
import json
import base64
import requests
import sys
import os

# ─── Configuration ───
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
ENDPOINT_ID = os.environ.get("RUNPOD_LTX2_ENDPOINT_ID", "")
BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {RUNPOD_API_KEY}",
}


def test_text_to_video():
    """Test text-to-video generation."""
    payload = {
        "input": {
            "prompt": "A cinematic documentary shot of ancient Roman ruins at golden hour, "
                      "slow camera pan revealing detailed stone columns, warm natural lighting, "
                      "photorealistic, 4K quality",
            "mode": "t2v",
            "width": 768,
            "height": 512,
            "num_frames": 81,       # ~3.2s at 25fps
            "frame_rate": 25.0,
            "num_inference_steps": 40,
            "cfg_scale": 3.0,
            "seed": 42,
        }
    }

    print("=" * 60)
    print("TEST: Text-to-Video")
    print(f"Prompt: {payload['input']['prompt'][:80]}...")
    print(f"Resolution: {payload['input']['width']}x{payload['input']['height']}")
    print(f"Frames: {payload['input']['num_frames']} @ {payload['input']['frame_rate']}fps")
    print("=" * 60)

    return send_request(payload)


def test_image_to_video(image_path):
    """Test image-to-video generation."""
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "input": {
            "prompt": "Slow cinematic camera movement, the scene comes to life with subtle motion",
            "mode": "i2v",
            "image_base64": image_b64,
            "image_strength": 1.0,
            "width": 768,
            "height": 512,
            "num_frames": 81,
            "frame_rate": 25.0,
            "num_inference_steps": 40,
            "seed": 42,
        }
    }

    print("=" * 60)
    print("TEST: Image-to-Video")
    print(f"Image: {image_path}")
    print(f"Frames: {payload['input']['num_frames']} @ {payload['input']['frame_rate']}fps")
    print("=" * 60)

    return send_request(payload)


def test_distilled():
    """Test distilled pipeline (faster, 8 steps)."""
    payload = {
        "input": {
            "prompt": "A beautiful mountain landscape with clouds moving slowly, aerial drone shot",
            "mode": "t2v",
            "pipeline_type": "distilled",
            "width": 768,
            "height": 512,
            "num_frames": 41,       # ~1.6s at 25fps
            "frame_rate": 25.0,
            "seed": 123,
        }
    }

    print("=" * 60)
    print("TEST: Distilled Pipeline (8 steps)")
    print("=" * 60)

    return send_request(payload)


def send_request(payload):
    """Send request to RunPod endpoint."""
    if not RUNPOD_API_KEY or not ENDPOINT_ID:
        print("ERROR: Set RUNPOD_API_KEY and RUNPOD_LTX2_ENDPOINT_ID env vars")
        return None

    # Use async (run) since video gen takes time
    print("Sending request (async)...")
    resp = requests.post(f"{BASE_URL}/run", json=payload, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    job_id = data.get("id")
    print(f"Job ID: {job_id}")

    # Poll for result
    import time
    max_wait = 600  # 10 minutes
    start = time.time()

    while time.time() - start < max_wait:
        status_resp = requests.get(f"{BASE_URL}/status/{job_id}", headers=HEADERS, timeout=30)
        status_data = status_resp.json()
        status = status_data.get("status")

        if status == "COMPLETED":
            output = status_data.get("output", {})
            if "error" in output:
                print(f"ERROR: {output['error']}")
                return None

            print(f"Duration: {output.get('duration_s')}s")
            print(f"Resolution: {output.get('resolution')}")
            print(f"Frames: {output.get('num_frames')}")
            print(f"Inference time: {output.get('inference_time_s')}s")
            print(f"File size: {output.get('file_size_mb')}MB")
            print(f"Seed: {output.get('seed')}")

            # Save video
            video_b64 = output.get("video_base64", "")
            if video_b64:
                out_name = f"test_output_{int(time.time())}.mp4"
                with open(out_name, "wb") as f:
                    f.write(base64.b64decode(video_b64))
                print(f"Saved: {out_name}")

            return output

        elif status == "FAILED":
            print(f"FAILED: {status_data.get('error', 'Unknown error')}")
            return None

        else:
            elapsed = int(time.time() - start)
            print(f"  Status: {status} ({elapsed}s elapsed)")
            time.sleep(10)

    print("TIMEOUT: Job did not complete in time")
    return None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "i2v":
        image_path = sys.argv[2] if len(sys.argv) > 2 else "test_image.jpg"
        test_image_to_video(image_path)
    elif len(sys.argv) > 1 and sys.argv[1] == "distilled":
        test_distilled()
    else:
        test_text_to_video()
