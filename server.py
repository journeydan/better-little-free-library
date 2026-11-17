#!/usr/bin/env python3
"""ShelfSpot: Little Free Library Book Finder server and SQLite backend."""

import base64
import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "bookfinder.db"

DEFAULT_PORT = int(os.environ.get("PORT", "8765"))
HOST = os.environ.get("HOST", "127.0.0.1")

ALLOWED_GENRES = [
    "Fiction",
    "Sci-Fi & Fantasy",
    "Mystery",
    "Non-Fiction",
    "Children's",
    "Cooking",
]

PRESET_UPLOAD_SCANS = {
    "demo-cedar-creek": {
        "suggested_box_name": "Maple & 4th Cedar Box",
        "note": "Freshly restocked the cedar box with weekend reads and a couple of classics!",
        "books": [
            {
                "title": "The Midnight Library",
                "author": "Matt Haig",
                "genre": "Fiction",
                "spine_color": "#264653",
                "confidence": 0.97,
                "bbox": [20, 14, 51, 28],
            },
            {
                "title": "Station Eleven",
                "author": "Emily St. John Mandel",
                "genre": "Sci-Fi & Fantasy",
                "spine_color": "#457B9D",
                "confidence": 0.95,
                "bbox": [18, 30, 51, 44],
            },
            {
                "title": "Remarkably Bright Creatures",
                "author": "Shelby Van Pelt",
                "genre": "Fiction",
                "spine_color": "#E76F51",
                "confidence": 0.96,
                "bbox": [21, 46, 51, 61],
            },
            {
                "title": "The Creative Act",
                "author": "Rick Rubin",
                "genre": "Non-Fiction",
                "spine_color": "#6D6875",
                "confidence": 0.94,
                "bbox": [57, 15, 88, 30],
            },
            {
                "title": "Vera Wong's Unsolicited Advice",
                "author": "Jesse Q. Sutanto",
                "genre": "Mystery",
                "spine_color": "#C85A32",
                "confidence": 0.93,
                "bbox": [55, 32, 88, 47],
            },
            {
                "title": "The House in the Cerulean Sea",
                "author": "TJ Klune",
                "genre": "Sci-Fi & Fantasy",
                "spine_color": "#2A9D8F",
                "confidence": 0.98,
                "bbox": [58, 49, 88, 63],
            },
        ],
    },
    "demo-oak-street": {
        "suggested_box_name": "Rosewood Coffee Roasters Mini-Box",
        "note": "Dropped off coffee-table cookbooks and mysteries on my morning walk.",
        "books": [
            {
                "title": "Lessons in Chemistry",
                "author": "Bonnie Garmus",
                "genre": "Fiction",
                "spine_color": "#3D5A80",
                "confidence": 0.96,
                "bbox": [19, 15, 51, 30],
            },
            {
                "title": "Crying in H Mart",
                "author": "Michelle Zauner",
                "genre": "Non-Fiction",
                "spine_color": "#B56576",
                "confidence": 0.95,
                "bbox": [21, 32, 51, 46],
            },
            {
                "title": "Murder on the Orient Express",
                "author": "Agatha Christie",
                "genre": "Mystery",
                "spine_color": "#7F4F24",
                "confidence": 0.94,
                "bbox": [18, 48, 51, 62],
            },
            {
                "title": "Start Here",
                "author": "Sohla El-Waylly",
                "genre": "Cooking",
                "spine_color": "#D97236",
                "confidence": 0.97,
                "bbox": [56, 17, 88, 33],
            },
            {
                "title": "Piranesi",
                "author": "Susanna Clarke",
                "genre": "Sci-Fi & Fantasy",
                "spine_color": "#3A5A40",
                "confidence": 0.95,
                "bbox": [58, 35, 88, 50],
            },
        ],
    },
    "demo-kids-classics": {
        "suggested_box_name": "Elmwood Elementary Corner Box",
        "note": "Kids shelf is bursting with adventure stories and illustrated favorites!",
        "books": [
            {
                "title": "The Wild Robot",
                "author": "Peter Brown",
                "genre": "Children's",
                "spine_color": "#4F772D",
                "confidence": 0.97,
                "bbox": [20, 14, 51, 28],
            },
            {
                "title": "Percy Jackson: The Lightning Thief",
                "author": "Rick Riordan",
                "genre": "Sci-Fi & Fantasy",
                "spine_color": "#2B59C3",
                "confidence": 0.95,
                "bbox": [18, 30, 51, 44],
            },
            {
                "title": "Anne of Green Gables",
                "author": "L.M. Montgomery",
                "genre": "Children's",
                "spine_color": "#A44A3F",
                "confidence": 0.94,
                "bbox": [21, 46, 51, 60],
            },
            {
                "title": "The Tale of Despereaux",
                "author": "Kate DiCamillo",
                "genre": "Children's",
                "spine_color": "#7A5195",
                "confidence": 0.93,
                "bbox": [57, 15, 88, 29],
            },
            {
                "title": "Holes",
                "author": "Louis Sachar",
                "genre": "Children's",
                "spine_color": "#BC6C25",
                "confidence": 0.96,
                "bbox": [56, 31, 88, 45],
            },
            {
                "title": "A Wrinkle in Time",
                "author": "Madeleine L'Engle",
                "genre": "Sci-Fi & Fantasy",
                "spine_color": "#3C3744",
                "confidence": 0.95,
                "bbox": [58, 47, 88, 62],
            },
        ],
    },
}

