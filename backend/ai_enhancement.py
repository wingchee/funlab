import base64
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

BEAD_IMAGE_ENHANCEMENT_PROMPT = """Create a family-friendly Q-style pixel bead craft reference from the input image.

Requirements:
- Identify the core subject automatically and remove all background objects.
- Keep the full subject contour intact, including important hair, accessories, small decorations, transparent materials, and edge details that define the subject.
- Render the subject as a cute Q-style craft icon with bright block colors and clean simple lines.
- Center the subject and show the complete full body or complete upper-body crop; do not cut off important parts.
- Use a pure white (#FFFFFF) background or transparent-looking pure white background.
- Do not identify, label, or realistically reproduce any person; if a person appears, make the result generic and non-identifying.
- Add no shadows, complex textures, gradients, text, logos, or photographic details.
- Avoid background residue, broken subject parts, white edge halos, noisy borders, and extra objects.
- Keep the subject complete and easy to recognize at a small bead-grid size.
- Preserve silhouette, accessories, distinctive colors, and visual identity needed for a bead pattern while simplifying fine detail into bead-friendly color blocks.
- Output a PNG-style image suitable for converting into a Perler/Hama bead grid.
"""


def _provider_error_metadata(exc: Exception) -> dict:
    raw = str(exc)
    lowered = raw.lower()
    if (
        "moderation_blocked" in lowered
        or "safety system" in lowered
        or "image_generation_user_error" in lowered
    ):
        return {
            "error_type": "safety_blocked",
            "reason": "OpenAI safety system rejected this image edit request.",
            "provider_error": raw,
        }
    if "must be verified to use the model" in lowered:
        return {
            "error_type": "model_access_denied",
            "reason": "OpenAI rejected the configured image model; use gpt-image-1.5 or verify the organization.",
            "provider_error": raw,
        }
    if "timeout" in lowered or "timed out" in lowered:
        return {
            "error_type": "timeout",
            "reason": "OpenAI image enhancement timed out.",
            "provider_error": raw,
        }
    if "rate limit" in lowered or "429" in lowered:
        return {
            "error_type": "rate_limited",
            "reason": "OpenAI rate limit was reached. Try again later.",
            "provider_error": raw,
        }
    if "insufficient_quota" in lowered or "quota" in lowered or "billing" in lowered:
        return {
            "error_type": "quota_exceeded",
            "reason": "OpenAI quota or billing limit prevented image enhancement.",
            "provider_error": raw,
        }
    if "invalid_api_key" in lowered or "incorrect api key" in lowered or "401" in lowered:
        return {
            "error_type": "auth_failed",
            "reason": "OpenAI API authentication failed.",
            "provider_error": raw,
        }
    if (
        "invalid image" in lowered
        or "unsupported image" in lowered
        or "image too large" in lowered
        or "file size" in lowered
        or "400" in lowered
    ):
        return {
            "error_type": "invalid_image",
            "reason": "OpenAI rejected the image input. The upload may be too large, corrupted, or unsupported.",
            "provider_error": raw,
        }
    if "connection" in lowered or "network" in lowered or "dns" in lowered or "resolve" in lowered:
        return {
            "error_type": "network_error",
            "reason": "Network connection to OpenAI failed.",
            "provider_error": raw,
        }
    if "500" in lowered or "502" in lowered or "503" in lowered or "504" in lowered:
        return {
            "error_type": "provider_unavailable",
            "reason": "OpenAI image service was temporarily unavailable.",
            "provider_error": raw,
        }
    return {
        "error_type": "provider_error",
        "reason": raw,
    }


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except ValueError:
        return default


