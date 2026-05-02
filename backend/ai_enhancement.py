import base64
import logging
import os
from pathlib import Path
from urllib.request import urlopen

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
    return {
        "error_type": "provider_error",
        "reason": raw,
    }


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
        metadata["reason"] = "disabled"
        return image_path, metadata

    if not os.getenv("OPENAI_API_KEY"):
        metadata["reason"] = "OPENAI_API_KEY is not set"
        return image_path, metadata

    try:
        from openai import OpenAI
    except ImportError:
        metadata["reason"] = "openai package is not installed"
        return image_path, metadata

    try:
        base_url = os.getenv("OPENAI_BASE_URL") or None
        timeout = float(os.getenv("OPENAI_REQUEST_TIMEOUT", "45"))
        client = OpenAI(base_url=base_url, timeout=timeout) if base_url else OpenAI(timeout=timeout)
        model = metadata["model"]
        output_path = Path(workdir) / "ai_enhanced.png"

        params = {
            "model": model,
            "image": open(image_path, "rb"),
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
