# ShelfSpot — Little Free Library Book Finder

A mobile-first web app for snapping photos of Little Free Library boxes, detecting book spines with AI, browsing a neighborhood photo feed, searching a global book index, and exploring nearby boxes on an interactive map.

## Features

- **Photo Check-In Feed**: Chronological community snapshots of Little Free Library boxes with toggleable spine bounding-box overlays and clickable book chips.
- **Global Book Index**: Real-time search across book titles, authors, genres, and boxes, availability status updates (`Available` / `Picked Up`), shelf-photo inspection, and direct map links.
- **Interactive Neighborhood Map**: Pan-and-zoom SVG neighborhood map with Little Free Library pins showing available book counts, box inventory drawers, and new-box pin placement.
- **Snap & Index Workflow**: Upload a photo, capture via live camera (`getUserMedia`), or test with built-in demo shelf photos, then review and edit detected spines before publishing.
- **AI Provider Support**: Configured for the **DeepSeek API** by default, with optional **Google Gemini API** support and an offline built-in spine detector fallback so the app works out of the box.

## Quick Start

Requires Python 3.9+ (uses Python's built-in `http.server` and `sqlite3`, with zero external package dependencies).

```bash
python3 server.py
```

Open `http://127.0.0.1:8765` in your browser. On first launch, `server.py` initializes `data/bookfinder.db` with 6 sample Little Free Library boxes, 6 photo check-ins, and 28 indexed books.

## Optional AI Configuration

You can configure your API key either in the in-app **AI Settings** modal or via environment variables before running `python3 server.py`:

- **DeepSeek (default)**:
  - `DEEPSEEK_API_KEY` — Your DeepSeek API key (`sk-...`)
  - `DEEPSEEK_MODEL` — Optional (defaults to `deepseek-chat`)
  - `DEEPSEEK_BASE_URL` — Optional (defaults to `https://api.deepseek.com/chat/completions`)
- **Google Gemini (optional)**:
  - `GEMINI_API_KEY` — Your Gemini API key (`AIza...`)

## Project Structure

- `server.py` — HTTP server, REST API endpoints (`/api/state`, `/api/analyze-shelf`, `/api/checkins`, `/api/books/<id>/status`, `/api/boxes`), SQLite schema/seeding, and AI integrations
- `public/index.html` — Mobile-first application shell and modals
- `public/styles.css` — Responsive styling and bounding-box overlays
- `public/app.js` — Client state, feed/index/map rendering, camera/upload scanner workflow
- `public/sample-shelves.js` — Canvas shelf photo renderer for seeded check-ins and demo presets
- `package.json` — Convenience start script (`npm start`)
