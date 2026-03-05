import base64
import binascii
import copy
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


COMFYUI_DIR = os.getenv("COMFYUI_DIR", "/ComfyUI")
DEFAULT_COMFYUI_URL = os.getenv("COMFYUI_API_URL", "http://127.0.0.1:8188").rstrip("/")
DEFAULT_HTTP_TIMEOUT = float(os.getenv("COMFYUI_HTTP_TIMEOUT_SECONDS", "30"))
DEFAULT_POLL_INTERVAL = float(os.getenv("COMFYUI_POLL_INTERVAL_SECONDS", "2"))
DEFAULT_JOB_TIMEOUT = float(os.getenv("COMFYUI_JOB_TIMEOUT_SECONDS", "1800"))
DEFAULT_WORKFLOW_DIR = Path(os.getenv("WORKFLOW_DIR", "/opt/ltx2/workflows"))
DEFAULT_INPUT_DIR = Path(os.getenv("COMFYUI_INPUT_DIR", f"{COMFYUI_DIR}/input"))
DEFAULT_OUTPUT_DIR = Path(os.getenv("COMFYUI_OUTPUT_DIR", f"{COMFYUI_DIR}/output"))
DEFAULT_TEMP_DIR = Path(os.getenv("COMFYUI_TEMP_DIR", f"{COMFYUI_DIR}/temp"))
DEFAULT_CLEANUP_JOB_INPUTS = os.getenv("CLEANUP_JOB_INPUTS", "true")
DEFAULT_CLEANUP_JOB_OUTPUTS = os.getenv("CLEANUP_JOB_OUTPUTS", "true")
DEFAULT_MAX_INLINE_OUTPUT_MB = float(os.getenv("MAX_INLINE_OUTPUT_MB", "30"))
DEFAULT_MAX_INPUT_IMAGE_MB = float(os.getenv("MAX_INPUT_IMAGE_MB", "30"))

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

INPUT_IMAGE_ALIASES = ["image", "image_path", "input_image", "reference_image"]


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
            fps = _to_int(req.get("fps", 24), "fps")
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


def _safe_filename(filename: str) -> str:
    safe = Path(str(filename)).name.strip()
    if not safe or safe in {".", ".."}:
        return "input.png"
    return safe.replace("\x00", "")


def _unique_file_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(filename)
    candidate = directory / safe_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    while True:
        candidate = directory / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
        if not candidate.exists():
            return candidate


def _infer_extension_from_mime(mime: str | None, default_ext: str = ".png") -> str:
    if not mime:
        return default_ext
    ext = mimetypes.guess_extension(mime)
    if ext == ".jpe":
        ext = ".jpg"
    return ext or default_ext


def _decode_base64_image(payload: str) -> tuple[bytes, str]:
    raw_payload = payload.strip()
    mime_type: str | None = None

    if raw_payload.startswith("data:"):
        parts = raw_payload.split(",", 1)
        if len(parts) != 2:
            raise ValueError("Invalid data URI for input image.")
        header, raw_payload = parts
        mime_type = header[5:].split(";")[0] or None

    compact = "".join(raw_payload.split())
    if not compact:
        raise ValueError("input_image_base64 is empty.")

    try:
        data = base64.b64decode(compact, validate=True)
    except binascii.Error:
        padding = "=" * (-len(compact) % 4)
        try:
            data = base64.b64decode(compact + padding, validate=False)
        except binascii.Error as exc:
            raise ValueError("Invalid base64 image payload.") from exc

    if not data:
        raise ValueError("Decoded input image is empty.")

    return data, _infer_extension_from_mime(mime_type)


def _write_input_file(data: bytes, filename: str) -> Path:
    max_bytes = int(DEFAULT_MAX_INPUT_IMAGE_MB * 1024 * 1024)
    if len(data) > max_bytes:
        raise ValueError(f"Input image exceeds MAX_INPUT_IMAGE_MB ({DEFAULT_MAX_INPUT_IMAGE_MB} MB).")

    path = _unique_file_path(DEFAULT_INPUT_DIR, filename)
    path.write_bytes(data)
    return path


def _materialize_input_image(req: dict[str, Any]) -> Path | None:
    base64_payload = req.get("input_image_base64") or req.get("image_base64")
    if base64_payload:
        data, ext = _decode_base64_image(str(base64_payload))
        filename = str(req.get("input_image_name", f"api_input_{uuid.uuid4().hex}{ext}"))
        path = _write_input_file(data, filename)
        req["input_image"] = path.name
        return path

    image_url = req.get("input_image_url") or req.get("image_url")
    if image_url:
        response = requests.get(str(image_url), timeout=DEFAULT_HTTP_TIMEOUT)
        response.raise_for_status()
        mime_type = response.headers.get("content-type", "").split(";")[0].strip() or None
        ext = _infer_extension_from_mime(mime_type)
        filename = str(req.get("input_image_name", f"api_input_{uuid.uuid4().hex}{ext}"))
        path = _write_input_file(response.content, filename)
        req["input_image"] = path.name
        return path

    input_image = req.get("input_image")
    if isinstance(input_image, str) and input_image.strip():
        path = Path(input_image)
        if path.is_absolute() and path.exists() and path.is_file():
            data = path.read_bytes()
            target = _write_input_file(data, req.get("input_image_name", path.name))
            req["input_image"] = target.name
            return target
        req["input_image"] = _safe_filename(input_image)

    return None


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


