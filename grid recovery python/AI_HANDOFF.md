# AI Handoff: Image Processing Python Files

## Purpose

This project contains the Python-side image processing pipeline for converting a source image into structured grid data. The main use case is reading a grid-based image, extracting cells, colors, and symbols, and exporting the result in a machine-friendly format for web or API consumers.

The codebase supports multiple conversion methods. These methods are used to generate alternative outputs, compare extraction quality, and provide review-friendly artifacts rather than relying on a single pass.

## High-Level Flow

1. Accept an image from either a local file path or a remote URL.
2. Create or resolve a working directory.
3. Run the core grid-recovery pipeline.
4. Generate multiple output variants and artifact files.
5. Convert those outputs into a structured payload for downstream consumers.
6. Optionally expose the pipeline through a FastAPI endpoint.

## Main Files

### `grid_recovery.py`

This is the core processing engine.

Responsibilities:
- Detect the grid layout from the image.
- Estimate rows, columns, line positions, and cell size.
- Extract cell regions from the detected grid.
- Detect and interpret legend entries.
- Use OCR to read symbols and labels.
- Classify cell content, colors, confidence, and review flags.
- Generate multiple conversion outputs and artifact files.

Key implementation details:
- Uses `OpenCV` for image preprocessing, thresholding, morphology, connected components, and clustering.
- Uses `pytesseract` for OCR.
- Uses `NumPy` for array operations and layout analysis.
- Uses `Pillow` for rendering or output image generation where needed.

Important entry points:
- `generate_reference_outputs(image_path, output_root)`
- `generate_web_result(image_path, workdir)`

### `grid_web_export.py`

This file converts generated CSV/artifact outputs into a structured export payload.

Responsibilities:
- Read processed cell CSV data.
- Read legend CSV data.
- Build metadata for generated artifacts.
- Return a clean dictionary payload containing:
  - image metadata
  - grid size
  - cells
  - legend
  - artifact references

This is the formatting layer between raw processing outputs and API/web consumers.

### `services/processor/processor_service.py`

This is the service orchestration layer.

Responsibilities:
- Validate the request shape.
- Accept `image_path` or `image_url`.
- Resolve the source image.
- Call the processing/export pipeline.
- Return a typed response object.

Important models:
- `ProcessRequest`
- `ProcessResponse`

Important function:
- `process_image(request)`

### `services/processor/blob_client.py`

Utility layer for input handling.

Responsibilities:
- Create a working directory if needed.
- Download a source image when the input is a URL.

Important functions:
- `ensure_workdir(workdir=None)`
- `download_image_url(image_url, workdir)`

### `services/processor/web_export.py`

Thin adapter between the service layer and the top-level processing module.

Responsibility:
- Load the repository processing module dynamically and call it.

Important function:
- `build_grid_payload(image_path, workdir)`

### `services/processor/_repo_imports.py`

Dynamic module loader.

Responsibility:
- Load top-level repository modules, especially `grid_recovery.py`, from inside the service package.

This exists so the service package can call the copied processing script without tightly coupling import paths.

### `services/processor/app.py`

FastAPI wrapper.

Responsibilities:
- Expose `GET /health`
- Expose `POST /process`
- Optionally enforce a shared-secret header

This is the HTTP integration layer, not the processing logic itself.

## Conversion Methods

The project is designed around multiple conversion methods rather than a single extraction path.

Current behavior:
- The core processor generates several output variants under separate approach folders.
- These are typically referred to as:
  - `approach_1`
  - `approach_2`
  - `approach_3`

Why this matters:
- Different methods can perform better on different image qualities or symbol styles.
- Separate outputs make review and comparison easier.
- One method can be used for final export while others provide diagnostics or fallback references.

Practical interpretation:
- Treat the pipeline as a multi-approach conversion system.
- Do not assume only one output representation is authoritative without checking how downstream consumers select artifacts.

## Input and Output Contract

### Accepted Inputs

The service layer accepts one of:
- `image_path`: path to a local image file
- `image_url`: remote image URL to download first

Optional:
- `workdir`: directory where temporary and generated outputs should be stored

### Output Shape

The final structured payload contains:
- `image`
- `rows`
- `cols`
- `cells`
- `legend`
- `artifacts`

`cells` typically include:
- row/column coordinates
- symbol
- color
- confidence
- cluster information
- review flags

`artifacts` include metadata for generated files from each conversion approach.

## Dependencies

This code expects these Python libraries:
- `opencv-python` / `cv2`
- `numpy`
- `pytesseract`
- `Pillow`
- `fastapi`
- `pydantic`

Non-Python dependency:
- Tesseract OCR must be installed and available to `pytesseract`.

## What Another AI Should Know

- The real processing logic is in `grid_recovery.py`.
- The `services/processor` package is mostly orchestration and API wrapping.
- The system is intentionally multi-method and output-oriented.
- The exported payload is built from generated artifact files, not from a purely in-memory representation.
- If changing extraction behavior, start in `grid_recovery.py`.
- If changing response shape, start in `grid_web_export.py` and `processor_service.py`.
- If changing input transport or API behavior, start in `blob_client.py` or `app.py`.

## Recommended Mental Model

Think of this project as three layers:

1. `Core extraction`
   `grid_recovery.py`

2. `Payload conversion`
   `grid_web_export.py`
   `services/processor/web_export.py`

3. `Service/API wrapper`
   `services/processor/processor_service.py`
   `services/processor/blob_client.py`
   `services/processor/app.py`

That separation is the fastest way to navigate the code.
