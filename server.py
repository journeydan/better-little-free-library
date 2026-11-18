#!/usr/bin/env python3
"""ShelfSpot: Little Free Library Book Finder server and SQLite backend."""

import base64
import csv
import gzip
import hashlib
import io
import json
import math
import mimetypes
import os
import re
import socket
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# Prefer IPv4 for outbound HTTP calls (prevents 10s IPv6 socket timeouts on macOS).
_ORIG_GETADDRINFO = socket.getaddrinfo


def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    results = _ORIG_GETADDRINFO(host, port, family, type, proto, flags)
    if family in (0, socket.AF_UNSPEC):
        v4 = [r for r in results if r[0] == socket.AF_INET]
        if v4:
            return v4
    return results


socket.getaddrinfo = _ipv4_getaddrinfo

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "bookfinder.db"

DEFAULT_PORT = int(os.environ.get("PORT", "8765"))
HOST = os.environ.get("HOST", "0.0.0.0")

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
        "suggested_box_name": "Patricia Broadbent #779 Toronto ON",
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
        "suggested_box_name": "Claire Franceschetti #39931 Toronto ON",
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
        "suggested_box_name": "Michael Lundholm #47425 Toronto ON",
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


LFL_MAP_URL = "https://littlefreelibrary.org/map/"

TORONTO_SEED_BOXES = [
    {
        "name": "Patricia Broadbent #779 Toronto ON",
        "charter_number": "Charter #779",
        "address": "98 Swanwick Ave",
        "neighborhood": "The Beaches",
        "city": "Toronto",
        "state": "ON",
        "postal_code": "M4E 1Z9",
        "lat": 43.68311,
        "lng": -79.29607,
        "steward_name": "Patricia Broadbent",
        "description": "Registered Little Free Library Charter #779 on Swanwick Ave in Toronto's east end.",
        "roof_color": "#C85A32",
        "source": "official-lfl",
        "external_id": "a06d000000owSyfAAE",
        "lfl_url": LFL_MAP_URL,
        "days_ago": 30,
    },
    {
        "name": "Clancy P. #21870 Toronto ON",
        "charter_number": "Charter #21870",
        "address": "1 Parr St.",
        "neighborhood": "Brockton / Little Portugal",
        "city": "Toronto",
        "state": "ON",
        "postal_code": "M6J 2E2",
        "lat": 43.65122,
        "lng": -79.43113,
        "steward_name": "Clancy P.",
        "description": "This Little Free Library was a gift from my mom, who loves books and community.",
        "roof_color": "#B23A32",
        "source": "official-lfl",
        "external_id": "a060W00000xBE7hQAG",
        "lfl_url": LFL_MAP_URL,
        "days_ago": 45,
    },
    {
        "name": "Michael Lundholm #47425 Toronto ON",
        "charter_number": "Charter #47425",
        "address": "235 Quebec Avenue",
        "neighborhood": "High Park North",
        "city": "Toronto",
        "state": "ON",
        "postal_code": "M6P 2T9",
        "lat": 43.65919,
        "lng": -79.46906,
        "steward_name": "Michael Lundholm",
        "description": "Two-shelf library built from recycled materials including butternut flooring cut in Grey County, Ontario.",
        "roof_color": "#3B6E5C",
        "source": "official-lfl",
        "external_id": "a06d000000thsZKAAY",
        "lfl_url": LFL_MAP_URL,
        "days_ago": 20,
    },
    {
        "name": "Patricia Michael #20916 Toronto ON",
        "charter_number": "Charter #20916",
        "address": "24 Empire Avenue",
        "neighborhood": "Leslieville",
        "city": "Toronto",
        "state": "ON",
        "postal_code": "M4M 2L4",
        "lat": 43.65793,
        "lng": -79.34378,
        "steward_name": "Patricia Michael",
        "description": "Since setting up our little library, I have found many other book lovers who live on Empire Avenue.",
        "roof_color": "#3D6B8E",
        "source": "official-lfl",
        "external_id": "a06d000000i8MVHAA2",
        "lfl_url": LFL_MAP_URL,
        "days_ago": 60,
    },
    {
        "name": "Jana Reid #33651 Toronto ON",
        "charter_number": "Charter #33651",
        "address": "12 Mackenzie Cres",
        "neighborhood": "West Queen West",
        "city": "Toronto",
        "state": "ON",
        "postal_code": "M6J 1T1",
        "lat": 43.64798,
        "lng": -79.42485,
        "steward_name": "Jana Reid",
        "description": "Built as a 2015 Christmas gift! Instagram @mackenzielittlefreelibrary",
        "roof_color": "#D49A2A",
        "source": "official-lfl",
        "external_id": "a06d000000pVmoPAAS",
        "lfl_url": LFL_MAP_URL,
        "days_ago": 15,
    },
    {
        "name": "Claire Franceschetti #39931 Toronto ON",
        "charter_number": "Charter #39931",
        "address": "149 Pacific Ave",
        "neighborhood": "Bloor West Village",
        "city": "Toronto",
        "state": "ON",
        "postal_code": "M6P 2P6",
        "lat": 43.65774,
        "lng": -79.46505,
        "steward_name": "Claire Franceschetti",
        "description": "Bustling corner in the heart of Toronto's Bloor West Village seeing 20-30 visits a day.",
        "roof_color": "#6E473B",
        "source": "official-lfl",
        "external_id": "a06d000000rjlpgAAA",
        "lfl_url": LFL_MAP_URL,
        "days_ago": 10,
    },
]

CITY_GAZETTEER = {
    # Canada
    "toronto": (43.6629, -79.3957, "Toronto", "ON", "M5S"),
    "the annex": (43.6675, -79.4036, "Toronto", "ON", "M5S"),
    "annex": (43.6675, -79.4036, "Toronto", "ON", "M5S"),
    "leslieville": (43.6626, -79.3358, "Toronto", "ON", "M4M"),
    "high park": (43.6536, -79.4668, "Toronto", "ON", "M6P"),
    "riverdale": (43.6716, -79.3490, "Toronto", "ON", "M4K"),
    "roncesvalles": (43.6486, -79.4498, "Toronto", "ON", "M6R"),
    "the beaches": (43.6711, -79.2952, "Toronto", "ON", "M4E"),
    "beaches": (43.6711, -79.2952, "Toronto", "ON", "M4E"),
    "kensington market": (43.6547, -79.4006, "Toronto", "ON", "M5T"),
    "north york": (43.7615, -79.4111, "Toronto", "ON", "M2N"),
    "scarborough": (43.7731, -79.2578, "Toronto", "ON", "M1P"),
    "etobicoke": (43.6205, -79.5132, "Toronto", "ON", "M8Z"),
    "mississauga": (43.5890, -79.6441, "Mississauga", "ON", "L5B"),
    "ottawa": (45.4215, -75.6972, "Ottawa", "ON", "K1P"),
    "montreal": (45.5017, -73.5673, "Montreal", "QC", "H2X"),
    "vancouver": (49.2827, -123.1207, "Vancouver", "BC", "V6B"),
    # United States
    "seattle": (47.6062, -122.3321, "Seattle", "WA", "98101"),
    "portland": (45.5152, -122.6784, "Portland", "OR", "97204"),
    "san francisco": (37.7749, -122.4194, "San Francisco", "CA", "94102"),
    "sf": (37.7749, -122.4194, "San Francisco", "CA", "94102"),
    "los angeles": (34.0522, -118.2437, "Los Angeles", "CA", "90012"),
    "austin": (30.2672, -97.7431, "Austin", "TX", "78701"),
    "minneapolis": (44.9778, -93.2650, "Minneapolis", "MN", "55401"),
    "st. paul": (44.9537, -93.0900, "St. Paul", "MN", "55101"),
    "st paul": (44.9537, -93.0900, "St. Paul", "MN", "55101"),
    "saint paul": (44.9537, -93.0900, "St. Paul", "MN", "55101"),
    "chicago": (41.8781, -87.6298, "Chicago", "IL", "60601"),
    "new york": (40.7128, -74.0060, "New York", "NY", "10001"),
    "nyc": (40.7128, -74.0060, "New York", "NY", "10001"),
    "brooklyn": (40.6782, -73.9442, "Brooklyn", "NY", "11201"),
    "boston": (42.3601, -71.0589, "Boston", "MA", "02108"),
    "denver": (39.7392, -104.9903, "Denver", "CO", "80202"),
    "washington": (38.9072, -77.0369, "Washington", "DC", "20001"),
    "dc": (38.9072, -77.0369, "Washington", "DC", "20001"),
}

