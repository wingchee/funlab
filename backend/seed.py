import json
import math

import models
from database import engine
from sqlalchemy.orm import Session

BEAD_PALETTE = [
    {"id": "B001", "name": "Cherry Red",    "hex": "#CC2936"},
    {"id": "B002", "name": "Sky Blue",       "hex": "#4A90D9"},
    {"id": "B003", "name": "Lemon Yellow",   "hex": "#F5C518"},
    {"id": "B004", "name": "Forest Green",   "hex": "#2E7D32"},
    {"id": "B005", "name": "Pure White",     "hex": "#F5F5F0"},
    {"id": "B006", "name": "Jet Black",      "hex": "#1C1C1E"},
    {"id": "B007", "name": "Peach",          "hex": "#FFAB76"},
    {"id": "B008", "name": "Lavender",       "hex": "#9B72CF"},
    {"id": "B009", "name": "Coral",          "hex": "#FF6B6B"},
    {"id": "B010", "name": "Teal",           "hex": "#26A69A"},
]

DEMO_PATTERNS = [
    {"title": "Super Mushroom", "tags": ["Nintendo", "Game", "Character"], "size": "Small",  "grid_w": 16, "grid_h": 16, "preview_color": "#CC2936", "s": 0, "e": 6},
    {"title": "Pixel Cat",      "tags": ["Animal", "Cute"],                "size": "Medium", "grid_w": 24, "grid_h": 24, "preview_color": "#F5C518", "s": 2, "e": 8},
    {"title": "Sakura Branch",  "tags": ["Nature", "Floral"],              "size": "Large",  "grid_w": 32, "grid_h": 32, "preview_color": "#FFAB76", "s": 4, "e": 9},
    {"title": "Pikachu",        "tags": ["Nintendo", "Anime", "Character"],"size": "Medium", "grid_w": 24, "grid_h": 24, "preview_color": "#F5C518", "s": 1, "e": 7},
    {"title": "Rainbow Star",   "tags": ["Abstract", "Star"],              "size": "Small",  "grid_w": 16, "grid_h": 16, "preview_color": "#9B72CF", "s": 0, "e": 7},
    {"title": "Totoro",         "tags": ["Anime", "Character"],            "size": "Large",  "grid_w": 32, "grid_h": 32, "preview_color": "#2E7D32", "s": 3, "e": 9},
    {"title": "Sunset Waves",   "tags": ["Abstract", "Landscape"],         "size": "Medium", "grid_w": 24, "grid_h": 24, "preview_color": "#FF6B6B", "s": 0, "e": 5},
    {"title": "Pixel Heart",    "tags": ["Love", "Simple"],                "size": "Small",  "grid_w": 12, "grid_h": 12, "preview_color": "#CC2936", "s": 0, "e": 4},
]


def _generate_grid(w: int, h: int, palette: list) -> list:
    return [
        [palette[int((math.sin(x * 0.7 + y * 0.5) * 0.5 + 0.5) * len(palette)) % len(palette)]["id"]
         for x in range(w)]
        for y in range(h)
    ]


def seed_demo_data() -> None:
    with Session(engine) as db:
        if db.query(models.Pattern).count() > 0:
            return
        for p in DEMO_PATTERNS:
            palette = BEAD_PALETTE[p["s"]:p["e"]]
            db.add(models.Pattern(
                title=p["title"],
                tags=json.dumps(p["tags"]),
                size=p["size"],
                grid_w=p["grid_w"],
                grid_h=p["grid_h"],
                faves_count=0,
                preview_color=p["preview_color"],
                palette=json.dumps(palette),
                grid_data=json.dumps(_generate_grid(p["grid_w"], p["grid_h"], palette)),
            ))
        db.commit()
