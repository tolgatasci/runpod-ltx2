import copy
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


DEFAULT_COMFYUI_URL = os.getenv("COMFYUI_API_URL", "http://127.0.0.1:8188").rstrip("/")
DEFAULT_HTTP_TIMEOUT = float(os.getenv("COMFYUI_HTTP_TIMEOUT_SECONDS", "30"))
DEFAULT_POLL_INTERVAL = float(os.getenv("COMFYUI_POLL_INTERVAL_SECONDS", "2"))
DEFAULT_JOB_TIMEOUT = float(os.getenv("COMFYUI_JOB_TIMEOUT_SECONDS", "1800"))
DEFAULT_WORKFLOW_DIR = Path(os.getenv("WORKFLOW_DIR", "/opt/ltx2/workflows"))

WORKFLOW_ALIASES = {
    "image_to_video": "image_to_video.json",
    "cinematic_i2v": "cinematic_i2v.json",
}

PARAM_ALIASES = {
    "width": ["width", "image_width", "w"],
    "height": ["height", "image_height", "h"],
    "fps": ["fps", "frame_rate"],
    "frames": ["frames", "num_frames", "frame_count", "length"],
    "steps": ["steps", "num_steps", "sampling_steps"],
    "seed": ["seed", "noise_seed"],
    "cfg": ["cfg", "cfg_scale", "guidance", "guidance_scale"],
    "denoise": ["denoise", "denoise_strength"],
}

PROMPT_ALIASES = {
    "positive_prompt": ["positive_prompt", "positive", "prompt", "text"],
    "negative_prompt": ["negative_prompt", "negative", "neg_prompt"],
}

INPUT_IMAGE_ALIASES = ["image", "image_path", "input_image", "reference_image", "filename"]


def _event_input(event: Any) -> dict[str, Any]:
    if isinstance(event, dict) and isinstance(event.get("input"), dict):
        return event["input"]
    if isinstance(event, dict):
        return event
    raise ValueError("Request body must be a JSON object.")


def _to_int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{field}' must be an integer.") from exc


def _to_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{field}' must be a number.") from exc


def _to_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def _load_prompt_from_file(workflow_name: str) -> dict[str, Any]:
    filename = WORKFLOW_ALIASES.get(workflow_name, workflow_name)
    path = Path(filename)
    if not path.is_absolute():
        path = DEFAULT_WORKFLOW_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _is_api_prompt(prompt: dict[str, Any]) -> bool:
    if not isinstance(prompt, dict) or not prompt:
        return False
    for value in prompt.values():
        if not isinstance(value, dict):
            continue
        if "class_type" in value and isinstance(value.get("inputs"), dict):
            return True
    return False


def _is_ui_workflow(prompt: dict[str, Any]) -> bool:
    return isinstance(prompt, dict) and isinstance(prompt.get("nodes"), list)


def _iter_node_inputs(prompt: dict[str, Any]):
    for node_id, node_data in prompt.items():
        if not isinstance(node_data, dict):
            continue
        inputs = node_data.get("inputs")
        if isinstance(inputs, dict):
            yield str(node_id), inputs