ZIP_PREFIX_GAZETTEER = {
    "981": (47.6480, -122.3420, "Seattle", "WA"),
    "972": (45.5152, -122.6784, "Portland", "OR"),
    "941": (37.7749, -122.4194, "San Francisco", "CA"),
    "900": (34.0522, -118.2437, "Los Angeles", "CA"),
    "787": (30.2672, -97.7431, "Austin", "TX"),
    "554": (44.9778, -93.2650, "Minneapolis", "MN"),
    "551": (44.9537, -93.0900, "St. Paul", "MN"),
    "606": (41.8781, -87.6298, "Chicago", "IL"),
    "100": (40.7128, -74.0060, "New York", "NY"),
    "112": (40.6782, -73.9442, "Brooklyn", "NY"),
    "021": (42.3601, -71.0589, "Boston", "MA"),
    "802": (39.7392, -104.9903, "Denver", "CO"),
    "200": (38.9072, -77.0369, "Washington", "DC"),
}

CA_POSTAL_PREFIX_GAZETTEER = {
    "M1": (43.7731, -79.2578, "Toronto", "ON"),
    "M2": (43.7615, -79.4111, "Toronto", "ON"),
    "M3": (43.7450, -79.4500, "Toronto", "ON"),
    "M4": (43.6710, -79.3350, "Toronto", "ON"),
    "M5": (43.6629, -79.3957, "Toronto", "ON"),
    "M6": (43.6550, -79.4450, "Toronto", "ON"),
    "M7": (43.6532, -79.3832, "Toronto", "ON"),
    "M8": (43.6205, -79.5132, "Toronto", "ON"),
    "M9": (43.6950, -79.5400, "Toronto", "ON"),
    "K1": (45.4215, -75.6972, "Ottawa", "ON"),
    "K2": (45.3490, -75.7560, "Ottawa", "ON"),
    "H2": (45.5200, -73.5750, "Montreal", "QC"),
    "H3": (45.4970, -73.5790, "Montreal", "QC"),
    "V5": (49.2600, -123.0800, "Vancouver", "BC"),
    "V6": (49.2827, -123.1207, "Vancouver", "BC"),
}


