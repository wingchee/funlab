import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import grid_recovery as gr  # noqa: E402


def _cell(row: int, col: int, color_bgr: tuple[int, int, int]) -> gr.CellRecord:
    return gr.CellRecord(
        row=row,
        col=col,
        bbox=(0, 0, 1, 1),
        color_bgr=color_bgr,
        color_hex="#{:02X}{:02X}{:02X}".format(color_bgr[2], color_bgr[1], color_bgr[0]),
        is_empty=False,
        raw_symbol="",
        raw_confidence=0.0,
    )


def test_cluster_cells_assigns_every_non_empty_cell_to_a_cluster():
    cells = [
        _cell(1, 1, (10, 10, 10)),
        _cell(1, 2, (12, 10, 10)),
        _cell(2, 1, (240, 240, 240)),
        _cell(2, 2, (242, 240, 240)),
    ]

    gr._cluster_cells(cells, max_k=2)

    assert all(cell.cluster_id >= 0 for cell in cells)
    assert len({cell.cluster_id for cell in cells}) == 2


def test_derive_legend_entries_from_clusters_uses_cluster_colors_when_footer_legend_is_missing():
    cells = [
        _cell(1, 1, (10, 20, 30)),
        _cell(1, 2, (10, 20, 30)),
        _cell(2, 1, (70, 80, 90)),
    ]
    cells[0].cluster_id = 3
    cells[1].cluster_id = 3
    cells[2].cluster_id = 8

    entries = gr._derive_legend_entries_from_clusters(cells)

    assert [(entry.symbol, entry.color_bgr, entry.confidence) for entry in entries] == [
        ("C03", (10, 20, 30), 0.25),
        ("C08", (70, 80, 90), 0.25),
    ]


def test_apply_border_label_counts_corrects_missing_leading_line_and_footer_lines():
    layout = gr.GridLayout(
        left=0,
        top=0,
        width=140,
        height=220,
        cell_size=20,
        rows=5,
        cols=3,
        x_lines=[40, 60, 80, 100],
        y_lines=[100, 120, 140, 160, 180, 200],
    )
    counts = gr.BorderLabelCounts(
        rows=3,
        cols=4,
        first_row_center_y=90.0,
        last_row_center_y=150.0,
    )

    corrected = gr._apply_border_label_counts(layout, counts)

    assert corrected.cols == 4
    assert corrected.x_lines == [20, 40, 60, 80, 100]
    assert corrected.rows == 3
    assert corrected.y_lines == [80, 100, 120, 140]


def test_choose_legend_entries_uses_cluster_fallback_for_partial_low_confidence_footer():
    extracted = [
        gr.LegendEntry("S1", (1, 1, 1), (0, 0, 1, 1), 0.05),
        gr.LegendEntry("S2", (2, 2, 2), (0, 0, 1, 1), 0.05),
        gr.LegendEntry("S3", (3, 3, 3), (0, 0, 1, 1), 0.05),
        gr.LegendEntry("S4", (4, 4, 4), (0, 0, 1, 1), 0.05),
        gr.LegendEntry("1", (5, 5, 5), (0, 0, 1, 1), 0.21),
    ]
    clustered = [
        gr.LegendEntry(f"C{i:02d}", (i, i, i), (0, 0, 0, 0), 0.25)
        for i in range(8)
    ]

    assert gr._choose_legend_entries(extracted, clustered) == clustered