def _extract_tuning_values(req: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in ("width", "height", "fps", "frames", "steps", "seed"):
        if key in req and req[key] is not None:
            values[key] = _to_int(req[key], key)
    for key in ("cfg", "denoise"):
        if key in req and req[key] is not None:
            values[key] = _to_float(req[key], key)

    duration = req.get("duration_seconds", req.get("duration"))
    if duration is not None:
        duration = _to_float(duration, "duration_seconds")
        fps = values.get("fps")
        if fps is None:
            fps_from_req = req.get("fps", 24)
            fps = _to_int(fps_from_req, "fps")
            values["fps"] = fps
        values["frames"] = max(1, int(round(duration * fps)))

    return values


def _apply_param_aliases(prompt: dict[str, Any], values: dict[str, Any]) -> list[dict[str, Any]]:
    patched: list[dict[str, Any]] = []
    for node_id, inputs in _iter_node_inputs(prompt):
        for logical_key, new_value in values.items():
            aliases = PARAM_ALIASES.get(logical_key, [])
            for input_key in aliases:
                if input_key in inputs:
                    old_value = inputs[input_key]
                    inputs[input_key] = new_value
                    patched.append(
                        {
                            "node_id": node_id,
                            "input": input_key,
                            "old": old_value,
                            "new": new_value,
                            "source": logical_key,
                        }
                    )
    return patched


def _apply_prompt_text(prompt: dict[str, Any], req: dict[str, Any]) -> list[dict[str, Any]]:
    patched: list[dict[str, Any]] = []
    for logical_key, aliases in PROMPT_ALIASES.items():
        text = req.get(logical_key)
        if text is None:
            continue
        for node_id, inputs in _iter_node_inputs(prompt):
            for input_key in aliases:
                if input_key in inputs and isinstance(inputs[input_key], str):
                    old_value = inputs[input_key]
                    inputs[input_key] = text
                    patched.append(
                        {
                            "node_id": node_id,
                            "input": input_key,
                            "old": old_value,
                            "new": text,
                            "source": logical_key,
                        }
                    )
    return patched


def _apply_input_image(prompt: dict[str, Any], req: dict[str, Any]) -> list[dict[str, Any]]:
    input_image = req.get("input_image")
    if not input_image:
        return []
    patched: list[dict[str, Any]] = []
    for node_id, inputs in _iter_node_inputs(prompt):
        for input_key in INPUT_IMAGE_ALIASES:
            if input_key in inputs and isinstance(inputs[input_key], str):
                old_value = inputs[input_key]
                inputs[input_key] = input_image
                patched.append(
                    {
                        "node_id": node_id,
                        "input": input_key,
                        "old": old_value,
                        "new": input_image,
                        "source": "input_image",
                    }
                )
    return patched


def _apply_node_overrides(prompt: dict[str, Any], node_overrides: Any) -> list[dict[str, Any]]:
    if not node_overrides:
        return []
    if not isinstance(node_overrides, dict):
        raise ValueError("'node_overrides' must be an object keyed by node id.")

    patched: list[dict[str, Any]] = []
    for node_id, override_map in node_overrides.items():
        node_key = str(node_id)
        resolved_key: Any = node_key if node_key in prompt else node_id
        if resolved_key not in prompt:
            raise ValueError(f"Node '{node_key}' not found in prompt graph.")
        node_data = prompt[resolved_key]
        if not isinstance(node_data, dict) or not isinstance(node_data.get("inputs"), dict):
            raise ValueError(f"Node '{node_key}' does not have editable inputs.")
        if not isinstance(override_map, dict):
            raise ValueError(f"Override for node '{node_key}' must be an object.")

        for input_key, new_value in override_map.items():
            old_value = node_data["inputs"].get(input_key)
            node_data["inputs"][input_key] = new_value
            patched.append(
                {
                    "node_id": node_key,
                    "input": input_key,
                    "old": old_value,
                    "new": new_value,
                    "source": "node_overrides",
                }
            )

    return patched


def _submit_prompt(comfy_url: str, prompt: dict[str, Any], client_id: str) -> dict[str, Any]:
    response = requests.post(
        f"{comfy_url}/prompt",
        json={"prompt": prompt, "client_id": client_id},
        timeout=DEFAULT_HTTP_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if "prompt_id" not in payload:
        raise RuntimeError(f"Invalid ComfyUI response: {payload}")
    return payload


def _wait_for_history(comfy_url: str, prompt_id: str, timeout_s: float, poll_s: float) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = requests.get(f"{comfy_url}/history/{prompt_id}", timeout=DEFAULT_HTTP_TIMEOUT)
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, dict) and prompt_id in payload:
                return payload[prompt_id]
        time.sleep(poll_s)
    raise TimeoutError(f"Timed out while waiting for prompt '{prompt_id}' completion.")


def _extract_outputs(history_entry: dict[str, Any], comfy_url: str) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for node_id, node_output in history_entry.get("outputs", {}).items():
        if not isinstance(node_output, dict):
            continue
        for output_type, output_items in node_output.items():
            if not isinstance(output_items, list):
                continue
            for item in output_items:
                if not isinstance(item, dict) or "filename" not in item:
                    continue
                query = urlencode(
                    {
                        "filename": item.get("filename", ""),
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    }
                )
                outputs.append(
                    {
                        "node_id": str(node_id),
                        "output_type": output_type,
                        "filename": item.get("filename"),
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                        "url": f"{comfy_url}/view?{query}",
                    }
                )
    return outputs


def handle_event(event: dict[str, Any]) -> dict[str, Any]:
    try:
        req = _event_input(event)
        comfy_url = str(req.get("comfyui_url", DEFAULT_COMFYUI_URL)).rstrip("/")

        prompt = req.get("prompt")
        if prompt is None:
            workflow_name = str(req.get("workflow", "image_to_video"))
            prompt = _load_prompt_from_file(workflow_name)
        elif isinstance(prompt, str):
            prompt = json.loads(prompt)

        if not isinstance(prompt, dict):
            raise ValueError("'prompt' must be a JSON object.")

        if _is_ui_workflow(prompt):
            raise ValueError(
                "Workflow is in ComfyUI UI format ('nodes'). Send API prompt format "
                "('class_type' + 'inputs') via 'prompt', or provide an API-format file."
            )
        if not _is_api_prompt(prompt):
            raise ValueError("Prompt graph is not valid ComfyUI API format.")

        prompt_graph = copy.deepcopy(prompt)
        patched: list[dict[str, Any]] = []

        tuning_values = _extract_tuning_values(req)
        patched.extend(_apply_param_aliases(prompt_graph, tuning_values))
        patched.extend(_apply_prompt_text(prompt_graph, req))
        patched.extend(_apply_input_image(prompt_graph, req))
        patched.extend(_apply_node_overrides(prompt_graph, req.get("node_overrides")))

        client_id = str(req.get("client_id", uuid.uuid4()))
        submit_payload = _submit_prompt(comfy_url, prompt_graph, client_id)
        prompt_id = str(submit_payload["prompt_id"])

        wait_for_completion = _to_bool(req.get("wait"), True)
        if not wait_for_completion:
            return {
                "ok": True,
                "mode": "queued",
                "prompt_id": prompt_id,
                "client_id": client_id,
                "applied_overrides": patched,
                "submit_response": submit_payload,
            }

        timeout_s = _to_float(req.get("timeout_seconds", DEFAULT_JOB_TIMEOUT), "timeout_seconds")
        poll_s = _to_float(req.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL), "poll_interval_seconds")
        history_entry = _wait_for_history(comfy_url, prompt_id, timeout_s=timeout_s, poll_s=poll_s)
        outputs = _extract_outputs(history_entry, comfy_url)

        return {
            "ok": True,
            "mode": "completed",
            "prompt_id": prompt_id,
            "client_id": client_id,
            "applied_overrides": patched,
            "outputs": outputs,
            "history": history_entry,
        }
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}