def _resolve_output_local_path(output_item: dict[str, Any]) -> Path | None:
    output_type = str(output_item.get("type", "output"))
    base_dir = {
        "output": DEFAULT_OUTPUT_DIR,
        "input": DEFAULT_INPUT_DIR,
        "temp": DEFAULT_TEMP_DIR,
    }.get(output_type, DEFAULT_OUTPUT_DIR)

    filename = output_item.get("filename")
    if not filename:
        return None

    subfolder = str(output_item.get("subfolder", "")).strip("/\\")
    candidate = (base_dir / subfolder / _safe_filename(str(filename))).resolve()
    base_resolved = base_dir.resolve()

    if candidate != base_resolved and base_resolved not in candidate.parents:
        return None

    return candidate


def _attach_inline_base64(outputs: list[dict[str, Any]], max_mb: float) -> None:
    max_bytes = int(max_mb * 1024 * 1024)
    for item in outputs:
        path = _resolve_output_local_path(item)
        if path is None or not path.exists() or not path.is_file():
            item["inline_status"] = "missing"
            continue

        file_size = path.stat().st_size
        if file_size > max_bytes:
            item["inline_status"] = "too_large"
            item["size_bytes"] = file_size
            continue

        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        item["mime_type"] = mime_type
        item["size_bytes"] = file_size
        item["base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
        item["inline_status"] = "ok"


def _cleanup_outputs(outputs: list[dict[str, Any]]) -> int:
    deleted = 0
    for item in outputs:
        path = _resolve_output_local_path(item)
        if path is None:
            item["deleted"] = False
            continue
        try:
            if path.exists() and path.is_file():
                path.unlink()
                deleted += 1
                item["deleted"] = True
            else:
                item["deleted"] = False
        except OSError:
            item["deleted"] = False
    return deleted


def _cleanup_input_file(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except OSError:
        return False
    return False


def handle_event(event: dict[str, Any]) -> dict[str, Any]:
    created_input_file: Path | None = None
    try:
        req = _event_input(event)
        comfy_url = str(req.get("comfyui_url", DEFAULT_COMFYUI_URL)).rstrip("/")

        created_input_file = _materialize_input_image(req)

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
                "note": "Job queued. Outputs/input cleanup runs after completion only when wait=true.",
            }

        timeout_s = _to_float(req.get("timeout_seconds", DEFAULT_JOB_TIMEOUT), "timeout_seconds")
        poll_s = _to_float(req.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL), "poll_interval_seconds")
        history_entry = _wait_for_history(comfy_url, prompt_id, timeout_s=timeout_s, poll_s=poll_s)
        outputs = _extract_outputs(history_entry, comfy_url)

        return_inline_base64 = _to_bool(req.get("return_output_base64"), False)
        if return_inline_base64:
            max_inline_mb = _to_float(req.get("max_inline_output_mb", DEFAULT_MAX_INLINE_OUTPUT_MB), "max_inline_output_mb")
            _attach_inline_base64(outputs, max_inline_mb)

        preserve_outputs = _to_bool(req.get("preserve_outputs"), False)
        cleanup_outputs = _to_bool(req.get("cleanup_outputs"), _to_bool(DEFAULT_CLEANUP_JOB_OUTPUTS, True))
        cleanup_inputs = _to_bool(req.get("cleanup_inputs"), _to_bool(DEFAULT_CLEANUP_JOB_INPUTS, True))

        outputs_deleted = 0
        if cleanup_outputs and not preserve_outputs:
            outputs_deleted = _cleanup_outputs(outputs)

        input_deleted = False
        if cleanup_inputs:
            input_deleted = _cleanup_input_file(created_input_file)

        return {
            "ok": True,
            "mode": "completed",
            "prompt_id": prompt_id,
            "client_id": client_id,
            "applied_overrides": patched,
            "outputs": outputs,
            "cleanup": {
                "outputs_deleted": outputs_deleted,
                "input_deleted": input_deleted,
                "preserve_outputs": preserve_outputs,
            },
            "history": history_entry,
        }
    except Exception as exc:  # pragma: no cover
        _cleanup_input_file(created_input_file)
        return {"ok": False, "error": str(exc)}