def _prepare_openai_input_image(
    image_path: str,
    workdir: str,
    metadata: dict,
    *,
    max_side: Optional[int] = None,
) -> str:
    """Normalize and shrink the image before sending it to OpenAI."""
    source = Path(image_path)
    max_side = max_side or _env_int("OPENAI_INPUT_MAX_SIDE", 1536)
    max_bytes = _env_int("OPENAI_INPUT_MAX_BYTES", 4 * 1024 * 1024)
    jpeg_quality = min(95, max(60, _env_int("OPENAI_INPUT_JPEG_QUALITY", 90)))

    input_meta = {
        "source_name": source.name,
        "original_bytes": source.stat().st_size if source.exists() else None,
        "max_side": max_side,
        "max_bytes": max_bytes,
    }

    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            input_meta["original_size"] = [int(image.width), int(image.height)]

            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                rgba = image.convert("RGBA")
                white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                white.alpha_composite(rgba)
                image = white.convert("RGB")
            else:
                image = image.convert("RGB")

            largest_side = max(image.size)
            resized = largest_side > max_side
            if resized:
                scale = max_side / largest_side
                next_size = (
                    max(1, round(image.width * scale)),
                    max(1, round(image.height * scale)),
                )
                image = image.resize(next_size, Image.Resampling.LANCZOS)

            output_path = Path(workdir) / "ai_input.jpg"
            quality = jpeg_quality
            while True:
                image.save(output_path, format="JPEG", quality=quality, optimize=True, progressive=True)
                if output_path.stat().st_size <= max_bytes or quality <= 70:
                    break
                quality -= 8

            input_meta.update(
                {
                    "output_name": output_path.name,
                    "output_bytes": output_path.stat().st_size,
                    "prepared_size": [int(image.width), int(image.height)],
                    "resized": resized,
                    "jpeg_quality": quality,
                }
            )
            metadata["input_image"] = input_meta
            return str(output_path)
    except Exception as exc:
        input_meta["preparation_error"] = str(exc)
        input_meta["used_original"] = True
        metadata["input_image"] = input_meta
        return image_path


def enhance_image_for_beads(image_path: str, workdir: str) -> tuple[str, dict]:
    """Use OpenAI image editing to make an upload bead-pattern friendly.

    The conversion pipeline still works without an API key or network access; in
    that case this returns the original image and records why AI was skipped.
    """
    metadata = {
        "attempted": True,
        "used": False,
        "provider": "openai",
        "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1.5"),
    }

    if os.getenv("PIXELCRAFT_DISABLE_AI_ENHANCEMENT", "").lower() in {"1", "true", "yes"}:
        metadata["error_type"] = "disabled"
        metadata["reason"] = "disabled"
        return image_path, metadata

    if not os.getenv("OPENAI_API_KEY"):
        metadata["error_type"] = "missing_api_key"
        metadata["reason"] = "OPENAI_API_KEY is not set"
        return image_path, metadata

    try:
        from openai import OpenAI
    except ImportError:
        metadata["error_type"] = "dependency_missing"
        metadata["reason"] = "openai package is not installed"
        return image_path, metadata

    try:
        base_url = os.getenv("OPENAI_BASE_URL") or None
        timeout = float(os.getenv("OPENAI_REQUEST_TIMEOUT", "45"))
        client = OpenAI(base_url=base_url, timeout=timeout) if base_url else OpenAI(timeout=timeout)
        model = metadata["model"]
        output_path = Path(workdir) / "ai_enhanced.png"
        input_path = _prepare_openai_input_image(image_path, workdir, metadata)

        params = {
            "model": model,
            "image": open(input_path, "rb"),
            "prompt": BEAD_IMAGE_ENHANCEMENT_PROMPT,
            "size": os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
            "quality": os.getenv("OPENAI_IMAGE_QUALITY", "medium"),
            "output_format": "png",
            "extra_body": {
                "moderation": os.getenv("OPENAI_IMAGE_MODERATION", "low"),
            },
        }
        if model == "gpt-image-1":
            params["input_fidelity"] = "high"

        with params["image"]:
            response = client.images.edit(**params)

        image_data = response.data[0]
        b64_json = getattr(image_data, "b64_json", None)
        image_url = getattr(image_data, "url", None)

        if b64_json:
            output_path.write_bytes(base64.b64decode(b64_json))
        elif image_url:
            with urlopen(image_url, timeout=30) as remote:
                output_path.write_bytes(remote.read())
        else:
            raise ValueError("OpenAI image response did not include image data")

        metadata["used"] = True
        metadata["output_name"] = output_path.name
        return str(output_path), metadata
    except Exception as exc:
        logger.warning("OpenAI bead image enhancement failed; using original image: %s", exc)
        metadata.update(_provider_error_metadata(exc))
        return image_path, metadata