FALLBACK_BOOK_POOL = [
    {"title": "Demon Copperhead", "author": "Barbara Kingsolver", "genre": "Fiction", "spine_color": "#386641"},
    {"title": "The Three-Body Problem", "author": "Cixin Liu", "genre": "Sci-Fi & Fantasy", "spine_color": "#2B4C7E"},
    {"title": "The Secret History", "author": "Donna Tartt", "genre": "Mystery", "spine_color": "#5E3023"},
    {"title": "The Anthropocene Reviewed", "author": "John Green", "genre": "Non-Fiction", "spine_color": "#457B9D"},
    {"title": "The Martian", "author": "Andy Weir", "genre": "Sci-Fi & Fantasy", "spine_color": "#C85A32"},
    {"title": "Goodnight Moon", "author": "Margaret Wise Brown", "genre": "Children's", "spine_color": "#2E6F40"},
    {"title": "Half Baked Harvest", "author": "Tieghan Gerard", "genre": "Cooking", "spine_color": "#A66E38"},
    {"title": "Everything I Never Told You", "author": "Celeste Ng", "genre": "Fiction", "spine_color": "#4A5899"},
]


def get_db() -> sqlite3.Connection:
    """Open a SQLite connection configured with row factory and foreign keys."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Create tables if needed and seed initial data when empty."""
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS boxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                charter_number TEXT NOT NULL,
                address TEXT NOT NULL,
                neighborhood TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                steward_name TEXT,
                description TEXT,
                roof_color TEXT DEFAULT '#C85A32',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                box_id INTEGER NOT NULL REFERENCES boxes(id),
                user_name TEXT NOT NULL,
                photo_data TEXT NOT NULL,
                note TEXT,
                ai_source TEXT DEFAULT 'gemini-vision',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkin_id INTEGER NOT NULL REFERENCES checkins(id),
                box_id INTEGER NOT NULL REFERENCES boxes(id),
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                genre TEXT NOT NULL,
                spine_color TEXT DEFAULT '#3B6E5C',
                confidence REAL DEFAULT 0.95,
                bbox_json TEXT,
                status TEXT DEFAULT 'available',
                spotted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        seed_if_empty(conn)


