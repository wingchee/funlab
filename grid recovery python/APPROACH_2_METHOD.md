# Approach 2 Method Handoff

## Purpose

`approach_2` is the clean, legend-constrained grid recovery method used by this project.

Its goal is to convert a chart image into:

- a reconstructed preview image
- a machine-readable cell grid CSV
- a recovered legend CSV

The key rule is:

> Non-empty grid cells must be assigned symbols from the recovered legend, not from raw per-cell OCR.

This makes `approach_2` more stable than direct OCR because blurry or tiny cell symbols are not treated as the final authority. OCR is used mainly to recover legend labels and seed diagnostic information.

## Main Source Files

- `grid_recovery.py`
  Core image processing and artifact generation.

- `grid_web_export.py`
  Reads generated artifacts into a web/API payload. It treats `approach_2/legend.csv` as the legend source.

Primary entry point:

```python
from pathlib import Path
import grid_recovery

grid_recovery.generate_reference_outputs(
    Path("blur.JPG"),
    Path("outputs"),
)
```

For `doraemon.jpeg`:

```python
from pathlib import Path
import grid_recovery

grid_recovery.generate_reference_outputs(
    Path("doraemon.jpeg"),
    Path("outputs_doraemon"),
)
```

## Approach 2 Output Files

For an output root such as `outputs`, `approach_2` writes:

```text
outputs/approach_2/preview.png
outputs/approach_2/grid.csv
outputs/approach_2/legend.csv
```

For `doraemon.jpeg`, the equivalent path is:

```text
outputs_doraemon/approach_2/preview.png
outputs_doraemon/approach_2/grid.csv
outputs_doraemon/approach_2/legend.csv
```

## High-Level Algorithm

1. Read the source image with OpenCV.
2. Detect the grid layout.
3. Recover legend entries from the footer/legend area.
4. Extract every grid cell and estimate its dominant color.
5. Cluster non-empty cell colors.
6. Run limited OCR on sample cells for diagnostics/seeding.
7. For `approach_2`, ignore final raw OCR symbols and assign each non-empty cell to the nearest recovered legend color.
8. Render `preview.png`.
9. Write `grid.csv`.
10. Write `legend.csv`.

## Detailed Recreation Steps

### 1. Load Image

Use:

```python
image = cv2.imread(str(image_path))
```

Fail if OpenCV cannot read the image.

### 2. Detect Grid Layout

Use `detect_grid_layout(image)`.

This function:

- converts the image to grayscale
- applies adaptive thresholding
- extracts horizontal and vertical grid lines with morphology
- finds the bounding box of the grid region
- estimates cell size from line projection spacing
- refines vertical and horizontal line locations
- trims trailing irregular lines so footer content is not treated as grid rows

The result is a `GridLayout` with:

- `left`
- `top`
- `width`
- `height`
- `cell_size`
- `rows`
- `cols`
- `x_lines`
- `y_lines`

### 3. Recover Legend Entries

Use:

```python
legend_entries = extract_legend_entries(image, layout)
legend_table = build_legend_table(legend_entries)
```

Each `LegendEntry` contains:

- `symbol`
- `color_bgr`
- `bbox`
- `confidence`

`build_legend_table` deduplicates entries by symbol and keeps the highest-confidence entry for each symbol.

The pipeline has two legend recovery paths.

#### Structured Footer Path

This path is attempted first.

It is designed for images like `doraemon.jpeg`, where the footer has large, evenly spaced legend slots below the grid.

It does the following:

- crops an expanded band below the grid
- detects non-white or saturated connected components as swatches
- infers evenly spaced slot centers
- inserts a leading slot if the first item appears to be text-only
- OCRs each slot label with several crop/threshold/PSM variants
- normalizes common OCR digit confusions
- samples the swatch color, or uses the slot background when no swatch exists

Important OCR normalization examples:

```text
O -> 0
D -> 0
Q -> 9
Y -> 9
Z -> 2
S -> 5
B -> 8
```

For `doraemon.jpeg`, this should recover symbols like:

```text
H2, H6, C24, F24, F9, F14, A22
```

#### Fallback Footer OCR Path

If the structured footer path does not produce enough entries, the code falls back to the older footer parser.

That path:

- crops a smaller footer band below the grid
- detects saturated swatch regions
- OCRs labels near swatches
- uses placeholder symbols only when OCR cannot produce usable labels
- samples colors from the swatch or nearby area

There is a final fallback that OCRs the lower part of the detected grid/legend band when footer parsing produces no entries.

### 4. Extract Cells

Use:

```python
base_cells = _extract_cells(image, layout)
```

For every row/column cell in the detected grid:

- crop the cell from the grid area
- remove a 1-pixel border when possible
- compute the median BGR color
- convert it to `#RRGGBB`
- mark it empty if HSV saturation is low and brightness is high

The empty-cell rule is:

```python
is_empty = hsv_saturation < 28 and hsv_value > 200
```

Each cell is represented as a `CellRecord` with:

- `row`
- `col`
- `bbox`
- `color_bgr`
- `color_hex`
- `is_empty`
- `raw_symbol`
- `raw_confidence`
- `symbol`
- `confidence`
- `cluster_id`
- `needs_review`
- `high_risk`

### 5. Cluster Cell Colors

Use:

```python
_cluster_cells(base_cells)
```

Only non-empty cells are clustered.

The implementation uses OpenCV k-means:

- maximum cluster count: `14`
- lower bound: `2`
- actual `k`: min of max cluster count and unique color count
- criteria: EPS + max iterations
- attempts: `5`
- initialization: `cv2.KMEANS_PP_CENTERS`

After clustering, each colored cell gets:

- `cluster_id`
- updated cluster-center `color_bgr`
- updated cluster-center `color_hex`

### 6. Seed OCR For Clusters

Use:

```python
_seed_ocr_for_clusters(image, layout, base_cells)
```

This OCR pass samples up to six cells per color cluster, prioritizing cells near the grid center.

It uses several threshold variants and Tesseract with:

```text
--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789
```

For `approach_2`, this raw OCR is not the final symbol source. It is still run because the shared generation pipeline uses it for other approaches and diagnostics.

### 7. Assign Symbols From Legend

This is the defining step of `approach_2`.

Use:

```python
assign_cells_from_legend(cells, legend_table)
```

Behavior:

- if a cell is empty:
  - `symbol = ""`
  - `confidence = 1.0`
- if a cell is non-empty:
  - compute Euclidean distance between the cell BGR color and every legend BGR color
  - select the nearest legend entry
  - set `cell.symbol = nearest.symbol`
  - set confidence from normalized color distance

Confidence formula:

```python
distance = math.dist(cell.color_bgr, nearest.color_bgr)
confidence = max(0.0, 1.0 - distance / (255.0 * math.sqrt(3)))
```

This means the final `approach_2` cell symbols are constrained to the legend symbols. The method fails closed if the legend is empty:

```python
raise ValueError("legend-constrained assignment requires at least one legend entry")
```

### 8. Render Preview

Use:

```python
_render_preview(layout, cells, preview_path, show_review=False)
```

For `approach_2`, `show_review` is false.

The preview:

- creates a white canvas
- draws every cell using its recovered color
- centers the assigned symbol inside the cell
- chooses black or white symbol text based on fill luminance
- draws grid lines
- draws row and column indexes

### 9. Write Grid CSV

Use:

```python
_write_csv(cells, csv_path, include_review=False)
```

`approach_2/grid.csv` columns:

```text
row,col,symbol,color_hex,cluster_id,empty,confidence
```

Notes:

- `row` and `col` are 1-based.
- `empty` is `1` or `0`.
- `confidence` is formatted to three decimals.
- no `needs_review` column is written for `approach_2`.

### 10. Write Legend CSV

Use:

```python
write_legend_csv(legend_entries, variant_dir / "legend.csv")
```

`approach_2/legend.csv` columns:

```text
symbol,color_hex,confidence,x1,y1,x2,y2
```

Notes:

- `color_hex` is converted from stored BGR to RGB hex.
- bounding boxes use image coordinates.
- duplicate symbols may appear in the raw legend CSV because `legend.csv` writes `legend_entries`, not the deduplicated `legend_table`.
- final cell assignment uses the deduplicated `legend_table`.

## Minimal Pseudocode

```python
def recreate_approach_2(image_path, output_root):
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)

    layout = detect_grid_layout(image)
    legend_entries = extract_legend_entries(image, layout)
    legend_table = build_legend_table(legend_entries)

    cells = _extract_cells(image, layout)
    _cluster_cells(cells)
    _seed_ocr_for_clusters(image, layout, cells)

    approach_dir = Path(output_root) / "approach_2"
    assign_cells_from_legend(cells, legend_table)

    _render_preview(layout, cells, approach_dir / "preview.png", show_review=False)
    _write_csv(cells, approach_dir / "grid.csv", include_review=False)
    write_legend_csv(legend_entries, approach_dir / "legend.csv")
```

## Difference From Other Approaches

`approach_1`:

- direct baseline
- uses raw cell OCR where available
- does not write `legend.csv`
- does not constrain final symbols to legend colors

`approach_2`:

- main clean output
- final symbols come from nearest legend color
- writes `legend.csv`
- no review flags in `grid.csv`

`approach_3`:

- review-oriented variant
- starts from legend-constrained assignment
- applies high-risk smoothing
- writes `needs_review`
- highlights review cells in the preview
- does not write its own `legend.csv`

## Validation Checks

Run:

```bash
python3 -m pytest -q tests/test_grid_recovery.py
```

Important regression expectations:

- `generate_reference_outputs` writes `approach_1`, `approach_2`, and `approach_3`.
- `approach_2` writes `preview.png`, `grid.csv`, and `legend.csv`.
- final symbols in `approach_2/grid.csv` are a subset of symbols in `approach_2/legend.csv`.
- missing legends raise an error for legend-constrained output.
- `doraemon.jpeg` legend extraction includes:

```text
H2, H6, C24, F24, F9, F14, A22
```

## Dependencies

Python packages:

- `opencv-python` / `cv2`
- `numpy`
- `pytesseract`
- `Pillow`
- `pytest` for tests

System dependency:

- Tesseract OCR must be installed and discoverable by `pytesseract`.

## Practical Notes For Another AI

- Start with `generate_reference_outputs` in `grid_recovery.py`.
- Recreate `approach_2` exactly by preserving the legend-constrained assignment rule.
- Do not use `clear.JPG` as a source of truth for chart content. It is only a visual reference.
- Do not replace final `approach_2` symbols with raw cell OCR; raw cell OCR is unreliable on blurry cells.
- Keep footer/legend extraction authoritative when it succeeds.
- If adapting to a new image style, update legend extraction first, then verify that final cell symbols remain a subset of the legend.