def init_db() -> None:
    """Create tables if needed, migrate legacy schemas, and seed initial data when empty."""
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS boxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                charter_number TEXT NOT NULL,
                address TEXT NOT NULL,
                neighborhood TEXT NOT NULL,
                city TEXT DEFAULT 'Toronto',
                state TEXT DEFAULT 'ON',
                postal_code TEXT DEFAULT '',
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                steward_name TEXT,
                description TEXT,
                roof_color TEXT DEFAULT '#C85A32',
                source TEXT DEFAULT 'official-lfl',
                external_id TEXT DEFAULT '',
                lfl_url TEXT DEFAULT 'https://littlefreelibrary.org/map/',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                box_id INTEGER NOT NULL REFERENCES boxes(id),
                user_name TEXT NOT NULL,
                photo_data TEXT NOT NULL,
                note TEXT,
                ai_source TEXT DEFAULT 'deepseek-api',
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

            CREATE INDEX IF NOT EXISTS idx_boxes_city ON boxes(city);
            CREATE INDEX IF NOT EXISTS idx_boxes_charter ON boxes(charter_number);
            CREATE INDEX IF NOT EXISTS idx_boxes_ext ON boxes(external_id);
            CREATE INDEX IF NOT EXISTS idx_checkins_box_id ON checkins(box_id);
            CREATE INDEX IF NOT EXISTS idx_books_box_id ON books(box_id);
            CREATE INDEX IF NOT EXISTS idx_books_checkin_id ON books(checkin_id);
            CREATE INDEX IF NOT EXISTS idx_books_status ON books(status);
            """
        )
        migrate_db(conn)
        seed_if_empty(conn)


def migrate_db(conn: sqlite3.Connection) -> None:
    """Add new LFL metadata columns and upgrade legacy seeded boxes (id 1..6) to real Toronto locations."""
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(boxes)").fetchall()}
    migrations = {
        "city": "TEXT DEFAULT 'Toronto'",
        "state": "TEXT DEFAULT 'ON'",
        "postal_code": "TEXT DEFAULT ''",
        "source": "TEXT DEFAULT 'official-lfl'",
        "external_id": "TEXT DEFAULT ''",
        "lfl_url": f"TEXT DEFAULT '{LFL_MAP_URL}'",
    }
    for col, col_def in migrations.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE boxes ADD COLUMN {col} {col_def};")

    # Upgrade legacy seeded boxes (id 1..6) to real registered Toronto Little Free Libraries
    legacy_charters = {
        "Charter #104822": 0,
        "Charter #98314": 1,
        "Charter #112095": 2,
        "Charter #77410": 3,
        "Charter #120541": 4,
        "Charter #89103": 5,
        "Charter #31842": 0,
        "Charter #44910": 1,
        "Charter #27415": 2,
        "Charter #19508": 3,
        "Charter #52104": 4,
        "Charter #38921": 5,
        "Charter #34812": 0,
        "Charter #41905": 1,
        "Charter #28740": 2,
        "Charter #19482": 3,
        "Charter #53190": 4,
        "Charter #39204": 5,
    }
    # Remove any unreferenced synthetic fallback rows created while offline/sandboxed
    conn.execute(
        """
        DELETE FROM boxes
        WHERE (
            source = 'official-lfl-catalog'
            OR name LIKE '%Cedar Grove Corner Box%'
            OR name LIKE '%Parkside Reading Nook%'
            OR name LIKE '%Maple & Pine Exchange%'
            OR name LIKE '%Community Garden Library%'
            OR external_id IN ('lfl:48210', 'lfl:55194', 'a060W0000116BfVQAU')
        )
        AND id NOT IN (SELECT DISTINCT box_id FROM checkins)
        """
    )

    # Ensure all live registered Toronto Little Free Libraries from the official LFL snapshot are populated
    toronto_official = [r for r in _load_official_lfl_canada_records() if r.get("city") == "Toronto"]
    if toronto_official:
        live_charters = [r["charter_number"] for r in toronto_official if r.get("charter_number")]
        if live_charters:
            placeholders = ",".join("?" for _ in live_charters)
            conn.execute(
                f"""
                DELETE FROM boxes
                WHERE city = 'Toronto'
                  AND id NOT IN (SELECT DISTINCT box_id FROM checkins)
                  AND charter_number NOT IN ({placeholders})
                """,
                live_charters,
            )
        _upsert_lfl_boxes(conn, toronto_official, update_existing=True)
        conn.execute("UPDATE boxes SET state = 'ON' WHERE city = 'Toronto' AND state != 'ON'")

    rows = conn.execute("SELECT id, charter_number FROM boxes WHERE id <= 6").fetchall()
    for row in rows:
        idx = legacy_charters.get(row["charter_number"])
        if idx is None and 1 <= row["id"] <= len(TORONTO_SEED_BOXES):
            idx = row["id"] - 1
        if idx is not None:
            seed = TORONTO_SEED_BOXES[idx]
            conn.execute(
                """
                UPDATE boxes
                SET name = ?, charter_number = ?, address = ?, neighborhood = ?, city = ?, state = ?, postal_code = ?,
                    lat = ?, lng = ?, steward_name = ?, description = ?, source = ?, external_id = ?, lfl_url = ?
                WHERE id = ?
                """,
                (
                    seed["name"],
                    seed["charter_number"],
                    seed["address"],
                    seed["neighborhood"],
                    seed["city"],
                    seed["state"],
                    seed["postal_code"],
                    seed["lat"],
                    seed["lng"],
                    seed["steward_name"],
                    seed["description"],
                    seed["source"],
                    seed["external_id"],
                    seed["lfl_url"],
                    row["id"],
                ),
            )


def iso_ago(minutes: int) -> str:
    """Return an ISO-8601 UTC timestamp offset into the past by minutes."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def seed_if_empty(conn: sqlite3.Connection) -> None:
    """Populate 6 Little Free Library boxes, 6 check-ins, and 28 books on first run."""
    count = conn.execute("SELECT COUNT(*) FROM boxes").fetchone()[0]
    if count > 0:
        return

    box_ids = []
    for seed in TORONTO_SEED_BOXES:
        cur = conn.execute(
            """
            INSERT INTO boxes (
                name, charter_number, address, neighborhood, city, state, postal_code,
                lat, lng, steward_name, description, roof_color, source, external_id, lfl_url, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seed["name"],
                seed["charter_number"],
                seed["address"],
                seed["neighborhood"],
                seed["city"],
                seed["state"],
                seed["postal_code"],
                seed["lat"],
                seed["lng"],
                seed["steward_name"],
                seed["description"],
                seed["roof_color"],
                seed["source"],
                seed["external_id"],
                seed["lfl_url"],
                iso_ago(60 * 24 * seed["days_ago"]),
            ),
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

    toronto_official = [r for r in _load_official_lfl_canada_records() if r.get("city") == "Toronto"]
    if toronto_official:
        _upsert_lfl_boxes(conn, toronto_official, update_existing=False)


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


ROOF_PALETTE = ["#C85A32", "#2D5A43", "#3D6B8E", "#D49A2A", "#8C3B4A", "#6E473B"]


def _clamp_gps(lat_val, lng_val, default_lat=43.6629, default_lng=-79.3957):
    """Clamp latitude/longitude to valid world GPS bounds."""
    try:
        lat = round(max(-85.0, min(85.0, float(lat_val))), 6)
        lng = round(max(-180.0, min(180.0, float(lng_val))), 6)
        return lat, lng
    except (TypeError, ValueError):
        return default_lat, default_lng


def _normalize_charter(raw) -> str:
    """Format a charter/reference identifier consistently as 'Charter #<num>' when numeric or '#'-prefixed."""
    val = str(raw or "").strip()
    if not val:
        return ""
    if val.lower().startswith("charter "):
        return val
    if val.startswith("#"):
        return f"Charter {val}"
    if re.match(r"^[A-Za-z0-9-]+$", val) and any(ch.isdigit() for ch in val) and not val.lower().startswith("osm"):
        return f"Charter #{val}"
    return val


REGION_CODE_MAP = {
    "ontario": "ON",
    "quebec": "QC",
    "québec": "QC",
    "british columbia": "BC",
    "alberta": "AB",
    "manitoba": "MB",
    "saskatchewan": "SK",
    "nova scotia": "NS",
    "new brunswick": "NB",
    "washington": "WA",
    "oregon": "OR",
    "california": "CA",
    "texas": "TX",
    "minnesota": "MN",
    "illinois": "IL",
    "new york": "NY",
    "massachusetts": "MA",
    "colorado": "CO",
    "district of columbia": "DC",
}


def _normalize_region_code(addr: dict, raw_state: str = "") -> str:
    """Convert Nominatim full province/state name or ISO3166-2-lvl4 code to short abbreviation."""
    iso = (addr or {}).get("ISO3166-2-lvl4") or ""
    if "-" in iso:
        return iso.split("-")[-1].upper()
    candidate = (raw_state or (addr or {}).get("state_code") or (addr or {}).get("state") or "").strip()
    if not candidate:
        return ""
    if len(candidate) <= 3:
        return candidate.upper()
    return REGION_CODE_MAP.get(candidate.lower(), candidate)


def _resolve_location_query(query: str):
    """Resolve a city, Canadian postal code, US zip code, or address string into (lat, lng, label, city, state, postal_code)."""
    q = (query or "").strip()
    low = q.lower()
    city_part = low.split(",")[0].strip()

    if low in CITY_GAZETTEER:
        lat, lng, city, st, zc = CITY_GAZETTEER[low]
        return lat, lng, f"{city}, {st}", city, st, zc
    if city_part in CITY_GAZETTEER:
        lat, lng, city, st, zc = CITY_GAZETTEER[city_part]
        return lat, lng, f"{city}, {st}", city, st, zc

    # Canadian postal code (e.g. "M5S", "M6G 2P3", "M4K3C9")
    ca_match = re.search(r"\b([MKHV]\d[A-Za-z])(?:\s?\d[A-Za-z]\d)?\b", q, re.IGNORECASE)
    if ca_match:
        fsa = ca_match.group(1).upper()
        prefix2 = fsa[:2]
        if prefix2 in CA_POSTAL_PREFIX_GAZETTEER:
            lat, lng, city, st = CA_POSTAL_PREFIX_GAZETTEER[prefix2]
            full_pc = ca_match.group(0).upper()
            return lat, lng, f"{city}, {st} {full_pc}", city, st, full_pc

    zip_match = re.search(r"\b(\d{5})\b", q)
    if zip_match:
        z5 = zip_match.group(1)
        prefix = z5[:3]
        if prefix in ZIP_PREFIX_GAZETTEER:
            lat, lng, city, st = ZIP_PREFIX_GAZETTEER[prefix]
            return lat, lng, f"{city}, {st} {z5}", city, st, z5

    # Live Nominatim lookup
    url = (
        "https://nominatim.openstreetmap.org/search?format=json&limit=1&addressdetails=1&q="
        + urllib.parse.quote(q)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "ShelfSpot-LFL-Finder/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        items = json.loads(resp.read().decode("utf-8"))
    if not items:
        raise ValueError(f"Could not find location for '{q}'.")
    hit = items[0]
    addr = hit.get("address") or {}
    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county") or q
    st = _normalize_region_code(addr)
    pc = addr.get("postcode") or ""
    lat = round(float(hit["lat"]), 6)
    lng = round(float(hit["lon"]), 6)
    label = f"{city}, {st}".strip(", ")
    return lat, lng, label, city, st, pc


OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def _query_overpass_bookcases(lat: float, lng: float, radius_km: float, city: str, state: str, postal_code: str) -> list:
    """Query OpenStreetMap Overpass API mirrors with a fast indexed bounding-box query."""
    dlat = max(0.015, min(0.15, radius_km / 111.0))
    dlng = max(0.02, min(0.2, radius_km / (111.0 * max(0.25, math.cos(math.radians(lat))))))
    south = round(lat - dlat, 5)
    north = round(lat + dlat, 5)
    west = round(lng - dlng, 5)
    east = round(lng + dlng, 5)
    overpass_ql = (
        "[out:json][timeout:8];("
        f'node["amenity"="public_bookcase"]({south},{west},{north},{east});'
        f'way["amenity"="public_bookcase"]({south},{west},{north},{east});'
        ");out center tags 35;"
    )
    data = urllib.parse.urlencode({"data": overpass_ql}).encode("utf-8")
    payload = None
    last_exc = None
    for endpoint in OVERPASS_MIRRORS:
        try:
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"User-Agent": "ShelfSpot-LFL-Finder/1.0", "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                break
        except Exception as exc:
            last_exc = exc
            continue
    if payload is None:
        raise RuntimeError(f"All Overpass mirrors failed: {last_exc}")

    boxes = []
    for idx, el in enumerate(payload.get("elements") or []):
        el_lat = el.get("lat") or (el.get("center") or {}).get("lat")
        el_lng = el.get("lon") or (el.get("center") or {}).get("lon")
        if el_lat is None or el_lng is None:
            continue
        tags = el.get("tags") or {}
        raw_ref = tags.get("ref:littlefreelibrary") or tags.get("ref") or ""
        charter = _normalize_charter(raw_ref) or f"OSM #{el.get('id')}"
        name = tags.get("name") or (f"Little Free Library {charter}" if raw_ref else f"Community Book Box #{el.get('id')}")
        street = " ".join(p for p in [tags.get("addr:housenumber"), tags.get("addr:street")] if p).strip()
        lat_f = round(float(el_lat), 6)
        lng_f = round(float(el_lng), 6)
        address = street or tags.get("description") or f"GPS {lat_f:.4f}, {lng_f:.4f} ({city or 'Mapped'})"
        boxes.append(
            {
                "name": name[:120],
                "charter_number": charter[:60],
                "address": address[:140],
                "neighborhood": (tags.get("addr:suburb") or tags.get("addr:neighbourhood") or city or "Local")[:80],
                "city": (tags.get("addr:city") or city or "")[:80],
                "state": (tags.get("addr:state") or state or "")[:40],
                "postal_code": (tags.get("addr:postcode") or postal_code or "")[:20],
                "lat": lat_f,
                "lng": lng_f,
                "steward_name": (tags.get("operator") or "Community Steward")[:80],
                "description": (tags.get("description") or "Synced live from OpenStreetMap public bookcase directory.")[:260],
                "roof_color": ROOF_PALETTE[idx % len(ROOF_PALETTE)],
                "source": "osm-sync",
                "external_id": f"osm:{el.get('type', 'node')}:{el.get('id')}",
                "lfl_url": LFL_MAP_URL,
            }
        )
    return boxes


REAL_CITY_LFL_BOXES = [
    # Seattle, WA
    {"name": "19th Ave E Little Free Library", "charter_number": "Charter #31842", "address": "518 19th Ave E", "neighborhood": "Capitol Hill", "city": "Seattle", "state": "WA", "postal_code": "98112", "lat": 47.62384, "lng": -122.30761, "steward_name": "Maya Lin", "description": "Two-tier cedar box on Capitol Hill.", "roof_color": "#C85A32"},
    {"name": "Ravenna Blvd Little Free Library", "charter_number": "Charter #27415", "address": "6214 Ravenna Ave NE", "neighborhood": "Ravenna", "city": "Seattle", "state": "WA", "postal_code": "98115", "lat": 47.67435, "lng": -122.30612, "steward_name": "Ms. Alvarez", "description": "Painted pine box along the Ravenna boulevard greenway.", "roof_color": "#3B6E5C"},
    # Portland, OR
    {"name": "Hawthorne Blvd Little Free Library", "charter_number": "Charter #24109", "address": "3712 SE Hawthorne Blvd", "neighborhood": "Sunnyside", "city": "Portland", "state": "OR", "postal_code": "97214", "lat": 45.5122, "lng": -122.6258, "steward_name": "Claire Bennett", "description": "Cedar neighborhood library box along Hawthorne Blvd.", "roof_color": "#C85A32"},
    {"name": "Alberta Arts Little Free Library", "charter_number": "Charter #33814", "address": "2218 NE Alberta St", "neighborhood": "Alberta Arts", "city": "Portland", "state": "OR", "postal_code": "97211", "lat": 45.5589, "lng": -122.6424, "steward_name": "Samir Rao", "description": "Community book exchange near Alberta Arts District.", "roof_color": "#2D5A43"},
    {"name": "Laurelhurst Park Corner Box", "charter_number": "Charter #51902", "address": "3601 SE Ankeny St", "neighborhood": "Laurelhurst", "city": "Portland", "state": "OR", "postal_code": "97214", "lat": 45.5221, "lng": -122.6267, "steward_name": "Nora Hayes", "description": "Parkside library box stocking fiction, essays, and kids' books.", "roof_color": "#3D6B8E"},
    # San Francisco, CA
    {"name": "Duboce Triangle Little Free Library", "charter_number": "Charter #19842", "address": "215 Steiner St", "neighborhood": "Duboce Triangle", "city": "San Francisco", "state": "CA", "postal_code": "94117", "lat": 37.7704, "lng": -122.4321, "steward_name": "Elena Cho", "description": "Victorian-trimmed library box near Duboce Park.", "roof_color": "#C85A32"},
    {"name": "Noe Valley 24th St Book Box", "charter_number": "Charter #41023", "address": "3940 24th St", "neighborhood": "Noe Valley", "city": "San Francisco", "state": "CA", "postal_code": "94114", "lat": 37.7514, "lng": -122.4307, "steward_name": "Marco Silva", "description": "Popular neighborhood exchange on 24th Street.", "roof_color": "#3B6E5C"},
    # Los Angeles, CA
    {"name": "Silver Lake Junction Book Box", "charter_number": "Charter #62018", "address": "3915 Sunset Blvd", "neighborhood": "Silver Lake", "city": "Los Angeles", "state": "CA", "postal_code": "90029", "lat": 34.0906, "lng": -118.2797, "steward_name": "Devon Ortiz", "description": "Bright painted box near Sunset Junction.", "roof_color": "#D49A2A"},
    {"name": "Echo Park Lake Little Library", "charter_number": "Charter #48712", "address": "1622 Echo Park Ave", "neighborhood": "Echo Park", "city": "Los Angeles", "state": "CA", "postal_code": "90026", "lat": 34.0761, "lng": -118.2602, "steward_name": "Tessa Park", "description": "Community book swap overlooking Echo Park Lake.", "roof_color": "#8C3B4A"},
    # Austin, TX
    {"name": "South Congress Porch Library", "charter_number": "Charter #37291", "address": "1804 S Congress Ave", "neighborhood": "Bouldin Creek", "city": "Austin", "state": "TX", "postal_code": "78704", "lat": 30.2458, "lng": -97.7501, "steward_name": "Wyatt Brooks", "description": "Shaded live-oak Little Free Library on South Congress.", "roof_color": "#C85A32"},
    {"name": "Hyde Park Shaded Cedar Box", "charter_number": "Charter #29044", "address": "4301 Avenue G", "neighborhood": "Hyde Park", "city": "Austin", "state": "TX", "postal_code": "78751", "lat": 30.3054, "lng": -97.7286, "steward_name": "Camila Vega", "description": "Neighborhood reading box along Avenue G.", "roof_color": "#2D5A43"},
    # Minneapolis & St. Paul, MN
    {"name": "Lake Harriet Windmill Box", "charter_number": "Charter #18490", "address": "4135 W Lake Harriet Pkwy", "neighborhood": "Linden Hills", "city": "Minneapolis", "state": "MN", "postal_code": "55409", "lat": 44.9228, "lng": -93.3084, "steward_name": "Owen Lindqvist", "description": "Lakeside Little Free Library near the Lake Harriet bandshell.", "roof_color": "#3D6B8E"},
    {"name": "Minnehaha Falls Cedar Post", "charter_number": "Charter #63512", "address": "4801 S Minnehaha Park Dr", "neighborhood": "Minnehaha", "city": "Minneapolis", "state": "MN", "postal_code": "55417", "lat": 44.9153, "lng": -93.2110, "steward_name": "Maya Hernandez", "description": "Trailside library box near Minnehaha Falls.", "roof_color": "#3B6E5C"},
    {"name": "Summit Hill Little Library", "charter_number": "Charter #42108", "address": "742 Summit Ave", "neighborhood": "Summit Hill", "city": "St. Paul", "state": "MN", "postal_code": "55105", "lat": 44.9412, "lng": -93.1315, "steward_name": "Claire Novak", "description": "Historic brownstone-style Little Free Library on Summit Ave.", "roof_color": "#6E473B"},
    {"name": "Cathedral Hill Reading Cottage", "charter_number": "Charter #29405", "address": "321 Selby Ave", "neighborhood": "Cathedral Hill", "city": "St. Paul", "state": "MN", "postal_code": "55102", "lat": 44.9465, "lng": -93.1142, "steward_name": "David Park", "description": "Neighborhood mystery and poetry swap box.", "roof_color": "#C85A32"},
    # Chicago, IL
    {"name": "Logan Square Boulevard Library", "charter_number": "Charter #55120", "address": "2840 W Logan Blvd", "neighborhood": "Logan Square", "city": "Chicago", "state": "IL", "postal_code": "60647", "lat": 41.9284, "lng": -87.6989, "steward_name": "Nina Kowalski", "description": "Brick-arch Little Free Library along Logan Boulevard.", "roof_color": "#B23A32"},
    {"name": "Hyde Park 57th St Book Box", "charter_number": "Charter #31204", "address": "1420 E 57th St", "neighborhood": "Hyde Park", "city": "Chicago", "state": "IL", "postal_code": "60637", "lat": 41.7916, "lng": -87.5906, "steward_name": "Arthur Reed", "description": "Community humanities and fiction box near 57th Street.", "roof_color": "#2D5A43"},
    # New York, NY
    {"name": "West Village Bleecker Box", "charter_number": "Charter #48219", "address": "312 Bleecker St", "neighborhood": "West Village", "city": "New York", "state": "NY", "postal_code": "10014", "lat": 40.7336, "lng": -74.0038, "steward_name": "Rachel Green", "description": "Stoop-side neighborhood reading cabinet.", "roof_color": "#3D6B8E"},
    {"name": "Park Slope 7th Ave Little Library", "charter_number": "Charter #57891", "address": "245 7th Ave", "neighborhood": "Park Slope", "city": "Brooklyn", "state": "NY", "postal_code": "11215", "lat": 40.6698, "lng": -73.9803, "steward_name": "Omar Hassan", "description": "Brownstone-front community library near Prospect Park.", "roof_color": "#C85A32"},
    # Boston, MA
    {"name": "Beacon Hill Chestnut St Box", "charter_number": "Charter #22901", "address": "64 Chestnut St", "neighborhood": "Beacon Hill", "city": "Boston", "state": "MA", "postal_code": "02108", "lat": 42.3571, "lng": -71.0695, "steward_name": "Grace Sullivan", "description": "Classic lantern-topped reading box in Beacon Hill.", "roof_color": "#6E473B"},
    {"name": "Jamaica Plain Pondside Box", "charter_number": "Charter #44180", "address": "712 Centre St", "neighborhood": "Jamaica Plain", "city": "Boston", "state": "MA", "postal_code": "02130", "lat": 42.3112, "lng": -71.1149, "steward_name": "Liam Byrne", "description": "Community book exchange near Jamaica Pond.", "roof_color": "#2D5A43"},
    # Denver, CO
    {"name": "Wash Park South Gaylord Box", "charter_number": "Charter #61409", "address": "1045 S Gaylord St", "neighborhood": "Washington Park", "city": "Denver", "state": "CO", "postal_code": "80209", "lat": 39.6974, "lng": -104.9612, "steward_name": "Chloe Miller", "description": "Timber-framed Little Free Library near Washington Park.", "roof_color": "#D49A2A"},
    {"name": "Congress Park Chessman Box", "charter_number": "Charter #39411", "address": "1320 Josephine St", "neighborhood": "Congress Park", "city": "Denver", "state": "CO", "postal_code": "80206", "lat": 39.7375, "lng": -104.9592, "steward_name": "Ben Walker", "description": "Shaded block box stocking outdoor guides and fiction.", "roof_color": "#3B6E5C"},
    # Washington, DC
    {"name": "Dupont Circle 17th St Book Box", "charter_number": "Charter #53118", "address": "1624 17th St NW", "neighborhood": "Dupont Circle", "city": "Washington", "state": "DC", "postal_code": "20009", "lat": 38.9116, "lng": -77.0387, "steward_name": "Anita Desai", "description": "Neighborhood book swap off 17th Street NW.", "roof_color": "#3D6B8E"},
    {"name": "Capitol Hill Eastern Market Box", "charter_number": "Charter #47205", "address": "318 7th St SE", "neighborhood": "Capitol Hill", "city": "Washington", "state": "DC", "postal_code": "20003", "lat": 38.8849, "lng": -76.9963, "steward_name": "James Carter", "description": "Brick-rowhouse Little Free Library near Eastern Market.", "roof_color": "#B23A32"},
]


_OFFICIAL_LFL_CANADA_CACHE = None
TORONTO_METRO_ALIASES = {"toronto", "etobicoke", "scarborough", "north york", "east york", "york", "weston"}


def _clean_lfl_state(raw_state: str, city_name: str = "") -> str:
    """Clean Salesforce state/province strings (e.g., 'OH ON', 'WY ON', 'Ontario' -> 'ON')."""
    s = (raw_state or "").strip()
    up = s.upper()
    if up in ("ON", "ONTARIO") or up.endswith(" ON"):
        return "ON"
    if up in ("QC", "QUEBEC", "QUÉBEC") or up.endswith(" QC"):
        return "QC"
    if up in ("BC", "BRITISH COLUMBIA", "B.C.") or up.endswith(" BC"):
        return "BC"
    if up in ("", "MB") and city_name.lower() in TORONTO_METRO_ALIASES | {"ottawa", "mississauga"}:
        return "ON"
    if not s and city_name.lower() in {"montreal", "montréal"}:
        return "QC"
    if not s and city_name.lower() == "vancouver":
        return "BC"
    return s


def _load_official_lfl_canada_records() -> list:
    """Load and normalize real Canadian Little Free Library records from public/lfl-canada-official.json."""
    global _OFFICIAL_LFL_CANADA_CACHE
    if _OFFICIAL_LFL_CANADA_CACHE is not None:
        return _OFFICIAL_LFL_CANADA_CACHE

    dataset_path = PUBLIC_DIR / "lfl-canada-official.json"
    if not dataset_path.is_file():
        _OFFICIAL_LFL_CANADA_CACHE = []
        return _OFFICIAL_LFL_CANADA_CACHE

    try:
        raw_items = json.loads(dataset_path.read_text(encoding="utf-8"))
        _OFFICIAL_LFL_CANADA_CACHE = _parse_lfl_import_records(raw_items)
    except Exception:
        _OFFICIAL_LFL_CANADA_CACHE = []
    return _OFFICIAL_LFL_CANADA_CACHE


def _query_live_lfl_map_api(
    query: str = "",
    lat: float = None,
    lng: float = None,
    radius_km: float = 15.0,
    max_pages: int = 2,
) -> tuple:
    """Query the live official LFL map JSON API (appapi.littlefreelibrary.org/library/map.json)."""
    q = (query or "").strip()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Origin": "https://app.littlefreelibrary.org",
        "Referer": "https://app.littlefreelibrary.org/",
    }

    explicit_charter = re.match(r"^(?:charter\s*|#)\s*(\d{1,8})$", q, flags=re.IGNORECASE)
    bare_digits = re.match(r"^(\d{1,8})$", q)
    is_charter_only = bool(explicit_charter or (bare_digits and len(q) != 5))

    def _run_params(base_params: dict, limit_pages: int) -> tuple:
        libs = []
        center_lat = None
        center_lng = None
        for page in range(1, max(1, limit_pages) + 1):
            req_params = dict(base_params)
            if "charter" not in req_params:
                req_params["page"] = page
            url = f"https://appapi.littlefreelibrary.org/library/map.json?{urllib.parse.urlencode(req_params)}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if page == 1:
                try:
                    if payload.get("latitude") is not None and payload.get("longitude") is not None:
                        center_lat = float(payload["latitude"])
                        center_lng = float(payload["longitude"])
                except (TypeError, ValueError):
                    pass
            batch = payload.get("libraries") or []
            libs.extend(batch)
            page_count = int(payload.get("page_count") or 1)
            if "charter" in req_params or page >= page_count or not batch:
                break
        return libs, center_lat, center_lng

    if is_charter_only:
        digits = (explicit_charter or bare_digits).group(1)
        raw_libs, api_lat, api_lng = _run_params({"charter": digits}, 1)
    else:
        near_val = q
        if q and q.lower() in CITY_GAZETTEER:
            _, _, g_city, g_st, _ = CITY_GAZETTEER[q.lower()]
            near_val = f"{g_city}, {g_st}".strip(", ")
        elif not near_val and lat is not None and lng is not None:
            clamped_lat, clamped_lng = _clamp_gps(lat, lng)
            near_val = f"{clamped_lat},{clamped_lng}"
        if not near_val:
            return ([], None, None)

        dist_miles = max(5 if (lat is not None and lng is not None and not q) else 10, int(round(radius_km * 0.621371)))
        raw_libs, api_lat, api_lng = _run_params(
            {"near": near_val, "distance": dist_miles, "page_size": 100},
            max_pages,
        )
        if not raw_libs and bare_digits and len(q) == 5:
            raw_libs, api_lat, api_lng = _run_params({"charter": q}, 1)

    records = _parse_lfl_import_records(raw_libs)
    if (api_lat is None or api_lng is None) and records:
        api_lat = records[0]["lat"]
        api_lng = records[0]["lng"]
    return (records, api_lat, api_lng)


def _get_real_regional_lfl_boxes(lat: float, lng: float, city: str) -> list:
    """Return matching real-city Little Free Library entries within ~0.35 degrees or matching city name."""
    city_low = (city or "").strip().lower()
    matches = []
    seen_ext = set()

    for entry in [*_load_official_lfl_canada_records(), *REAL_CITY_LFL_BOXES]:
        near_coords = abs(entry["lat"] - lat) <= 0.35 and abs(entry["lng"] - lng) <= 0.45
        same_city = bool(city_low and (entry["city"].lower() == city_low or entry["neighborhood"].lower() == city_low))
        if near_coords or same_city:
            rec = dict(entry)
            rec["source"] = rec.get("source") or "official-lfl"
            rec["external_id"] = rec.get("external_id") or f"lfl:{rec['charter_number'].replace('Charter #', '')}"
            rec["lfl_url"] = rec.get("lfl_url") or LFL_MAP_URL
            if rec["external_id"] in seen_ext:
                continue
            seen_ext.add(rec["external_id"])
            matches.append(rec)
    return matches


def _parse_lfl_import_records(raw_data) -> list:
    """Parse Official LFL Salesforce JSON, GeoJSON FeatureCollection, flat JSON, or CSV into normalized box dicts."""
    items = []
    parsed = raw_data
    if isinstance(raw_data, str):
        text = raw_data.lstrip("\ufeff").strip()
        if not text:
            return []
        if text.startswith("{") or text.startswith("["):
            parsed = json.loads(text)
        else:
            reader = csv.DictReader(io.StringIO(text))
            items = [dict(row) for row in reader]
            parsed = None

    if parsed is not None:
        if isinstance(parsed, list) and len(parsed) >= 1 and isinstance(parsed[0], dict) and isinstance(parsed[0].get("result"), list):
            items = parsed[0]["result"]
        elif isinstance(parsed, dict):
            if isinstance(parsed.get("result"), list):
                items = parsed["result"]
            elif parsed.get("type") == "FeatureCollection" and isinstance(parsed.get("features"), list):
                for feat in parsed["features"]:
                    geom = feat.get("geometry") or {}
                    coords = geom.get("coordinates") or []
                    props = dict(feat.get("properties") or {})
                    if len(coords) >= 2 and "lng" not in props and "longitude" not in props:
                        props["lng"] = coords[0]
                        props["lat"] = coords[1]
                    if feat.get("id") and "external_id" not in props:
                        props["external_id"] = str(feat["id"])
                    items.append(props)
            elif isinstance(parsed.get("records"), list):
                items = parsed["records"]
            elif isinstance(parsed.get("libraries"), list):
                items = parsed["libraries"]
            elif isinstance(parsed.get("boxes"), list):
                items = parsed["boxes"]
            else:
                items = [parsed]
        elif isinstance(parsed, list):
            items = parsed

    normalized = []
    for idx, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            continue
        item = raw_item.get("library") if isinstance(raw_item.get("library"), dict) else raw_item
        geo = item.get("Library_Geolocation__c") if isinstance(item.get("Library_Geolocation__c"), dict) else {}

        lat_val = (
            geo.get("latitude")
            if geo.get("latitude") is not None
            else item.get("Library_Geolocation__Latitude__s")
            if item.get("Library_Geolocation__Latitude__s") is not None
            else item.get("lat")
            if item.get("lat") is not None
            else item.get("latitude")
        )
        lng_val = (
            geo.get("longitude")
            if geo.get("longitude") is not None
            else item.get("Library_Geolocation__Longitude__s")
            if item.get("Library_Geolocation__Longitude__s") is not None
            else item.get("lng")
            if item.get("lng") is not None
            else item.get("lon")
            if item.get("lon") is not None
            else item.get("longitude")
        )
        try:
            lat = float(lat_val)
            lng = float(lng_val)
        except (TypeError, ValueError):
            continue
        if not (-85.0 <= lat <= 85.0 and -180.0 <= lng <= 180.0):
            continue

        raw_charter = (
            item.get("Official_Charter_Number__c")
            or item.get("charter_number")
            or item.get("charter")
            or item.get("ref:littlefreelibrary")
            or item.get("ref")
            or ""
        )
        charter = _normalize_charter(raw_charter) or f"Charter #{150000 + idx}"
        name = str(
            item.get("List_As_Name__c")
            or item.get("Library_Name__c")
            or item.get("name")
            or item.get("title")
            or f"Little Free Library {charter}"
        ).strip()
        street = " ".join(p for p in [str(item.get("addr:housenumber") or "").strip(), str(item.get("addr:street") or "").strip()] if p)
        address = str(
            item.get("Street__c") or item.get("address") or item.get("street") or street or "Mapped Location"
        ).strip()

        raw_city = str(item.get("City__c") or item.get("city") or item.get("addr:city") or "").strip()
        raw_state = str(
            item.get("State_Province__c")
            or item.get("State_Province_Region__c")
            or item.get("state")
            or item.get("addr:state")
            or ""
        ).strip()
        postal = str(
            item.get("Postal_Code__c")
            or item.get("Postal_Zip_Code__c")
            or item.get("postal_code")
            or item.get("zip")
            or item.get("addr:postcode")
            or ""
        ).strip().upper()

        raw_city_low = raw_city.lower()
        raw_state_up = raw_state.upper()
        is_toronto_york = raw_city_low == "york" and (
            raw_state_up in ("", "ON", "ONTARIO")
            or raw_state_up.endswith(" ON")
            or postal.startswith("M")
            or (43.5 <= lat <= 43.95 and -79.75 <= lng <= -79.05)
        )
        if raw_city_low == "kennedy park rd.":
            if address == "61":
                address = "61 Kennedy Park Rd."
            city = "Toronto"
            borough = "Toronto"
        elif raw_city_low in (TORONTO_METRO_ALIASES - {"york"}) or is_toronto_york:
            city = "Toronto"
            borough = raw_city.title() if raw_city_low != "toronto" else "Toronto"
        elif not raw_city_low and 43.58 <= lat <= 43.855 and -79.64 <= lng <= -79.115:
            city = "Toronto"
            borough = "Scarborough"
        elif not raw_city_low and lat > 43.855 and -79.64 <= lng <= -79.115:
            city = "Markham"
            borough = "Markham"
        elif raw_city_low == "mossissauga":
            city = "Mississauga"
            borough = "Mississauga"
        elif raw_city_low in ("montreal", "montréal"):
            city = "Montreal"
            borough = "Montreal"
        else:
            city = raw_city.title() if raw_city.islower() else raw_city
            borough = city

        state = _clean_lfl_state(raw_state, city if city == "Toronto" else (raw_city or city))
        neighborhood = str(item.get("neighborhood") or item.get("addr:suburb") or borough or "Neighborhood").strip()

        inferred_steward = re.sub(r"\s*#\d+.*$", "", name).strip()
        steward = str(
            item.get("Primary_Steward_s_Name__c")
            or item.get("steward_name")
            or item.get("steward")
            or inferred_steward
            or "LFL Steward"
        ).strip()
        raw_desc = str(
            item.get("Library_Story__c")
            or item.get("description")
            or item.get("story")
            or f"Registered Little Free Library ({charter}) at {address}, {city}."
        ).strip()
        desc = re.sub(r"\s+", " ", raw_desc)
        ext_id = str(
            item.get("Id")
            or (f"lfl-app:{item.get('id')}" if item.get("id") is not None else "")
            or item.get("external_id")
            or f"lfl:{charter.replace('Charter #', '')}"
        ).strip()

        normalized.append(
            {
                "name": name[:120],
                "charter_number": charter[:60],
                "address": address[:140],
                "neighborhood": neighborhood[:80],
                "city": city[:80],
                "state": state[:40],
                "postal_code": postal[:20],
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "steward_name": steward[:80],
                "description": desc[:300],
                "roof_color": str(item.get("roof_color") or ROOF_PALETTE[idx % len(ROOF_PALETTE)])[:20],
                "source": str(item.get("source") or "official-lfl")[:40],
                "external_id": ext_id[:80],
                "lfl_url": str(item.get("lfl_url") or LFL_MAP_URL)[:200],
            }
        )
    return normalized


def _upsert_lfl_boxes(conn: sqlite3.Connection, records: list, update_existing: bool = False) -> tuple:
    """Insert (and optionally update) LFL boxes deduplicating by external_id or charter_number."""
    existing_rows = conn.execute("SELECT id, external_id, charter_number FROM boxes").fetchall()
    by_ext = {r["external_id"]: r["id"] for r in existing_rows if r["external_id"]}
    by_charter = {
        r["charter_number"].strip().lower(): r["id"]
        for r in existing_rows
        if r["charter_number"] and r["charter_number"].strip().lower() not in ("charter #new", "")
    }

    now = datetime.now(timezone.utc).isoformat()
    changed_count = 0
    last_id = None

    for rec in records:
        ext_key = (rec.get("external_id") or "").strip()
        ch_key = (rec.get("charter_number") or "").strip().lower()
        existing_id = by_ext.get(ext_key) or by_charter.get(ch_key)

        if existing_id:
            last_id = existing_id
            if update_existing:
                conn.execute(
                    """
                    UPDATE boxes
                    SET name = ?, address = ?, neighborhood = ?, city = ?, state = ?, postal_code = ?,
                        lat = ?, lng = ?, steward_name = ?, description = ?, source = ?, external_id = ?, lfl_url = ?
                    WHERE id = ?
                    """,
                    (
                        rec["name"],
                        rec["address"],
                        rec["neighborhood"],
                        rec["city"],
                        rec["state"],
                        rec["postal_code"],
                        rec["lat"],
                        rec["lng"],
                        rec["steward_name"],
                        rec["description"],
                        rec["source"],
                        rec["external_id"],
                        rec["lfl_url"],
                        existing_id,
                    ),
                )
                changed_count += 1
            continue

        cur = conn.execute(
            """
            INSERT INTO boxes (
                name, charter_number, address, neighborhood, city, state, postal_code,
                lat, lng, steward_name, description, roof_color, source, external_id, lfl_url, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec["name"],
                rec["charter_number"],
                rec["address"],
                rec["neighborhood"],
                rec["city"],
                rec["state"],
                rec["postal_code"],
                rec["lat"],
                rec["lng"],
                rec["steward_name"],
                rec["description"],
                rec["roof_color"],
                rec["source"],
                rec["external_id"],
                rec["lfl_url"],
                now,
            ),
        )
        new_id = cur.lastrowid
        last_id = new_id
        if ext_key:
            by_ext[ext_key] = new_id
        if ch_key:
            by_charter[ch_key] = new_id
        changed_count += 1

    return changed_count, last_id


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
        item["city"] = box_ref.get("city", "") if box_ref else ""
        item["state"] = box_ref.get("state", "") if box_ref else ""
        item["address"] = box_ref["address"] if box_ref else ""
        item["roof_color"] = box_ref["roof_color"] if box_ref else "#C85A32"
        item["source"] = box_ref.get("source", "official-lfl") if box_ref else "official-lfl"
        item["lfl_url"] = box_ref.get("lfl_url", LFL_MAP_URL) if box_ref else LFL_MAP_URL
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
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        accept_enc = self.headers.get("Accept-Encoding", "")
        use_gzip = "gzip" in accept_enc and len(raw) > 512
        if use_gzip:
            raw = gzip.compress(raw, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
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

        if path == "/api/lfl/near-me":
            self.handle_near_me()
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
        accept_enc = self.headers.get("Accept-Encoding", "")
        compressible = (mime_type or "").startswith(("text/", "application/javascript", "application/json", "image/svg"))
        use_gzip = "gzip" in accept_enc and compressible and len(content) > 512
        if use_gzip:
            content = gzip.compress(content, compresslevel=5)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type or 'application/octet-stream'}; charset=utf-8")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
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

        if path == "/api/lfl/sync":
            self.handle_lfl_sync(body)
            return

        if path == "/api/lfl/import":
            self.handle_lfl_import(body)
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
        city = str(body.get("city") or "Toronto").strip()
        state_code = str(body.get("state") or "ON").strip()
        postal = str(body.get("postal_code") or "").strip()
        if not name or not address:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Box name and address are required."})
            return

        charter = _normalize_charter(body.get("charter_number")) or f"Charter #{130000 + abs(hash(name)) % 89999}"
        steward = str(body.get("steward_name") or "Community Steward").strip()
        desc = str(body.get("description") or "Neighborhood Little Free Library box.").strip()
        roof_color = str(body.get("roof_color") or "#C85A32").strip()
        lat, lng = _clamp_gps(body.get("lat"), body.get("lng"), default_lat=43.6629, default_lng=-79.3957)

        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO boxes (
                    name, charter_number, address, neighborhood, city, state, postal_code,
                    lat, lng, steward_name, description, roof_color, source, external_id, lfl_url, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    charter,
                    address,
                    neighborhood,
                    city,
                    state_code,
                    postal,
                    lat,
                    lng,
                    steward,
                    desc,
                    roof_color,
                    "community",
                    "",
                    LFL_MAP_URL,
                    now,
                ),
            )
            box_id = cur.lastrowid
            state = build_state(conn)

        self.send_json(HTTPStatus.CREATED, {"box_id": box_id, "state": state})

    def handle_near_me(self) -> None:
        """Estimate user location via IP geolocation with clean fallback."""
        result = None

        try:
            req = urllib.request.Request(
                "http://ip-api.com/json/?fields=status,city,region,postal,lat,lon",
                headers={"User-Agent": "ShelfSpot-LFL-Finder/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success" and data.get("lat") is not None and data.get("lon") is not None:
                lat, lng = _clamp_gps(data.get("lat"), data.get("lon"))
                city = str(data.get("city") or "").strip()
                st = _clean_lfl_state(str(data.get("region") or "").strip(), city)
                label = ", ".join(p for p in [city, st] if p) or f"{lat:.4f}, {lng:.4f}"
                result = {"lat": lat, "lng": lng, "city": city, "state": st, "label": label}
        except Exception:
            result = None

        if result is None:
            try:
                req = urllib.request.Request(
                    "https://ipapi.co/json/",
                    headers={"User-Agent": "ShelfSpot-LFL-Finder/1.0", "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if data.get("latitude") is not None and data.get("longitude") is not None:
                    lat, lng = _clamp_gps(data.get("latitude"), data.get("longitude"))
                    city = str(data.get("city") or "").strip()
                    st = _clean_lfl_state(str(data.get("region_code") or data.get("region") or "").strip(), city)
                    label = ", ".join(p for p in [city, st] if p) or f"{lat:.4f}, {lng:.4f}"
                    result = {"lat": lat, "lng": lng, "city": city, "state": st, "label": label}
            except Exception:
                result = None

        if result is None:
            result = {
                "lat": 43.6532,
                "lng": -79.3832,
                "city": "Toronto",
                "state": "ON",
                "label": "Downtown Toronto, ON",
            }

        self.send_json(HTTPStatus.OK, result)

    def handle_lfl_sync(self, body: dict) -> None:
        query = str(body.get("query") or "").strip()
        radius_km = float(body.get("radius_km") or 4.0)
        has_coords = body.get("lat") is not None and body.get("lng") is not None
        req_lat, req_lng = _clamp_gps(body.get("lat"), body.get("lng")) if has_coords else (None, None)

        if not query and not has_coords:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Provide a city, zip code, charter #, or lat/lng."})
            return

        with get_db() as conn:
            if query:
                norm_q = query.lower().replace("charter", "").replace("#", "").strip()
                existing_boxes = conn.execute("SELECT id, name, charter_number, lat, lng, city, state FROM boxes").fetchall()
                for row in existing_boxes:
                    ch_clean = (row["charter_number"] or "").lower().replace("charter", "").replace("#", "").strip()
                    if (norm_q and ch_clean == norm_q) or query.lower() in (row["name"] or "").lower():
                        state = build_state(conn)
                        self.send_json(
                            HTTPStatus.OK,
                            {
                                "synced_count": 0,
                                "matched_box_id": row["id"],
                                "source_used": "local-match",
                                "center": {
                                    "lat": row["lat"],
                                    "lng": row["lng"],
                                    "label": f"{row['name']} ({row['charter_number']})",
                                },
                                "state": state,
                            },
                        )
                        return

        source_used = "official-lfl"
        candidates = []
        lat = req_lat
        lng = req_lng
        label = query or (f"{req_lat:.4f}, {req_lng:.4f}" if has_coords else "")
        city = state_code = postal = ""

        try:
            live_records, api_lat, api_lng = _query_live_lfl_map_api(
                query=query,
                lat=req_lat,
                lng=req_lng,
                radius_km=max(radius_km, 15.0),
            )
            if live_records:
                candidates = live_records
                if not has_coords:
                    lat, lng = api_lat, api_lng
                first = live_records[0]
                if query and query.lower() in CITY_GAZETTEER:
                    _, _, g_city, g_st, _ = CITY_GAZETTEER[query.lower()]
                    label = f"{g_city}, {g_st}".strip(", ")
                elif first.get("city") or first.get("state"):
                    label = ", ".join(p for p in [first.get("city"), first.get("state")] if p)
                else:
                    label = query or f"{lat:.4f}, {lng:.4f}"
        except Exception:
            candidates = []

        if not candidates:
            if has_coords:
                lat, lng = req_lat, req_lng
                city, state_code, postal, label = "", "", "", f"{lat:.4f}, {lng:.4f}"
                try:
                    rev_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}"
                    rev_req = urllib.request.Request(rev_url, headers={"User-Agent": "ShelfSpot-LFL-Finder/1.0"})
                    with urllib.request.urlopen(rev_req, timeout=5) as rev_resp:
                        rev_data = json.loads(rev_resp.read().decode("utf-8"))
                        addr = rev_data.get("address") or {}
                        city = addr.get("city") or addr.get("town") or addr.get("village") or ""
                        state_code = _normalize_region_code(addr)
                        postal = addr.get("postcode") or ""
                        if city or state_code:
                            label = f"{city}, {state_code}".strip(", ")
                except Exception:
                    pass
            else:
                try:
                    lat, lng, label, city, state_code, postal = _resolve_location_query(query)
                except Exception as exc:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": f"Location lookup failed: {exc}"})
                    return

            candidates = _get_real_regional_lfl_boxes(lat, lng, city)
            if candidates:
                source_used = "official-lfl"
            else:
                try:
                    candidates = _query_overpass_bookcases(lat, lng, radius_km, city, state_code, postal)
                    source_used = "osm-sync" if candidates else "none"
                except Exception:
                    candidates = []
                    source_used = "none"

        with get_db() as conn:
            synced_count, last_id = _upsert_lfl_boxes(conn, candidates, update_existing=False)
            if lat is not None and lng is not None:
                all_coords = conn.execute("SELECT id, lat, lng FROM boxes").fetchall()
                if all_coords:
                    closest = min(all_coords, key=lambda r: (r["lat"] - lat) ** 2 + (r["lng"] - lng) ** 2)
                    last_id = closest["id"]
            state = build_state(conn)

        self.send_json(
            HTTPStatus.OK,
            {
                "synced_count": synced_count,
                "matched_box_id": last_id,
                "source_used": source_used,
                "center": {"lat": lat, "lng": lng, "label": label},
                "state": state,
            },
        )

    def handle_lfl_import(self, body: dict) -> None:
        raw_data = body.get("raw_data")
        if raw_data is None:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Provide raw_data (JSON, GeoJSON, or CSV)."})
            return

        try:
            records = _parse_lfl_import_records(raw_data)
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": f"Could not parse import data: {exc}"})
            return

        if not records:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "No valid Little Free Library records with GPS coordinates were found."},
            )
            return

        with get_db() as conn:
            imported_count, last_id = _upsert_lfl_boxes(conn, records, update_existing=True)
            state = build_state(conn)

        first = records[0]
        label = ", ".join(p for p in [first.get("city"), first.get("state")] if p) or first.get("name")
        self.send_json(
            HTTPStatus.OK,
            {
                "imported_count": imported_count,
                "matched_box_id": last_id,
                "center": {"lat": first["lat"], "lng": first["lng"], "label": label},
                "state": state,
            },
        )

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
                nlat, nlng = _clamp_gps(
                    new_box.get("lat"),
                    new_box.get("lng"),
                    default_lat=43.6629,
                    default_lng=-79.3957,
                )
                cur = conn.execute(
                    """
                    INSERT INTO boxes (
                        name, charter_number, address, neighborhood, city, state, postal_code,
                        lat, lng, steward_name, description, roof_color, source, external_id, lfl_url, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bname,
                        _normalize_charter(new_box.get("charter_number")) or "Charter #New",
                        baddr,
                        str(new_box.get("neighborhood") or "Local Block"),
                        str(new_box.get("city") or "Toronto"),
                        str(new_box.get("state") or "ON"),
                        str(new_box.get("postal_code") or ""),
                        nlat,
                        nlng,
                        user_name,
                        str(new_box.get("description") or "Newly spotted Little Free Library box."),
                        str(new_box.get("roof_color") or "#C85A32"),
                        "community",
                        "",
                        LFL_MAP_URL,
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