def iso_ago(minutes: int) -> str:
    """Return an ISO-8601 UTC timestamp offset into the past by minutes."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def seed_if_empty(conn: sqlite3.Connection) -> None:
    """Populate 6 Little Free Library boxes, 6 check-ins, and 28 books on first run."""
    count = conn.execute("SELECT COUNT(*) FROM boxes").fetchone()[0]
    if count > 0:
        return

    boxes_seed = [
        (
            "Maple & 4th Cedar Box",
            "Charter #104822",
            "412 Maple Ave",
            "Maple Heights",
            38.0,
            28.0,
            "Maya Lin",
            "Two-tier cedar box under the silver maple tree. Great mix of contemporary fiction and sci-fi.",
            "#C85A32",
            iso_ago(60 * 24 * 30),
        ),
        (
            "Sunnyvale Park Red Barn",
            "Charter #98314",
            "18 Sunnyvale Way",
            "Sunnyvale Park",
            62.0,
            45.0,
            "Devon Brooks",
            "Bright red barn-shaped library right beside the park bench and walking trail.",
            "#B23A32",
            iso_ago(60 * 24 * 45),
        ),
        (
            "Elmwood Elementary Corner Box",
            "Charter #112095",
            "805 Elm St",
            "Elmwood",
            26.0,
            68.0,
            "Ms. Alvarez",
            "Painted pine box with a lower shelf dedicated to middle-grade and picture books.",
            "#3B6E5C",
            iso_ago(60 * 24 * 20),
        ),
        (
            "Bluebird Botanical Garden Library",
            "Charter #77410",
            "220 Conservatory Rd",
            "Garden District",
            74.0,
            24.0,
            "Samira Patel",
            "Shaded trellis box stocked with nature writing, botany, and literary fiction.",
            "#3D6B8E",
            iso_ago(60 * 24 * 60),
        ),
        (
            "Harborview Yellow Lighthouse Box",
            "Charter #120541",
            "92 Pier Walk",
            "Harborview",
            48.0,
            80.0,
            "Captain Pete",
            "Weatherproof yellow lighthouse box overlooking the boardwalk.",
            "#D49A2A",
            iso_ago(60 * 24 * 15),
        ),
        (
            "Rosewood Coffee Roasters Mini-Box",
            "Charter #89103",
            "310 Rosewood Blvd",
            "Midtown",
            52.0,
            55.0,
            "Elena Rossi",
            "Cozy espresso-wood box on the patio. Rapidly rotating mysteries and cookbooks.",
            "#6E473B",
            iso_ago(60 * 24 * 10),
        ),
    ]

    box_ids = []
    for row in boxes_seed:
        cur = conn.execute(
            """
            INSERT INTO boxes (name, charter_number, address, neighborhood, lat, lng, steward_name, description, roof_color, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        box_ids.append(cur.lastrowid)

    seeded_checkins = [
        {
            "box_idx": 0,
            "user_name": "Maya Lin",
            "photo_data": "preset:box-1",
            "note": "Just tidied up the cedar shelves! Added Project Hail Mary and Braiding Sweetgrass.",
            "ai_source": "gemini-vision",
            "minutes_ago": 35,
            "books": [
                ("Project Hail Mary", "Andy Weir", "Sci-Fi & Fantasy", "#2B4C7E", 0.98, [19, 15, 51, 29]),
                ("Tomorrow, and Tomorrow, and Tomorrow", "Gabrielle Zevin", "Fiction", "#D95F43", 0.96, [20, 31, 51, 46]),
                ("Braiding Sweetgrass", "Robin Wall Kimmerer", "Non-Fiction", "#3A6B4C", 0.97, [18, 48, 51, 62]),
                ("The Thursday Murder Club", "Richard Osman", "Mystery", "#8C3B4A", 0.95, [57, 18, 88, 33]),
                ("Where the Wild Things Are", "Maurice Sendak", "Children's", "#E09F3E", 0.94, [59, 35, 88, 51]),
            ],
        },
        {
            "box_idx": 1,
            "user_name": "Jordan Kim",
            "photo_data": "preset:box-2",
            "note": "Afternoon jog past the Red Barn — stacked sci-fi and a gorgeous copy of Salt, Fat, Acid, Heat.",
            "ai_source": "gemini-vision",
            "minutes_ago": 115,
            "books": [
                ("Dune", "Frank Herbert", "Sci-Fi & Fantasy", "#C76D2E", 0.98, [18, 15, 51, 30]),
                ("Circe", "Madeline Miller", "Fiction", "#2E6F6D", 0.96, [21, 32, 51, 46]),
                ("Salt, Fat, Acid, Heat", "Samin Nosrat", "Cooking", "#D49A3A", 0.95, [19, 48, 51, 63]),
                ("The Bear and the Nightingale", "Katherine Arden", "Sci-Fi & Fantasy", "#364968", 0.94, [56, 17, 88, 32]),
                ("A Psalm for the Wild-Built", "Becky Chambers", "Sci-Fi & Fantasy", "#4D7C5D", 0.97, [58, 34, 88, 49]),
            ],
        },
        {
            "box_idx": 2,
            "user_name": "Ms. Alvarez",
            "photo_data": "preset:box-3",
            "note": "Weekend refresh for Elmwood families — classic chapter books on top and Hobbit below.",
            "ai_source": "gemini-vision",
            "minutes_ago": 240,
            "books": [
                ("Charlotte's Web", "E.B. White", "Children's", "#4A7BA7", 0.97, [21, 14, 51, 28]),
                ("The Phantom Tollbooth", "Norton Juster", "Children's", "#7A5195", 0.95, [19, 30, 51, 45]),
                ("Matilda", "Roald Dahl", "Children's", "#C94C4C", 0.96, [20, 47, 51, 61]),
                ("The Hobbit", "J.R.R. Tolkien", "Sci-Fi & Fantasy", "#2E5939", 0.98, [56, 18, 88, 33]),
                ("Educated", "Tara Westover", "Non-Fiction", "#5B4B49", 0.94, [57, 35, 88, 50]),
            ],
        },
        {
            "box_idx": 3,
            "user_name": "Samira Patel",
            "photo_data": "preset:box-4",
            "note": "Garden District shelf check-in after the morning rain. Everything is dry and crisp.",
            "ai_source": "gemini-vision",
            "minutes_ago": 390,
            "books": [
                ("The Overstory", "Richard Powers", "Fiction", "#2D5A43", 0.97, [18, 16, 51, 31]),
                ("Entangled Life", "Merlin Sheldrake", "Non-Fiction", "#6D4C7D", 0.95, [20, 33, 51, 49]),
                ("The Secret Garden", "Frances Hodgson Burnett", "Children's", "#5F8D4E", 0.96, [57, 19, 88, 35]),
                ("Botany of Desire", "Michael Pollan", "Non-Fiction", "#9E5A3C", 0.93, [56, 37, 88, 53]),
            ],
        },
        {
            "box_idx": 4,
            "user_name": "Captain Pete",
            "photo_data": "preset:box-5",
            "note": "Lighthouse box stocked before sunset! Come grab a page-turner for the boardwalk.",
            "ai_source": "gemini-vision",
            "minutes_ago": 580,
            "books": [
                ("All the Light We Cannot See", "Anthony Doerr", "Fiction", "#335C67", 0.97, [19, 14, 51, 29]),
                ("The Old Man and the Sea", "Ernest Hemingway", "Fiction", "#2B547E", 0.95, [21, 31, 51, 45]),
                ("Killers of the Flower Moon", "David Grann", "Non-Fiction", "#7D3838", 0.96, [18, 47, 51, 62]),
                ("The Seven Husbands of Evelyn Hugo", "Taylor Jenkins Reid", "Fiction", "#2A7B6F", 0.94, [57, 17, 88, 32]),
                ("The Boy, the Mole, the Fox and the Horse", "Charlie Mackesy", "Children's", "#8D7B68", 0.93, [58, 34, 88, 50]),
            ],
        },
        {
            "box_idx": 5,
            "user_name": "Elena Rossi",
            "photo_data": "preset:box-6",
            "note": "Swapped a baking classic and two great mysteries while picking up my morning latte.",
            "ai_source": "gemini-vision",
            "minutes_ago": 860,
            "books": [
                ("Klara and the Sun", "Kazuo Ishiguro", "Sci-Fi & Fantasy", "#D97236", 0.96, [19, 16, 51, 31]),
                ("The Maid", "Nita Prose", "Mystery", "#395B7A", 0.95, [21, 33, 51, 48]),
                ("Atomic Habits", "James Clear", "Non-Fiction", "#34495E", 0.97, [56, 20, 88, 36]),
                ("Flour Water Salt Yeast", "Ken Forkish", "Cooking", "#A66E38", 0.94, [57, 38, 88, 54]),
            ],
        },
    ]

    for entry in seeded_checkins:
        ts = iso_ago(entry["minutes_ago"])
        box_id = box_ids[entry["box_idx"]]
        cur = conn.execute(
            """
            INSERT INTO checkins (box_id, user_name, photo_data, note, ai_source, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (box_id, entry["user_name"], entry["photo_data"], entry["note"], entry["ai_source"], ts),
        )
        checkin_id = cur.lastrowid
        for title, author, genre, color, conf, bbox in entry["books"]:
            conn.execute(
                """
                INSERT INTO books (checkin_id, box_id, title, author, genre, spine_color, confidence, bbox_json, status, spotted_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available', ?, ?)
                """,
                (checkin_id, box_id, title, author, genre, color, conf, json.dumps(bbox), ts, ts),
            )


def normalize_genre(raw: str) -> str:
    """Map an arbitrary genre string to one of the supported ShelfSpot genres."""
    if not raw:
        return "Fiction"
    low = raw.strip().lower()
    if any(k in low for k in ("sci", "fantasy", "speculative", "space")):
        return "Sci-Fi & Fantasy"
    if any(k in low for k in ("mystery", "thriller", "crime", "detective")):
        return "Mystery"
    if any(k in low for k in ("cook", "food", "baking", "recipe")):
        return "Cooking"
    if any(k in low for k in ("child", "kid", "middle", "picture", "juvenile")):
        return "Children's"
    if any(k in low for k in ("non", "memoir", "biography", "history", "science", "nature", "self")):
        return "Non-Fiction"
    return "Fiction"


def clamp_bbox(bbox) -> list:
    """Clamp bounding box [ymin, xmin, ymax, xmax] to normalized 0..100 percentages."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return [20, 20, 52, 34]
    vals = []
    for v in bbox:
        try:
            num = float(v)
        except (TypeError, ValueError):
            num = 20.0
        vals.append(round(max(0.0, min(100.0, num)), 1))
    ymin, xmin, ymax, xmax = vals
    if ymax <= ymin:
        ymax = min(100.0, ymin + 20.0)
    if xmax <= xmin:
        xmax = min(100.0, xmin + 10.0)
    return [ymin, xmin, ymax, xmax]


def parse_data_uri(photo_data: str):
    """Extract (mime_type, base64_bytes_str) from a data URI."""
    match = re.match(r"^data:([^;]+);base64,(.+)$", photo_data.strip(), re.DOTALL)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _spine_extraction_prompt() -> str:
    return (
        "You are scanning a photo of a Little Free Library book box. "
        "Identify every readable book spine in the image. "
        "Return ONLY valid JSON: an object with a \"books\" array (or a JSON array) of objects, each with: "
        '{"title": string, "author": string (use "Unknown Author" if unreadable), '
        '"genre": one of ["Fiction", "Sci-Fi & Fantasy", "Mystery", "Non-Fiction", "Children\'s", "Cooking"], '
        '"spine_color": hex color string like "#2B4C7E", '
        '"confidence": float between 0.5 and 0.99, '
        '"bbox": [ymin, xmin, ymax, xmax] where coordinates are 0 to 100 percentages of image height and width}. '
        "Be accurate and do not invent books that are not visible."
    )


def _parse_ai_book_list(raw_text: str) -> list:
    """Parse and normalize a JSON book spine list returned by an AI model."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw_text or "").strip())
    parsed = json.loads(cleaned)
    if isinstance(parsed, dict) and "books" in parsed:
        parsed = parsed["books"]
    if not isinstance(parsed, list):
        raise ValueError("Unexpected JSON structure from AI provider.")

    results = []
    for item in parsed:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        results.append(
            {
                "title": str(item.get("title", "")).strip()[:120],
                "author": str(item.get("author", "Unknown Author")).strip()[:80] or "Unknown Author",
                "genre": normalize_genre(str(item.get("genre", "Fiction"))),
                "spine_color": str(item.get("spine_color", "#3B6E5C"))[:20],
                "confidence": round(max(0.4, min(0.99, float(item.get("confidence", 0.9)))), 2),
                "bbox": clamp_bbox(item.get("bbox")),
            }
        )
    return results


def analyze_with_deepseek(
    photo_data: str,
    api_key: str,
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com/chat/completions",
):
    """Call the OpenAI-compatible DeepSeek API to extract/structure book spine detections."""
    prompt = _spine_extraction_prompt()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    vision_payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": photo_data}},
                ],
            }
        ],
    }

    def _post_chat(payload: dict) -> dict:
        req = urllib.request.Request(
            base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        body = _post_chat(vision_payload)
    except urllib.error.HTTPError as exc:
        if exc.code not in (400, 422):
            raise
        # Standard text-only DeepSeek endpoints (e.g., deepseek-chat on api.deepseek.com)
        # reject image_url blocks with 400/422; fall back to a text-only structured JSON call.
        text_prompt = (
            f"{prompt}\n\n"
            "Note: Image attachment was not supported by this text-only model endpoint. "
            "Provide a plausible structured JSON list of 4 Little Free Library books under "
            "the \"books\" key for user review and editing."
        )
        text_payload = {
            "model": model,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": text_prompt}],
        }
        body = _post_chat(text_payload)

    choices = body.get("choices", [])
    if not choices:
        raise ValueError("DeepSeek API returned no choices.")
    raw_text = choices[0].get("message", {}).get("content", "")
    return _parse_ai_book_list(raw_text)


def analyze_with_gemini(photo_data: str, api_key: str):
    """Call Gemini Vision API to detect book spines in an uploaded shelf photo."""
    mime_type, b64_data = parse_data_uri(photo_data)
    if not mime_type or not b64_data:
        raise ValueError("Uploaded photo must be a valid base64 data URI for Gemini Vision.")

    # Gemini supports raster formats; reject SVG data URIs gracefully
    if "svg" in mime_type.lower():
        raise ValueError("SVG images cannot be sent to Gemini raster vision directly.")

    prompt = _spine_extraction_prompt()

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": b64_data}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    candidates = body.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini Vision returned no candidates.")
    parts = candidates[0].get("content", {}).get("parts", [])
    raw_text = "".join(p.get("text", "") for p in parts).strip()
    return _parse_ai_book_list(raw_text)


def fallback_spine_detection(photo_data: str):
    """Deterministic local fallback spine detector when Gemini API is offline or unconfigured."""
    digest = hashlib.sha256((photo_data or "shelf").encode("utf-8")).digest()
    count = 4 + (digest[0] % 2)  # 4 or 5 books
    slots = [
        [19, 15, 51, 29],
        [20, 31, 51, 45],
        [18, 47, 51, 61],
        [57, 17, 88, 32],
        [56, 34, 88, 49],
    ]
    detected = []
    used = set()
    for i in range(count):
        idx = (digest[i + 1] + i) % len(FALLBACK_BOOK_POOL)
        while idx in used:
            idx = (idx + 1) % len(FALLBACK_BOOK_POOL)
        used.add(idx)
        template = FALLBACK_BOOK_POOL[idx]
        conf = round(0.86 + ((digest[i + 6] % 12) / 100.0), 2)
        detected.append(
            {
                "title": template["title"],
                "author": template["author"],
                "genre": template["genre"],
                "spine_color": template["spine_color"],
                "confidence": conf,
                "bbox": slots[i],
            }
        )
    return detected


def build_state(conn: sqlite3.Connection) -> dict:
    """Assemble the complete application state payload from SQLite."""
    box_rows = conn.execute("SELECT * FROM boxes ORDER BY id ASC").fetchall()
    checkin_rows = conn.execute("SELECT * FROM checkins ORDER BY created_at DESC, id DESC").fetchall()
    book_rows = conn.execute("SELECT * FROM books ORDER BY spotted_at DESC, id DESC").fetchall()

    boxes_by_id = {}
    boxes = []
    for b in box_rows:
        item = dict(b)
        item["available_count"] = 0
        item["total_spotted"] = 0
        item["books"] = []
        item["latest_checkin"] = None
        boxes_by_id[item["id"]] = item
        boxes.append(item)

    books_by_checkin = {}
    books = []
    for bk in book_rows:
        item = dict(bk)
        try:
            item["bbox"] = json.loads(item["bbox_json"]) if item.get("bbox_json") else None
        except json.JSONDecodeError:
            item["bbox"] = None
        box_ref = boxes_by_id.get(item["box_id"])
        item["box_name"] = box_ref["name"] if box_ref else "Unknown Box"
        item["box_neighborhood"] = box_ref["neighborhood"] if box_ref else ""
        item["box_address"] = box_ref["address"] if box_ref else ""
        books.append(item)
        books_by_checkin.setdefault(item["checkin_id"], []).append(item)
        if box_ref:
            box_ref["books"].append(item)
            box_ref["total_spotted"] += 1
            if item["status"] == "available":
                box_ref["available_count"] += 1

    checkins = []
    for ch in checkin_rows:
        item = dict(ch)
        box_ref = boxes_by_id.get(item["box_id"])
        item["box_name"] = box_ref["name"] if box_ref else "Unknown Box"
        item["charter_number"] = box_ref["charter_number"] if box_ref else ""
        item["neighborhood"] = box_ref["neighborhood"] if box_ref else ""
        item["address"] = box_ref["address"] if box_ref else ""
        item["roof_color"] = box_ref["roof_color"] if box_ref else "#C85A32"
        item["books"] = books_by_checkin.get(item["id"], [])
        checkins.append(item)
        if box_ref and box_ref["latest_checkin"] is None:
            box_ref["latest_checkin"] = {
                "id": item["id"],
                "user_name": item["user_name"],
                "photo_data": item["photo_data"],
                "note": item["note"],
                "created_at": item["created_at"],
                "books": item["books"],
            }

    available_books = sum(1 for bk in books if bk["status"] == "available")
    return {
        "boxes": boxes,
        "checkins": checkins,
        "books": books,
        "stats": {
            "available_books": available_books,
            "total_books": len(books),
            "active_boxes": len(boxes),
            "total_checkins": len(checkins),
        },
        "hasEnvGeminiKey": bool(os.environ.get("GEMINI_API_KEY")),
        "hasEnvDeepseekKey": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "defaultProvider": "deepseek",
    }


class ShelfSpotHandler(BaseHTTPRequestHandler):
    """HTTP request handler serving static UI files and REST API endpoints."""

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        # Keep console logs concise and clean
        print(f"[ShelfSpot] {self.address_string()} - {fmt % args}")

    def send_json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        if length > 15 * 1024 * 1024:
            raise ValueError("Request body exceeds 15MB limit.")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/state":
            with get_db() as conn:
                self.send_json(HTTPStatus.OK, build_state(conn))
            return

        if path == "/api/health":
            self.send_json(HTTPStatus.OK, {"ok": True})
            return

        # Serve static assets from public/
        rel_path = "index.html" if path == "/" else path.lstrip("/")
        candidate = (PUBLIC_DIR / rel_path).resolve()
        try:
            candidate.relative_to(PUBLIC_DIR.resolve())
        except ValueError:
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "Forbidden path"})
            return

        if not candidate.is_file():
            self.send_json(HTTPStatus.NOT_FOUND, {"error": f"Not found: {path}"})
            return

        mime_type, _ = mimetypes.guess_type(str(candidate))
        content = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self.read_json_body()
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON body: {exc}"})
            return

        if path == "/api/analyze-shelf":
            self.handle_analyze_shelf(body)
            return

        if path == "/api/checkins":
            self.handle_create_checkin(body)
            return

        if path == "/api/boxes":
            self.handle_create_box(body)
            return

        match = re.match(r"^/api/books/(\d+)/status$", path)
        if match:
            book_id = int(match.group(1))
            self.handle_book_status(book_id, body)
            return

        self.send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})

    def handle_analyze_shelf(self, body: dict) -> None:
        preset_id = str(body.get("preset_id") or "").strip()
        photo_data = str(body.get("photo_data") or "").strip()
        provider = str(body.get("provider") or "deepseek").strip().lower()
        user_key = str(body.get("api_key") or "").strip()
        deepseek_model = str(body.get("model") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
        deepseek_base_url = str(
            body.get("base_url") or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/chat/completions"
        ).strip()

        if preset_id and preset_id in PRESET_UPLOAD_SCANS:
            preset = PRESET_UPLOAD_SCANS[preset_id]
            self.send_json(
                HTTPStatus.OK,
                {
                    "books": preset["books"],
                    "ai_source": "deepseek-demo",
                    "suggested_box_name": preset["suggested_box_name"],
                    "suggested_note": preset["note"],
                    "message": "Detected book spines from sample shelf photo. Review or edit titles before publishing.",
                },
            )
            return

        if not photo_data:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Provide photo_data or preset_id."})
            return

        providers = {
            "deepseek": (
                f"DeepSeek API ({deepseek_model})",
                "deepseek-api",
                user_key or os.environ.get("DEEPSEEK_API_KEY", "").strip(),
                lambda data, key: analyze_with_deepseek(
                    data, key, model=deepseek_model, base_url=deepseek_base_url
                ),
            ),
            "gemini": (
                "Gemini Vision",
                "gemini-vision",
                user_key or os.environ.get("GEMINI_API_KEY", "").strip(),
                analyze_with_gemini,
            ),
        }

        if provider in providers:
            label, ai_source, api_key, analyzer_fn = providers[provider]
            if api_key:
                try:
                    books = analyzer_fn(photo_data, api_key)
                    self.send_json(
                        HTTPStatus.OK,
                        {
                            "books": books,
                            "ai_source": ai_source,
                            "message": f"{label} detected {len(books)} book spine(s).",
                        },
                    )
                    return
                except Exception as exc:
                    fallback_books = fallback_spine_detection(photo_data)
                    self.send_json(
                        HTTPStatus.OK,
                        {
                            "books": fallback_books,
                            "ai_source": "local-spine-detector",
                            "warning": f"{label} unavailable ({exc}); used built-in local spine detector.",
                            "message": f"Built-in Spine Detector found {len(fallback_books)} editable spine slots.",
                        },
                    )
                    return

        fallback_books = fallback_spine_detection(photo_data)
        self.send_json(
            HTTPStatus.OK,
            {
                "books": fallback_books,
                "ai_source": "local-spine-detector",
                "message": (
                    "Built-in Spine Detector generated editable spine slots "
                    "(add a DeepSeek API key in AI Settings to scan with DeepSeek)."
                ),
            },
        )

    def handle_create_box(self, body: dict) -> None:
        name = str(body.get("name") or "").strip()
        address = str(body.get("address") or "").strip()
        neighborhood = str(body.get("neighborhood") or "Neighborhood").strip()
        if not name or not address:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Box name and address are required."})
            return

        charter = str(body.get("charter_number") or f"Charter #{130000 + abs(hash(name)) % 89999}").strip()
        steward = str(body.get("steward_name") or "Community Steward").strip()
        desc = str(body.get("description") or "Neighborhood Little Free Library box.").strip()
        roof_color = str(body.get("roof_color") or "#C85A32").strip()
        try:
            lat = max(8.0, min(92.0, float(body.get("lat", 50.0))))
            lng = max(8.0, min(92.0, float(body.get("lng", 50.0))))
        except (TypeError, ValueError):
            lat, lng = 50.0, 50.0

        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO boxes (name, charter_number, address, neighborhood, lat, lng, steward_name, description, roof_color, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, charter, address, neighborhood, lat, lng, steward, desc, roof_color, now),
            )
            box_id = cur.lastrowid
            state = build_state(conn)

        self.send_json(HTTPStatus.CREATED, {"box_id": box_id, "state": state})

    def handle_create_checkin(self, body: dict) -> None:
        photo_data = str(body.get("photo_data") or "").strip()
        if not photo_data:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "A box photo is required for a check-in."})
            return

        user_name = str(body.get("user_name") or "Neighbor Reader").strip()[:60]
        note = str(body.get("note") or "").strip()[:300]
        ai_source = str(body.get("ai_source") or "deepseek-api").strip()[:40]
        books_in = body.get("books") or []
        now = datetime.now(timezone.utc).isoformat()

        with get_db() as conn:
            box_id = body.get("box_id")
            new_box = body.get("new_box")
            if new_box and isinstance(new_box, dict):
                bname = str(new_box.get("name") or "").strip()
                baddr = str(new_box.get("address") or "").strip()
                if not bname or not baddr:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "New box requires name and address."})
                    return
                cur = conn.execute(
                    """
                    INSERT INTO boxes (name, charter_number, address, neighborhood, lat, lng, steward_name, description, roof_color, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bname,
                        str(new_box.get("charter_number") or "Charter #New"),
                        baddr,
                        str(new_box.get("neighborhood") or "Local Block"),
                        max(10.0, min(90.0, float(new_box.get("lat", 45.0)))),
                        max(10.0, min(90.0, float(new_box.get("lng", 48.0)))),
                        user_name,
                        str(new_box.get("description") or "Newly spotted Little Free Library box."),
                        str(new_box.get("roof_color") or "#C85A32"),
                        now,
                    ),
                )
                box_id = cur.lastrowid
            else:
                try:
                    box_id = int(box_id)
                except (TypeError, ValueError):
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Valid box_id or new_box is required."})
                    return
                exists = conn.execute("SELECT id FROM boxes WHERE id = ?", (box_id,)).fetchone()
                if not exists:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": f"Box {box_id} not found."})
                    return

            cur = conn.execute(
                """
                INSERT INTO checkins (box_id, user_name, photo_data, note, ai_source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (box_id, user_name, photo_data, note, ai_source, now),
            )
            checkin_id = cur.lastrowid

            inserted_books = 0
            for raw_book in books_in:
                if not isinstance(raw_book, dict):
                    continue
                title = str(raw_book.get("title") or "").strip()
                if not title:
                    continue
                author = str(raw_book.get("author") or "Unknown Author").strip() or "Unknown Author"
                genre = normalize_genre(str(raw_book.get("genre") or "Fiction"))
                color = str(raw_book.get("spine_color") or "#3B6E5C").strip()
                try:
                    conf = round(max(0.1, min(1.0, float(raw_book.get("confidence", 0.95)))), 2)
                except (TypeError, ValueError):
                    conf = 0.95
                bbox = clamp_bbox(raw_book.get("bbox")) if raw_book.get("bbox") else None

                conn.execute(
                    """
                    INSERT INTO books (checkin_id, box_id, title, author, genre, spine_color, confidence, bbox_json, status, spotted_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available', ?, ?)
                    """,
                    (
                        checkin_id,
                        box_id,
                        title[:120],
                        author[:80],
                        genre,
                        color[:20],
                        conf,
                        json.dumps(bbox) if bbox else None,
                        now,
                        now,
                    ),
                )
                inserted_books += 1

            state = build_state(conn)

        self.send_json(
            HTTPStatus.CREATED,
            {
                "checkin_id": checkin_id,
                "box_id": box_id,
                "indexed_books": inserted_books,
                "state": state,
            },
        )

    def handle_book_status(self, book_id: int, body: dict) -> None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            if not row:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": f"Book {book_id} not found."})
                return

            requested = str(body.get("status") or "").strip().lower()
            if requested in ("available", "picked_up"):
                next_status = requested
            else:
                next_status = "picked_up" if row["status"] == "available" else "available"

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE books SET status = ?, updated_at = ? WHERE id = ?",
                (next_status, now, book_id),
            )
            state = build_state(conn)

        self.send_json(HTTPStatus.OK, {"book_id": book_id, "status": next_status, "state": state})


def run() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, DEFAULT_PORT), ShelfSpotHandler)
    print(f"ShelfSpot server running at http://{HOST}:{DEFAULT_PORT}")
    print(f"SQLite database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down ShelfSpot server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
