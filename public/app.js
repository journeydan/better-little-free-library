(function () {
  const GENRES = [
    "All Genres",
    "Fiction",
    "Sci-Fi & Fantasy",
    "Mystery",
    "Non-Fiction",
    "Children's",
    "Cooking",
  ];

  const state = {
    activeView: "feed",
    boxes: [],
    checkins: [],
    books: [],
    stats: { available_books: 0, total_books: 0, active_boxes: 0, total_checkins: 0 },
    hasEnvGeminiKey: false,
    hasEnvDeepseekKey: false,
    aiProvider: localStorage.getItem("shelfspot_ai_provider") || "deepseek",
    deepseekKey: localStorage.getItem("shelfspot_deepseek_key") || "",
    deepseekModel: localStorage.getItem("shelfspot_deepseek_model") || "deepseek-chat",
    deepseekBaseUrl:
      localStorage.getItem("shelfspot_deepseek_base_url") || "https://api.deepseek.com/chat/completions",
    apiKey: localStorage.getItem("shelfspot_gemini_key") || "",

    // Feed filters & UI state
    feedSearch: "",
    feedBoxId: "",
    hiddenOverlays: new Set(),
    activeFeedSpines: {}, // checkinId -> bookId
    highlightCheckinId: null,

    // Book Index filters
    indexSearch: "",
    indexGenre: "All Genres",
    indexStatus: "available",
    indexSort: "newest",

    // Map state
    selectedBoxId: null,
    activeRegion: "",
    mapCenter: { lat: 47.648, lng: -122.342, label: "Seattle, WA" },
    placingBoxMode: false,
    pendingNewBoxCoords: { lat: 47.648, lng: -122.342 },
    mapViewBox: { x: 0, y: 0, w: 1000, h: 720 },
    mapDrag: null,

    // Snap / Upload modal state
    snapPhotoData: "",
    snapPresetId: "",
    snapAiSource: "deepseek-api",
    snapBooks: [],
    activeReviewIdx: null,
    preselectedBoxId: null,
    cameraStream: null,
  };

  // --- Utilities ---
  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function timeAgo(isoStr) {
    if (!isoStr) return "just now";
    const diffSec = Math.max(0, Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000));
    if (diffSec < 60) return "just now";
    const mins = Math.floor(diffSec / 60);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  function showToast(message) {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.remove();
    }, 3400);
  }

  async function apiGet(url) {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  async function apiPost(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  function applyStatePayload(payload) {
    state.boxes = payload.boxes || [];
    state.checkins = payload.checkins || [];
    state.books = payload.books || [];
    state.stats = payload.stats || state.stats;
    state.hasEnvGeminiKey = Boolean(payload.hasEnvGeminiKey);
    state.hasEnvDeepseekKey = Boolean(payload.hasEnvDeepseekKey);

    if (!state.selectedBoxId && state.boxes.length > 0) {
      state.selectedBoxId = state.boxes[0].id;
    } else if (state.selectedBoxId && !state.boxes.some((b) => b.id === state.selectedBoxId)) {
      state.selectedBoxId = state.boxes[0]?.id || null;
    }

    if (!state.activeRegion && state.boxes.length > 0) {
      const b0 = state.boxes[0];
      state.activeRegion = getBoxRegionLabel(b0);
      state.mapCenter = { lat: b0.lat, lng: b0.lng, label: state.activeRegion };
    }

    renderAll();
  }

  async function loadInitialState() {
    try {
      const payload = await apiGet("/api/state");
      applyStatePayload(payload);
    } catch (err) {
      showToast(`Failed to load library data: ${err.message}`);
    }
  }

  // --- Navigation ---
  function switchView(viewName) {
    state.activeView = viewName;
    document.querySelectorAll(".view-section").forEach((el) => {
      el.classList.toggle("active", el.id === `view-${viewName}`);
    });
    document.querySelectorAll(".nav-tab, .mobile-nav-btn[data-view]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.view === viewName);
    });
    if (viewName === "map") {
      renderMapView();
    }
  }

  function getBoxRegionLabel(box) {
    if (!box) return "Seattle, WA";
    const city = (box.city || "").trim();
    const st = (box.state || "").trim();
    if (city && st) return `${city}, ${st}`;
    if (city) return city;
    return box.neighborhood || "Local Region";
  }

  function jumpToBoxOnMap(boxId) {
    state.selectedBoxId = boxId;
    const target = state.boxes.find((b) => b.id === boxId);
    if (target) {
      state.activeRegion = getBoxRegionLabel(target);
      state.mapCenter = { lat: target.lat, lng: target.lng, label: state.activeRegion };
      state.mapViewBox = { x: 0, y: 0, w: 1000, h: 720 };
    }
    switchView("map");
    renderMapView();
  }

  // --- Render Header & Stats ---
  function renderHeaderStats() {
    document.getElementById("statAvailable").textContent = state.stats.available_books ?? 0;
    document.getElementById("statBoxes").textContent = state.stats.active_boxes ?? 0;
    document.getElementById("statCheckins").textContent = state.stats.total_checkins ?? 0;

    const dot = document.getElementById("aiStatusDot");
    const hasActiveKey =
      state.aiProvider === "deepseek"
        ? Boolean(state.deepseekKey || state.hasEnvDeepseekKey)
        : Boolean(state.apiKey || state.hasEnvGeminiKey);
    dot.classList.toggle("connected", hasActiveKey);
  }

  // --- Render Photo Check-In Feed ---
  function renderFeedBoxOptions() {
    const select = document.getElementById("feedBoxFilter");
    const current = state.feedBoxId;
    select.innerHTML = `<option value="">All Library Boxes</option>` +
      state.boxes
        .map((b) => `<option value="${b.id}">${escapeHtml(b.name)} (${b.available_count})</option>`)
        .join("");
    select.value = current;
  }

  function renderFeedView() {
    renderFeedBoxOptions();
    const container = document.getElementById("feedList");
    const q = state.feedSearch.trim().toLowerCase();

    const filtered = state.checkins.filter((ch) => {
      if (state.feedBoxId && String(ch.box_id) !== String(state.feedBoxId)) return false;
      if (!q) return true;
      const inMeta =
        (ch.box_name || "").toLowerCase().includes(q) ||
        (ch.neighborhood || "").toLowerCase().includes(q) ||
        (ch.note || "").toLowerCase().includes(q) ||
        (ch.user_name || "").toLowerCase().includes(q);
      const inBooks = (ch.books || []).some(
        (bk) =>
          (bk.title || "").toLowerCase().includes(q) ||
          (bk.author || "").toLowerCase().includes(q) ||
          (bk.genre || "").toLowerCase().includes(q)
      );
      return inMeta || inBooks;
    });

    if (filtered.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <h3>No matching check-ins yet</h3>
          <p>Try clearing your filter or snap a new Little Free Library box photo!</p>
        </div>
      `;
      return;
    }

    container.innerHTML = filtered
      .map((ch) => {
        const photoUrl = window.ShelfPhotos.resolveCheckinPhoto(ch);
        const overlayHidden = state.hiddenOverlays.has(ch.id);
        const activeBookId = state.activeFeedSpines[ch.id];
        const books = ch.books || [];
        const availableHere = books.filter((b) => b.status === "available").length;
        const selectedBook = books.find((b) => b.id === activeBookId);

        const bboxesHtml = books
          .map((bk, idx) => {
            if (!Array.isArray(bk.bbox) || bk.bbox.length !== 4) return "";
            const [ymin, xmin, ymax, xmax] = bk.bbox;
            const isActive = bk.id === activeBookId;
            const isPicked = bk.status === "picked_up";
            return `
              <div
                class="spine-bbox ${isActive ? "active" : ""} ${isPicked ? "picked" : ""}"
                data-checkin-id="${ch.id}"
                data-book-id="${bk.id}"
                style="top:${ymin}%;left:${xmin}%;height:${Math.max(5, ymax - ymin)}%;width:${Math.max(4, xmax - xmin)}%;"
                title="${escapeHtml(bk.title)} — ${escapeHtml(bk.author)}"
              >
                <span class="spine-bbox-tag">${idx + 1}</span>
                <span class="spine-bbox-tooltip">${escapeHtml(bk.title)}</span>
              </div>
            `;
          })
          .join("");

        const chipsHtml = books
          .map((bk, idx) => {
            const isActive = bk.id === activeBookId;
            const isPicked = bk.status === "picked_up";
            return `
              <button
                type="button"
                class="book-chip ${isActive ? "active" : ""} ${isPicked ? "picked-up" : ""}"
                data-action="select-feed-book"
                data-checkin-id="${ch.id}"
                data-book-id="${bk.id}"
              >
                <span class="chip-swatch" style="background:${escapeHtml(bk.spine_color || "#3B6E5C")}"></span>
                <span class="chip-num">#${idx + 1}</span>
                <span class="chip-title">${escapeHtml(bk.title)}</span>
              </button>
            `;
          })
          .join("");

        const selectedDetailHtml = selectedBook
          ? `
            <div class="drawer-book-row">
              <div class="drawer-book-main">
                <span class="chip-swatch" style="background:${escapeHtml(selectedBook.spine_color || "#3B6E5C")}"></span>
                <div>
                  <div class="drawer-book-title">${escapeHtml(selectedBook.title)}</div>
                  <div class="drawer-book-author">${escapeHtml(selectedBook.author)} · ${escapeHtml(selectedBook.genre)}</div>
                </div>
              </div>
              <div style="display:flex;gap:6px;flex-shrink:0;">
                <button class="btn btn-secondary btn-sm" type="button" data-action="toggle-book-status" data-book-id="${selectedBook.id}">
                  ${selectedBook.status === "available" ? "Mark Picked Up" : "Mark Available"}
                </button>
              </div>
            </div>
          `
          : "";

        return `
          <article class="feed-card ${state.highlightCheckinId === ch.id ? "highlight-pulse" : ""}" id="checkin-card-${ch.id}">
            <div class="feed-card-head">
              <div>
                <button class="box-link-btn" type="button" data-action="goto-box" data-box-id="${ch.box_id}">
                  ${escapeHtml(ch.box_name)}
                </button>
                <div class="feed-meta-line">
                  ${escapeHtml(ch.charter_number)} · ${escapeHtml(ch.neighborhood)}${ch.city ? `, ${escapeHtml(ch.city)}` : ""} · Spotted ${timeAgo(ch.created_at)} by ${escapeHtml(ch.user_name)}
                </div>
              </div>
              <span class="badge badge-forest">${availableHere} available</span>
            </div>

            <div class="photo-stage">
              <img src="${photoUrl}" alt="Little Free Library shelf at ${escapeHtml(ch.box_name)}" />
              <div class="photo-overlay-controls">
                <button
                  class="overlay-toggle-btn ${overlayHidden ? "off" : ""}"
                  type="button"
                  data-action="toggle-overlay"
                  data-checkin-id="${ch.id}"
                >
                  Spine Overlay: ${overlayHidden ? "OFF" : "ON"}
                </button>
              </div>
              <div class="bbox-layer ${overlayHidden ? "hidden-boxes" : ""}">
                ${bboxesHtml}
              </div>
            </div>

            <div class="feed-card-body">
              ${ch.note ? `<p class="feed-note">“${escapeHtml(ch.note)}”</p>` : ""}
              <div class="feed-books-chips">
                ${chipsHtml || `<span class="feed-meta-line">No titles tagged yet.</span>`}
              </div>
              ${selectedDetailHtml}
              <div class="feed-card-footer">
                <span>AI Index: ${escapeHtml(ch.ai_source || "deepseek-api")}</span>
                <button class="btn btn-ghost btn-sm" type="button" data-action="goto-box" data-box-id="${ch.box_id}">
                  Locate on Map →
                </button>
              </div>
            </div>
          </article>
        `;
      })
      .join("");
  }

  // --- Render Global Book Index ---
  function renderGenrePills() {
    const container = document.getElementById("genreFilterPills");
    container.innerHTML = GENRES.map((genre) => {
      const count =
        genre === "All Genres"
          ? state.books.length
          : state.books.filter((b) => b.genre === genre).length;
      return `
        <button
          type="button"
          class="genre-pill ${state.indexGenre === genre ? "active" : ""}"
          data-genre="${escapeHtml(genre)}"
        >
          ${escapeHtml(genre)} (${count})
        </button>
      `;
    }).join("");
  }

  function renderBookIndexView() {
    renderGenrePills();
    const q = state.indexSearch.trim().toLowerCase();

    let items = state.books.filter((bk) => {
      if (state.indexGenre !== "All Genres" && bk.genre !== state.indexGenre) return false;
      if (state.indexStatus === "available" && bk.status !== "available") return false;
      if (state.indexStatus === "picked_up" && bk.status !== "picked_up") return false;
      if (!q) return true;
      return (
        (bk.title || "").toLowerCase().includes(q) ||
        (bk.author || "").toLowerCase().includes(q) ||
        (bk.genre || "").toLowerCase().includes(q) ||
        (bk.box_name || "").toLowerCase().includes(q) ||
        (bk.box_neighborhood || "").toLowerCase().includes(q)
      );
    });

    if (state.indexSort === "title") {
      items = [...items].sort((a, b) => (a.title || "").localeCompare(b.title || ""));
    } else if (state.indexSort === "box") {
      items = [...items].sort((a, b) => (a.box_name || "").localeCompare(b.box_name || ""));
    }

    document.getElementById("indexCountBar").textContent = `Showing ${items.length} of ${state.books.length} indexed books`;

    const grid = document.getElementById("bookIndexGrid");
    if (items.length === 0) {
      grid.innerHTML = `
        <div class="empty-state">
          <h3>No matching books in the index</h3>
          <p>Try a broader search term or switch status filter to “All Spotted Books”.</p>
        </div>
      `;
      return;
    }

    grid.innerHTML = items
      .map((bk) => {
        const isPicked = bk.status === "picked_up";
        const confPct = Math.round((bk.confidence || 0.95) * 100);
        return `
          <article class="book-card ${isPicked ? "is-picked" : ""}">
            <div class="book-spine-badge" style="background:${escapeHtml(bk.spine_color || "#3B6E5C")}"></div>
            <div class="book-card-content">
              <div>
                <div class="book-card-top">
                  <div>
                    <h3 class="book-title">${escapeHtml(bk.title)}</h3>
                    <div class="book-author">by ${escapeHtml(bk.author)}</div>
                  </div>
                  <span class="badge ${isPicked ? "badge-picked" : "badge-forest"}">
                    ${isPicked ? "Picked Up" : "Available"}
                  </span>
                </div>
                <div class="book-tags">
                  <span class="badge badge-neutral">${escapeHtml(bk.genre)}</span>
                  <span class="badge badge-terracotta">${confPct}% spine match</span>
                </div>
              </div>

              <div class="book-location-line">
                In <strong>${escapeHtml(bk.box_name)}</strong> · ${escapeHtml(bk.box_neighborhood)} · ${timeAgo(bk.spotted_at)}
              </div>

              <div class="book-card-actions">
                <button class="btn btn-secondary btn-sm" type="button" data-action="inspect-book-photo" data-checkin-id="${bk.checkin_id}" data-book-id="${bk.id}">
                  Shelf Photo
                </button>
                <button class="btn btn-secondary btn-sm" type="button" data-action="goto-box" data-box-id="${bk.box_id}">
                  Find on Map
                </button>
                <button class="btn btn-ghost btn-sm" type="button" data-action="toggle-book-status" data-book-id="${bk.id}">
                  ${isPicked ? "Still Here" : "Mark Picked Up"}
                </button>
              </div>
            </div>
          </article>
        `;
      })
      .join("");
  }

  // --- Render Interactive Map View ---
  function getVisibleMapBoxes() {
    if (!state.boxes.length) return [];
    if (state.activeRegion) {
      const matched = state.boxes.filter((b) => getBoxRegionLabel(b) === state.activeRegion);
      if (matched.length > 0) return matched;
    }
    const cLat = state.mapCenter?.lat ?? state.boxes[0].lat;
    const cLng = state.mapCenter?.lng ?? state.boxes[0].lng;
    const nearby = state.boxes.filter(
      (b) => Math.abs(b.lat - cLat) <= 0.35 && Math.abs(b.lng - cLng) <= 0.45
    );
    return nearby.length > 0 ? nearby : state.boxes;
  }

  function lngToWorldX(lng, z) {
    return ((lng + 180) / 360) * 256 * Math.pow(2, z);
  }

  function latToWorldY(lat, z) {
    const clamped = Math.max(-85.0511, Math.min(85.0511, lat));
    const rad = (clamped * Math.PI) / 180;
    return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * 256 * Math.pow(2, z);
  }

  function worldXToLng(wx, z) {
    return (wx / (256 * Math.pow(2, z))) * 360 - 180;
  }

  function worldYToLat(wy, z) {
    const n = Math.PI - (2 * Math.PI * wy) / (256 * Math.pow(2, z));
    return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  }

  function getGeoProjection(visibleBoxes) {
    const pts = visibleBoxes.length ? visibleBoxes : [{ lat: state.mapCenter.lat, lng: state.mapCenter.lng }];
    let minLat = Infinity;
    let maxLat = -Infinity;
    let minLng = Infinity;
    let maxLng = -Infinity;
    for (const b of pts) {
      minLat = Math.min(minLat, b.lat);
      maxLat = Math.max(maxLat, b.lat);
      minLng = Math.min(minLng, b.lng);
      maxLng = Math.max(maxLng, b.lng);
    }
    const centerLat = (minLat + maxLat) / 2;
    const centerLng = (minLng + maxLng) / 2;

    let zoom = 14;
    if (pts.length > 1) {
      zoom = 11;
      for (let z = 15; z >= 11; z--) {
        const dx = Math.abs(lngToWorldX(maxLng, z) - lngToWorldX(minLng, z));
        const dy = Math.abs(latToWorldY(minLat, z) - latToWorldY(maxLat, z));
        if (dx <= 760 && dy <= 520) {
          zoom = z;
          break;
        }
      }
    }

    const centerWx = lngToWorldX(centerLng, zoom);
    const centerWy = latToWorldY(centerLat, zoom);
    const originWx = centerWx - 500;
    const originWy = centerWy - 360;

    return {
      zoom,
      centerLat,
      centerLng,
      centerWx,
      centerWy,
      originWx,
      originWy,
      project(lat, lng) {
        return {
          x: 500 + (lngToWorldX(lng, zoom) - centerWx),
          y: 360 + (latToWorldY(lat, zoom) - centerWy),
        };
      },
      unproject(x, y) {
        return {
          lat: Number(worldYToLat(centerWy + (y - 360), zoom).toFixed(5)),
          lng: Number(worldXToLng(centerWx + (x - 500), zoom).toFixed(5)),
        };
      },
    };
  }

  function formatSourceBadge(source) {
    if (source === "official-lfl") return `<span class="badge badge-forest">Official LFL</span>`;
    if (source === "official-lfl-catalog") return `<span class="badge badge-forest">LFL Catalog</span>`;
    if (source === "osm-sync") return `<span class="badge badge-terracotta">OSM Sync</span>`;
    return `<span class="badge badge-neutral">Community</span>`;
  }

  function renderMapRegionPills() {
    const container = document.getElementById("mapRegionPills");
    if (!container) return;
    const counts = new Map();
    for (const b of state.boxes) {
      const label = getBoxRegionLabel(b);
      counts.set(label, (counts.get(label) || 0) + 1);
    }
    container.innerHTML = Array.from(counts.entries())
      .map(([label, cnt]) => {
        const active = state.activeRegion === label;
        return `
          <button
            type="button"
            class="genre-pill ${active ? "active" : ""}"
            data-region="${escapeHtml(label)}"
          >
            ${escapeHtml(label)} (${cnt})
          </button>
        `;
      })
      .join("");
  }

  function renderMapSvg() {
    const svg = document.getElementById("neighborhoodMapSvg");
    const vb = state.mapViewBox;
    svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);

    const visibleBoxes = getVisibleMapBoxes();
    const proj = getGeoProjection(visibleBoxes);
    state.lastGeoProjection = proj;

    const z = proj.zoom;
    const nTiles = Math.pow(2, z);
    const minTx = Math.floor(proj.originWx / 256);
    const maxTx = Math.floor((proj.originWx + 1000) / 256);
    const minTy = Math.max(0, Math.floor(proj.originWy / 256));
    const maxTy = Math.min(nTiles - 1, Math.floor((proj.originWy + 720) / 256));

    let tilesHtml = "";
    for (let tx = minTx; tx <= maxTx; tx++) {
      const wrappedTx = ((tx % nTiles) + nTiles) % nTiles;
      const tileX = tx * 256 - proj.originWx;
      for (let ty = minTy; ty <= maxTy; ty++) {
        const tileY = ty * 256 - proj.originWy;
        tilesHtml += `<image href="https://tile.openstreetmap.org/${z}/${wrappedTx}/${ty}.png" x="${tileX}" y="${tileY}" width="256.5" height="256.5" preserveAspectRatio="none" />`;
      }
    }

    // 1 km scale bar width in Web Mercator px
    const metersPerPx = (156543.03392 * Math.cos((proj.centerLat * Math.PI) / 180)) / Math.pow(2, z);
    const kmPx = Math.max(40, Math.min(260, 1000 / Math.max(0.1, metersPerPx)));
    const regionTitle = state.activeRegion || state.mapCenter?.label || "Little Free Library Map";

    const staticBackdrop = `
      <defs>
        <pattern id="mapMinorGrid" width="50" height="50" patternUnits="userSpaceOnUse">
          <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#EAE2D1" stroke-width="0.7" />
        </pattern>
      </defs>

      <rect x="0" y="0" width="1000" height="720" fill="#F4EFE4" />
      <rect x="0" y="0" width="1000" height="720" fill="url(#mapMinorGrid)" />

      <!-- Real OpenStreetMap Street Tiles -->
      <g>${tilesHtml}</g>

      <!-- Subtle Region Badge + Scale Bar + Compass -->
      <g transform="translate(18, 16)">
        <rect x="0" y="0" width="${Math.max(150, regionTitle.length * 8.5 + 24)}" height="28" rx="14" fill="rgba(255,255,255,0.92)" stroke="#D9CEBE" />
        <text x="12" y="18" fill="#214432" font-size="12" font-weight="700">${escapeHtml(regionTitle)} · z${z}</text>
      </g>

      <g transform="translate(24, 678)">
        <rect x="-8" y="-22" width="${kmPx + 24}" height="34" rx="8" fill="rgba(255,255,255,0.9)" stroke="#D9CEBE" />
        <path d="M 0 0 L 0 -6 M ${kmPx} 0 L ${kmPx} -6 M 0 -3 L ${kmPx} -3" stroke="#2D5A43" stroke-width="2.5" fill="none" />
        <text x="${kmPx / 2}" y="-9" text-anchor="middle" fill="#241E19" font-size="11" font-weight="700">1 km</text>
      </g>

      <g transform="translate(955, 675)">
        <circle cx="0" cy="0" r="18" fill="rgba(255,255,255,0.92)" stroke="#D9CEBE" />
        <path d="M 0 -12 L 5 4 L 0 0 L -5 4 Z" fill="#C85A32" />
        <text x="0" y="13" text-anchor="middle" fill="#241E19" font-size="9" font-weight="700">N</text>
      </g>
    `;

    const pinsHtml = visibleBoxes
      .map((box) => {
        const pt = proj.project(box.lat, box.lng);
        const selected = box.id === state.selectedBoxId;
        const roof = box.roof_color || "#C85A32";
        return `
          <g class="map-pin-group" data-box-id="${box.id}" transform="translate(${pt.x}, ${pt.y})">
            ${selected ? `<circle cx="0" cy="-12" r="34" fill="#D96B43" opacity="0.22" />` : ""}
            <ellipse cx="0" cy="4" rx="14" ry="5" fill="rgba(0,0,0,0.22)" />
            <g transform="scale(${selected ? 1.18 : 1})">
              <rect x="-15" y="-22" width="30" height="23" rx="3" fill="#FAF6F0" stroke="#3E2B1D" stroke-width="2.2" />
              <path d="M -20 -20 L 0 -37 L 20 -20 Z" fill="${escapeHtml(roof)}" stroke="#3E2B1D" stroke-width="2" stroke-linejoin="round" />
              <rect x="-9" y="-17" width="5" height="13" rx="1" fill="#2D5A43" />
              <rect x="-2" y="-18" width="5" height="14" rx="1" fill="#D96B43" />
              <rect x="5" y="-16" width="5" height="12" rx="1" fill="#3D6B8E" />
              <circle cx="17" cy="-29" r="11" fill="${selected ? "#D96B43" : "#2D5A43"}" stroke="#FFFFFF" stroke-width="2" />
              <text x="17" y="-25" text-anchor="middle" fill="#FFFFFF" font-size="11" font-weight="700">${box.available_count}</text>
            </g>
            <rect x="-74" y="10" width="148" height="20" rx="10" fill="rgba(255,255,255,0.94)" stroke="${selected ? "#D96B43" : "#D9CEBE"}" stroke-width="1.2" />
            <text x="0" y="24" text-anchor="middle" fill="#241E19" font-size="11" font-weight="700">
              ${escapeHtml(box.name.length > 21 ? box.name.slice(0, 19) + "…" : box.name)}
            </text>
          </g>
        `;
      })
      .join("");

    svg.innerHTML = staticBackdrop + pinsHtml;
  }

  function renderMapDrawer() {
    const drawer = document.getElementById("mapBoxDrawer");
    const box = state.boxes.find((b) => b.id === state.selectedBoxId);
    if (!box) {
      drawer.innerHTML = `<div class="empty-state">Select a library pin on the map to view its inventory.</div>`;
      return;
    }

    const latest = box.latest_checkin;
    const latestUrl = latest
      ? window.ShelfPhotos.resolveCheckinPhoto({ ...latest, roof_color: box.roof_color, charter_number: box.charter_number })
      : "";
    const availableBooks = (box.books || []).filter((bk) => bk.status === "available");
    const cityLine = [box.city, box.state, box.postal_code].filter(Boolean).join(", ");
    const lflLink = box.lfl_url || "https://littlefreelibrary.org/map/";
    const gmapsLink = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${box.lat},${box.lng}`)}`;

    drawer.innerHTML = `
      <div class="drawer-header">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
          <div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:5px;">
              ${formatSourceBadge(box.source)}
              <span class="badge badge-neutral">${escapeHtml(box.charter_number)}</span>
            </div>
            <h2>${escapeHtml(box.name)}</h2>
            <div class="drawer-meta">${escapeHtml(box.address)} · ${escapeHtml(box.neighborhood)}${cityLine ? ` (${escapeHtml(cityLine)})` : ""}</div>
            <div class="drawer-meta">GPS: ${Number(box.lat).toFixed(4)}, ${Number(box.lng).toFixed(4)} · Steward: ${escapeHtml(box.steward_name || "Community")}</div>
          </div>
          <span class="badge badge-forest">${box.available_count} available</span>
        </div>
      </div>

      <p class="drawer-desc">${escapeHtml(box.description || "Community Little Free Library box.")}</p>

      <div class="drawer-actions-row">
        <button class="btn btn-primary" style="flex:1;" type="button" data-action="snap-for-box" data-box-id="${box.id}">
          📸 Check In Photo Here
        </button>
        <a class="btn btn-secondary btn-sm" href="${escapeHtml(lflLink)}" target="_blank" rel="noopener">
          Official LFL Map ↗
        </a>
        <a class="btn btn-ghost btn-sm" href="${gmapsLink}" target="_blank" rel="noopener">
          Directions ↗
        </a>
      </div>

      ${
        latest
          ? `
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <strong style="font-size:0.86rem;">Latest Shelf Snapshot (${timeAgo(latest.created_at)})</strong>
          </div>
          <div class="photo-stage" style="border-radius:10px;">
            <img src="${latestUrl}" alt="Latest shelf at ${escapeHtml(box.name)}" />
          </div>
        </div>
      `
          : `<div class="info-banner">No photo check-ins yet for this Little Free Library box. Snap the first photo to index its books!</div>`
      }

      <div>
        <strong style="font-size:0.9rem;display:block;margin-bottom:8px;">Available Titles (${availableBooks.length})</strong>
        <div class="drawer-book-list">
          ${
            availableBooks.length > 0
              ? availableBooks
                  .map(
                    (bk) => `
                  <div class="drawer-book-row">
                    <div class="drawer-book-main">
                      <span class="chip-swatch" style="background:${escapeHtml(bk.spine_color || "#3B6E5C")}"></span>
                      <div style="min-width:0;">
                        <div class="drawer-book-title">${escapeHtml(bk.title)}</div>
                        <div class="drawer-book-author">${escapeHtml(bk.author)} · ${escapeHtml(bk.genre)}</div>
                      </div>
                    </div>
                    <button class="btn btn-ghost btn-sm" type="button" data-action="toggle-book-status" data-book-id="${bk.id}">
                      Picked Up
                    </button>
                  </div>
                `
                  )
                  .join("")
              : `<div class="feed-meta-line">No currently available titles recorded yet.</div>`
          }
        </div>
      </div>
    `;
  }

  function renderMapView() {
    renderMapRegionPills();
    renderMapSvg();
    renderMapDrawer();
  }

  function renderAll() {
    renderHeaderStats();
    renderFeedView();
    renderBookIndexView();
    renderMapView();
  }

  // --- Map Pan / Zoom & Placement ---
  function zoomMap(factor) {
    const vb = state.mapViewBox;
    const nextW = Math.max(360, Math.min(1000, vb.w * factor));
    const nextH = nextW * 0.72;
    const cx = vb.x + vb.w / 2;
    const cy = vb.y + vb.h / 2;
    vb.w = nextW;
    vb.h = nextH;
    vb.x = Math.max(0, Math.min(1000 - nextW, cx - nextW / 2));
    vb.y = Math.max(0, Math.min(720 - nextH, cy - nextH / 2));
    renderMapSvg();
  }

  function resetMap() {
    state.mapViewBox = { x: 0, y: 0, w: 1000, h: 720 };
    renderMapSvg();
  }

  function setAddBoxMode(enabled) {
    state.placingBoxMode = enabled;
    document.getElementById("mapPlacementBanner").classList.toggle("hidden", !enabled);
    document.getElementById("mapViewport").classList.toggle("placing-mode", enabled);
    document.getElementById("toggleAddBoxModeBtn").classList.toggle("active", enabled);
  }

  // --- Book Status & Lightbox ---
  async function toggleBookStatus(bookId) {
    try {
      const data = await apiPost(`/api/books/${bookId}/status`, {});
      applyStatePayload(data.state);
      showToast(data.status === "picked_up" ? "Marked book as Picked Up" : "Marked book as Available");
    } catch (err) {
      showToast(`Could not update book status: ${err.message}`);
    }
  }

  function openPhotoLightbox(checkinId, highlightBookId) {
    const ch = state.checkins.find((c) => c.id === Number(checkinId));
    if (!ch) return;
    document.getElementById("lightboxTitle").textContent = ch.box_name;
    document.getElementById("lightboxSubtitle").textContent = `${ch.address} · Spotted ${timeAgo(ch.created_at)} by ${ch.user_name}`;
    document.getElementById("lightboxImg").src = window.ShelfPhotos.resolveCheckinPhoto(ch);

    const layer = document.getElementById("lightboxBboxLayer");
    layer.innerHTML = (ch.books || [])
      .map((bk, idx) => {
        if (!Array.isArray(bk.bbox)) return "";
        const [ymin, xmin, ymax, xmax] = bk.bbox;
        const isActive = bk.id === Number(highlightBookId);
        return `
          <div
            class="spine-bbox ${isActive ? "active" : ""}"
            style="top:${ymin}%;left:${xmin}%;height:${Math.max(5, ymax - ymin)}%;width:${Math.max(4, xmax - xmin)}%;"
            title="${escapeHtml(bk.title)} — ${escapeHtml(bk.author)}"
          >
            <span class="spine-bbox-tag">${idx + 1}</span>
            <span class="spine-bbox-tooltip">${escapeHtml(bk.title)}</span>
          </div>
        `;
      })
      .join("");

    document.getElementById("photoLightboxModal").classList.remove("hidden");
  }

  // --- Snap / Upload Photo & AI Vision Review Modal ---
  function stopCamera() {
    if (state.cameraStream) {
      state.cameraStream.getTracks().forEach((t) => t.stop());
      state.cameraStream = null;
    }
    const video = document.getElementById("cameraVideo");
    video.srcObject = null;
    document.getElementById("captureFrameBtn").disabled = true;
  }

  function renderDemoPresets() {
    const grid = document.getElementById("demoPresetsGrid");
    grid.innerHTML = window.ShelfPhotos.DEMO_PRESETS.map((preset) => {
      const thumb = window.ShelfPhotos.renderDemoPresetPhoto(preset.id);
      return `
        <button class="demo-preset-card" type="button" data-preset-id="${preset.id}">
          <img src="${thumb}" alt="${escapeHtml(preset.label)}" />
          <div class="demo-preset-info">
            <div class="demo-preset-title">${escapeHtml(preset.label)}</div>
            <div class="demo-preset-sub">${escapeHtml(preset.subtitle)}</div>
          </div>
        </button>
      `;
    }).join("");
  }

  function openSnapModal(preselectedBoxId = null) {
    state.preselectedBoxId = preselectedBoxId;
    state.snapPhotoData = "";
    state.snapPresetId = "";
    state.snapBooks = [];
    state.activeReviewIdx = null;

    document.getElementById("snapStep1").classList.remove("hidden");
    document.getElementById("snapStep2").classList.add("hidden");
    switchCaptureTab("upload");
    renderDemoPresets();
    document.getElementById("snapModal").classList.remove("hidden");
  }

  function closeSnapModal() {
    stopCamera();
    document.getElementById("snapModal").classList.add("hidden");
  }

  function switchCaptureTab(tabName) {
    document.querySelectorAll(".capture-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.captureTab === tabName);
    });
    document.getElementById("capturePanelUpload").classList.toggle("active", tabName === "upload");
    document.getElementById("capturePanelCamera").classList.toggle("active", tabName === "camera");
    document.getElementById("capturePanelSamples").classList.toggle("active", tabName === "samples");
    if (tabName !== "camera") {
      stopCamera();
    }
  }

  async function startLiveCamera() {
    const fallback = document.getElementById("cameraFallbackMsg");
    const video = document.getElementById("cameraVideo");
    const captureBtn = document.getElementById("captureFrameBtn");
    fallback.classList.add("hidden");
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("Camera API unavailable");
      }
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      state.cameraStream = stream;
      video.srcObject = stream;
      captureBtn.disabled = false;
    } catch (err) {
      fallback.classList.remove("hidden");
      showToast("Could not access camera; you can upload a photo or use a demo shelf.");
    }
  }

  function captureCameraFrame() {
    const video = document.getElementById("cameraVideo");
    const canvas = document.getElementById("cameraCanvas");
    if (!video.videoWidth) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.88);
    stopCamera();
    runShelfAnalysis({ photoData: dataUrl, presetId: "" });
  }

  function handleUploadedFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      runShelfAnalysis({ photoData: reader.result, presetId: "" });
    };
    reader.readAsDataURL(file);
  }

  function populateCheckinBoxSelect(suggestedBoxName = "") {
    const select = document.getElementById("checkinBoxSelect");
    const options = state.boxes.map((b) => `<option value="${b.id}">${escapeHtml(b.name)} (${escapeHtml(b.neighborhood)})</option>`);
    options.push(`<option value="__new__">+ Create a New Library Box</option>`);
    select.innerHTML = options.join("");

    if (state.preselectedBoxId) {
      select.value = String(state.preselectedBoxId);
    } else if (suggestedBoxName) {
      const found = state.boxes.find((b) => b.name === suggestedBoxName);
      if (found) select.value = String(found.id);
    }
    document.getElementById("inlineNewBoxFields").classList.toggle("hidden", select.value !== "__new__");
  }

  function renderReviewBboxesAndRows() {
    document.getElementById("detectedCount").textContent = state.snapBooks.length;

    const bboxLayer = document.getElementById("reviewBboxLayer");
    bboxLayer.innerHTML = state.snapBooks
      .map((bk, idx) => {
        if (!Array.isArray(bk.bbox) || bk.bbox.length !== 4) return "";
        const [ymin, xmin, ymax, xmax] = bk.bbox;
        const isActive = state.activeReviewIdx === idx;
        return `
          <div
            class="spine-bbox ${isActive ? "active" : ""}"
            data-review-idx="${idx}"
            style="top:${ymin}%;left:${xmin}%;height:${Math.max(5, ymax - ymin)}%;width:${Math.max(4, xmax - xmin)}%;"
          >
            <span class="spine-bbox-tag">${idx + 1}</span>
            <span class="spine-bbox-tooltip">${escapeHtml(bk.title || "New Book")}</span>
          </div>
        `;
      })
      .join("");

    const listEl = document.getElementById("detectedBooksList");
    if (state.snapBooks.length === 0) {
      listEl.innerHTML = `<div class="feed-meta-line">No books detected yet. Click "+ Add Book Manually" to enter a title.</div>`;
      return;
    }

    listEl.innerHTML = state.snapBooks
      .map((bk, idx) => {
        const genreOpts = GENRES.filter((g) => g !== "All Genres")
          .map((g) => `<option value="${escapeHtml(g)}" ${bk.genre === g ? "selected" : ""}>${escapeHtml(g)}</option>`)
          .join("");

        return `
          <div class="detected-row ${state.activeReviewIdx === idx ? "active" : ""}" data-row-idx="${idx}">
            <span class="detected-num">${idx + 1}</span>
            <input type="text" data-field="title" data-idx="${idx}" value="${escapeHtml(bk.title || "")}" placeholder="Book Title" aria-label="Book title" />
            <input type="text" data-field="author" data-idx="${idx}" value="${escapeHtml(bk.author || "")}" placeholder="Author" aria-label="Book author" />
            <select data-field="genre" data-idx="${idx}" aria-label="Book genre">${genreOpts}</select>
            <input type="color" class="row-color-input" data-field="spine_color" data-idx="${idx}" value="${escapeHtml(bk.spine_color || "#3B6E5C")}" title="Spine color" />
            <button type="button" class="row-delete-btn" data-delete-idx="${idx}" title="Remove book">✕</button>
          </div>
        `;
      })
      .join("");
  }

  async function runShelfAnalysis({ photoData, presetId }) {
    state.snapPhotoData = photoData;
    state.snapPresetId = presetId || "";
    state.activeReviewIdx = null;

    document.getElementById("snapStep1").classList.add("hidden");
    document.getElementById("snapStep2").classList.remove("hidden");
    document.getElementById("reviewPhotoImg").src = photoData;
    document.getElementById("scanningOverlay").classList.remove("hidden");
    document.getElementById("scanStatusMessage").textContent = "Analyzing shelf photo for readable book spines...";
    document.getElementById("detectedBooksList").innerHTML = "";
    document.getElementById("reviewBboxLayer").innerHTML = "";

    try {
      const isDeepseek = state.aiProvider === "deepseek";
      const resp = await apiPost("/api/analyze-shelf", {
        photo_data: photoData,
        preset_id: presetId,
        provider: state.aiProvider,
        api_key: isDeepseek ? state.deepseekKey : state.apiKey,
        model: isDeepseek ? state.deepseekModel : undefined,
        base_url: isDeepseek ? state.deepseekBaseUrl : undefined,
      });
      state.snapBooks = (resp.books || []).map((b) => ({ ...b }));
      state.snapAiSource = resp.ai_source || "deepseek-api";

      const badgeMap = {
        "deepseek-api": "DeepSeek AI",
        "deepseek-demo": "DeepSeek AI (Demo)",
        "gemini-vision": "Gemini Vision",
        "gemini-vision-demo": "AI Spine Vision (Demo)",
      };
      document.getElementById("scanSourceBadge").textContent =
        badgeMap[state.snapAiSource] || "Local Spine Detector";

      document.getElementById("scanStatusMessage").textContent = resp.warning || resp.message || "";
      populateCheckinBoxSelect(resp.suggested_box_name || "");
      if (resp.suggested_note && !document.getElementById("checkinNoteInput").value) {
        document.getElementById("checkinNoteInput").value = resp.suggested_note;
      }
      renderReviewBboxesAndRows();
    } catch (err) {
      showToast(`Spine scan error: ${err.message}`);
      document.getElementById("scanStatusMessage").textContent = "Scan failed — you can still add books manually below.";
      populateCheckinBoxSelect();
      renderReviewBboxesAndRows();
    } finally {
      document.getElementById("scanningOverlay").classList.add("hidden");
    }
  }

  async function publishCheckin() {
    const boxSelect = document.getElementById("checkinBoxSelect").value;
    const validBooks = state.snapBooks.filter((b) => (b.title || "").trim().length > 0);
    if (validBooks.length === 0) {
      showToast("Add at least one book title before publishing.");
      return;
    }

    const payload = {
      photo_data: state.snapPhotoData,
      user_name: document.getElementById("checkinUserInput").value.trim() || "Neighbor Reader",
      note: document.getElementById("checkinNoteInput").value.trim(),
      ai_source: state.snapAiSource,
      books: validBooks,
    };

    if (boxSelect === "__new__") {
      const name = document.getElementById("inlineBoxName").value.trim();
      const address = document.getElementById("inlineBoxAddress").value.trim();
      if (!name || !address) {
        showToast("Please enter a name and address for the new library box.");
        return;
      }
      const centerLat = state.mapCenter?.lat ?? 47.648;
      const centerLng = state.mapCenter?.lng ?? -122.342;
      const regionParts = (state.activeRegion || "Seattle, WA").split(",").map((s) => s.trim());
      payload.new_box = {
        name,
        address,
        neighborhood: document.getElementById("inlineBoxNeighborhood").value.trim() || "Neighborhood",
        city: regionParts[0] || "Seattle",
        state: regionParts[1] || "WA",
        roof_color: document.getElementById("inlineBoxRoofColor").value,
        lat: Number((centerLat + (Math.random() - 0.5) * 0.01).toFixed(5)),
        lng: Number((centerLng + (Math.random() - 0.5) * 0.015).toFixed(5)),
      };
    } else {
      payload.box_id = Number(boxSelect);
    }

    const btn = document.getElementById("publishCheckinBtn");
    btn.disabled = true;
    btn.textContent = "Publishing...";
    try {
      const resp = await apiPost("/api/checkins", payload);
      state.highlightCheckinId = resp.checkin_id;
      document.getElementById("checkinNoteInput").value = "";
      closeSnapModal();
      applyStatePayload(resp.state);
      switchView("feed");
      showToast(`Published check-in and indexed ${resp.indexed_books} book(s)!`);
      setTimeout(() => {
        const card = document.getElementById(`checkin-card-${resp.checkin_id}`);
        if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch (err) {
      showToast(`Publish failed: ${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "Publish Check-In & Index Books";
    }
  }

  // --- Event Binding ---
  function bindEvents() {
    // Navigation tabs
    document.querySelectorAll(".nav-tab, .mobile-nav-btn[data-view]").forEach((btn) => {
      btn.addEventListener("click", () => switchView(btn.dataset.view));
    });
    document.getElementById("brandHomeBtn").addEventListener("click", () => switchView("feed"));

    // Quick search in header -> jumps to Book Index
    document.getElementById("headerQuickSearch").addEventListener("input", (e) => {
      state.indexSearch = e.target.value;
      document.getElementById("indexSearchInput").value = e.target.value;
      if (e.target.value.trim() && state.activeView !== "index") {
        switchView("index");
      }
      renderBookIndexView();
    });

    // Feed filters
    document.getElementById("feedSearchInput").addEventListener("input", (e) => {
      state.feedSearch = e.target.value;
      renderFeedView();
    });
    document.getElementById("feedBoxFilter").addEventListener("change", (e) => {
      state.feedBoxId = e.target.value;
      renderFeedView();
    });

    // Feed delegated clicks
    document.getElementById("feedList").addEventListener("click", (e) => {
      const bbox = e.target.closest(".spine-bbox");
      if (bbox) {
        const cid = Number(bbox.dataset.checkinId);
        const bid = Number(bbox.dataset.bookId);
        state.activeFeedSpines[cid] = state.activeFeedSpines[cid] === bid ? null : bid;
        renderFeedView();
        return;
      }

      const btn = e.target.closest("[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      if (action === "toggle-overlay") {
        const cid = Number(btn.dataset.checkinId);
        if (state.hiddenOverlays.has(cid)) state.hiddenOverlays.delete(cid);
        else state.hiddenOverlays.add(cid);
        renderFeedView();
      } else if (action === "select-feed-book") {
        const cid = Number(btn.dataset.checkinId);
        const bid = Number(btn.dataset.bookId);
        state.activeFeedSpines[cid] = state.activeFeedSpines[cid] === bid ? null : bid;
        renderFeedView();
      } else if (action === "goto-box") {
        jumpToBoxOnMap(Number(btn.dataset.boxId));
      } else if (action === "toggle-book-status") {
        toggleBookStatus(Number(btn.dataset.bookId));
      }
    });

    // Book Index filters
    document.getElementById("indexSearchInput").addEventListener("input", (e) => {
      state.indexSearch = e.target.value;
      document.getElementById("headerQuickSearch").value = e.target.value;
      renderBookIndexView();
    });
    document.getElementById("indexStatusFilter").addEventListener("change", (e) => {
      state.indexStatus = e.target.value;
      renderBookIndexView();
    });
    document.getElementById("indexSortSelect").addEventListener("change", (e) => {
      state.indexSort = e.target.value;
      renderBookIndexView();
    });
    document.getElementById("genreFilterPills").addEventListener("click", (e) => {
      const pill = e.target.closest(".genre-pill");
      if (!pill) return;
      state.indexGenre = pill.dataset.genre;
      renderBookIndexView();
    });
    document.getElementById("bookIndexGrid").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      if (action === "goto-box") jumpToBoxOnMap(Number(btn.dataset.boxId));
      else if (action === "toggle-book-status") toggleBookStatus(Number(btn.dataset.bookId));
      else if (action === "inspect-book-photo") openPhotoLightbox(btn.dataset.checkinId, btn.dataset.bookId);
    });

    // LFL World Map Sync, Near Me, Region Pills & Import Modal
    async function fetchWithTimeout(url, options = {}, timeoutMs = 9000) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        const res = await fetch(url, { ...options, signal: ctrl.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
      } finally {
        clearTimeout(timer);
      }
    }

    async function fetchLiveOsmBookcasesInBrowser({ query, lat, lng }) {
      let targetLat = lat;
      let targetLng = lng;
      let city = "";
      let stateCode = "";
      let postcode = "";

      if (query && (targetLat == null || targetLng == null)) {
        const nomData = await fetchWithTimeout(
          `https://nominatim.openstreetmap.org/search?format=json&limit=1&addressdetails=1&q=${encodeURIComponent(query)}`,
          {},
          7000
        );
        if (!Array.isArray(nomData) || nomData.length === 0) {
          throw new Error(`No geocoding match for "${query}"`);
        }
        const hit = nomData[0];
        const addr = hit.address || {};
        targetLat = Number(hit.lat);
        targetLng = Number(hit.lon);
        city = addr.city || addr.town || addr.village || addr.county || "";
        stateCode = addr.state || "";
        postcode = addr.postcode || "";
      } else if (targetLat != null && targetLng != null) {
        try {
          const revData = await fetchWithTimeout(
            `https://nominatim.openstreetmap.org/reverse?format=json&lat=${targetLat}&lon=${targetLng}`,
            {},
            6000
          );
          const addr = revData.address || {};
          city = addr.city || addr.town || addr.village || addr.county || "";
          stateCode = addr.state || "";
          postcode = addr.postcode || "";
        } catch (_err) {
          // Reverse geocode optional; continue with GPS coordinates
        }
      }

      const south = (targetLat - 0.03).toFixed(5);
      const north = (targetLat + 0.03).toFixed(5);
      const west = (targetLng - 0.04).toFixed(5);
      const east = (targetLng + 0.04).toFixed(5);
      const ql = `[out:json][timeout:8];(node["amenity"="public_bookcase"](${south},${west},${north},${east});way["amenity"="public_bookcase"](${south},${west},${north},${east}););out center tags 35;`;
      const body = `data=${encodeURIComponent(ql)}`;
      const endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
      ];

      let osmJson = null;
      for (const endpoint of endpoints) {
        try {
          osmJson = await fetchWithTimeout(
            endpoint,
            {
              method: "POST",
              headers: { "Content-Type": "application/x-www-form-urlencoded" },
              body,
            },
            9000
          );
          break;
        } catch (_err) {
          continue;
        }
      }
      if (!osmJson) {
        throw new Error("Overpass endpoints unreachable from browser");
      }

      const records = [];
      for (const el of osmJson.elements || []) {
        const elLat = el.lat ?? el.center?.lat;
        const elLng = el.lon ?? el.center?.lon;
        if (elLat == null || elLng == null) continue;
        const tags = el.tags || {};
        const rawRef = tags["ref:littlefreelibrary"] || tags.ref || "";
        const charter = rawRef ? rawRef : `OSM #${el.id}`;
        const name = tags.name || (rawRef ? `Little Free Library #${rawRef}` : `Community Book Box #${el.id}`);
        const street = [tags["addr:housenumber"], tags["addr:street"]].filter(Boolean).join(" ").trim();
        const boxCity = tags["addr:city"] || city || "";
        const boxState = tags["addr:state"] || stateCode || "";
        const boxZip = tags["addr:postcode"] || postcode || "";
        const neighborhood = tags["addr:suburb"] || tags["addr:neighbourhood"] || boxCity || "Local";
        const address = street || tags.description || `GPS ${Number(elLat).toFixed(4)}, ${Number(elLng).toFixed(4)}`;
        records.push({
          name,
          charter_number: charter,
          address,
          neighborhood,
          city: boxCity,
          state: boxState,
          postal_code: boxZip,
          lat: Number(Number(elLat).toFixed(6)),
          lng: Number(Number(elLng).toFixed(6)),
          steward_name: tags.operator || "Community Steward",
          description: tags.description || "Synced live from OpenStreetMap public bookcase directory.",
          source: "osm-sync",
          external_id: `osm:${el.type || "node"}:${el.id}`,
          lfl_url: "https://littlefreelibrary.org/map/",
        });
      }

      const label = [city, stateCode].filter(Boolean).join(", ") || `${targetLat.toFixed(4)}, ${targetLng.toFixed(4)}`;
      return { records, center: { lat: targetLat, lng: targetLng, label } };
    }

    async function runLflSync(payload) {
      const syncBtn = document.getElementById("lflSyncLocationBtn");
      syncBtn.disabled = true;
      syncBtn.textContent = "Syncing...";
      try {
        if (payload.query) {
          const normQ = payload.query.toLowerCase().replace(/charter/g, "").replace(/#/g, "").trim();
          const localMatch = state.boxes.find((b) => {
            const chClean = (b.charter_number || "").toLowerCase().replace(/charter/g, "").replace(/#/g, "").trim();
            return (normQ && chClean === normQ) || (b.name || "").toLowerCase().includes(payload.query.toLowerCase());
          });
          if (localMatch) {
            state.selectedBoxId = localMatch.id;
            state.activeRegion = getBoxRegionLabel(localMatch);
            state.mapCenter = { lat: localMatch.lat, lng: localMatch.lng, label: state.activeRegion };
            state.mapViewBox = { x: 0, y: 0, w: 1000, h: 720 };
            renderMapView();
            showToast(`Focused on ${localMatch.name} (${localMatch.charter_number})`);
            return;
          }
        }

        // Try live browser-side Nominatim + Overpass sync first
        try {
          const live = await fetchLiveOsmBookcasesInBrowser(payload);
          if (live.records.length > 0) {
            const imp = await apiPost("/api/lfl/import", { raw_data: live.records });
            state.mapCenter = live.center;
            if (imp.matched_box_id) state.selectedBoxId = imp.matched_box_id;
            state.mapViewBox = { x: 0, y: 0, w: 1000, h: 720 };
            const matched = (imp.state?.boxes || []).find((b) => b.id === imp.matched_box_id);
            state.activeRegion = matched ? getBoxRegionLabel(matched) : live.center.label;
            applyStatePayload(imp.state);
            showToast(`Synced ${live.records.length} live Little Free Library box(es) near ${live.center.label}`);
            return;
          }
        } catch (_browserErr) {
          // Fall back cleanly to server-side sync/catalog
        }

        const resp = await apiPost("/api/lfl/sync", payload);
        if (resp.center) state.mapCenter = resp.center;
        if (resp.matched_box_id) state.selectedBoxId = resp.matched_box_id;
        state.mapViewBox = { x: 0, y: 0, w: 1000, h: 720 };
        const matched = (resp.state?.boxes || []).find((b) => b.id === resp.matched_box_id);
        state.activeRegion = matched ? getBoxRegionLabel(matched) : (resp.center?.label || "");
        applyStatePayload(resp.state);
        if (resp.source_used === "local-match") {
          showToast(`Focused on ${resp.center?.label || "matching box"}`);
        } else if (resp.synced_count > 0) {
          showToast(
            `Synced ${resp.synced_count} Little Free Library box(es) near ${resp.center?.label || "location"} (${resp.source_used})`
          );
        } else {
          showToast(`Centered map on ${resp.center?.label || "location"}; no new mapped boxes found nearby.`);
        }
      } catch (err) {
        showToast(`LFL Sync failed: ${err.message}`);
      } finally {
        syncBtn.disabled = false;
        syncBtn.textContent = "Sync LFL Map";
      }
    }

    document.getElementById("lflSyncLocationBtn").addEventListener("click", () => {
      const query = document.getElementById("lflLocationSearchInput").value.trim();
      if (!query) {
        showToast("Enter a city, zip code, or Charter # to sync.");
        return;
      }
      runLflSync({ query });
    });

    document.getElementById("lflLocationSearchInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        document.getElementById("lflSyncLocationBtn").click();
      }
    });

    document.getElementById("lflNearMeBtn").addEventListener("click", () => {
      if (!navigator.geolocation) {
        showToast("Browser geolocation is unavailable; search a city or zip instead.");
        return;
      }
      showToast("Requesting device GPS location...");
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          runLflSync({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        },
        () => {
          showToast("Location permission denied; enter a city or zip code to sync.");
        },
        { timeout: 8000 }
      );
    });

    document.getElementById("mapRegionPills").addEventListener("click", (e) => {
      const pill = e.target.closest("[data-region]");
      if (!pill) return;
      state.activeRegion = pill.dataset.region;
      const firstInRegion = state.boxes.find((b) => getBoxRegionLabel(b) === state.activeRegion);
      if (firstInRegion) {
        state.selectedBoxId = firstInRegion.id;
        state.mapCenter = { lat: firstInRegion.lat, lng: firstInRegion.lng, label: state.activeRegion };
      }
      state.mapViewBox = { x: 0, y: 0, w: 1000, h: 720 };
      renderMapView();
    });

    // LFL Import Modal
    const SAMPLE_OFFICIAL_LFL_EXPORT = [
      {
        Library_Name__c: "Summit Hill Little Library",
        Official_Charter_Number__c: "42108",
        Street__c: "742 Summit Ave",
        City__c: "St. Paul",
        State_Province__c: "MN",
        Postal_Code__c: "55105",
        Library_Geolocation__c: { latitude: 44.9412, longitude: -93.1315 },
        Primary_Steward_s_Name__c: "Claire Novak",
        Library_Story__c: "Historic brownstone-style Little Free Library near the Summit Ave overlook.",
      },
      {
        Library_Name__c: "Lake Harriet Windmill Box",
        Official_Charter_Number__c: "18490",
        Street__c: "4135 W Lake Harriet Pkwy",
        City__c: "Minneapolis",
        State_Province__c: "MN",
        Postal_Code__c: "55409",
        Library_Geolocation__c: { latitude: 44.9228, longitude: -93.3084 },
        Primary_Steward_s_Name__c: "Owen Lindqvist",
        Library_Story__c: "Stocked daily with Twin Cities fiction, children's picture books, and nature guides.",
      },
      {
        Library_Name__c: "Minnehaha Falls Cedar Post",
        Official_Charter_Number__c: "63512",
        Street__c: "4801 S Minnehaha Park Dr",
        City__c: "Minneapolis",
        State_Province__c: "MN",
        Postal_Code__c: "55417",
        Library_Geolocation__c: { latitude: 44.9153, longitude: -93.2110 },
        Primary_Steward_s_Name__c: "Maya Hernandez",
        Library_Story__c: "Trailside box welcoming park visitors with rotating paperbacks.",
      },
      {
        Library_Name__c: "Cathedral Hill Reading Cottage",
        Official_Charter_Number__c: "29405",
        Street__c: "321 Selby Ave",
        City__c: "St. Paul",
        State_Province__c: "MN",
        Postal_Code__c: "55102",
        Library_Geolocation__c: { latitude: 44.9465, longitude: -93.1142 },
        Primary_Steward_s_Name__c: "David Park",
        Library_Story__c: "Neighborhood mystery and poetry swap box.",
      },
    ];

    document.getElementById("openLflImportModalBtn").addEventListener("click", () => {
      document.getElementById("lflImportModal").classList.remove("hidden");
    });
    document.getElementById("closeLflImportBtn").addEventListener("click", () => {
      document.getElementById("lflImportModal").classList.add("hidden");
    });
    document.getElementById("loadSampleLflExportBtn").addEventListener("click", () => {
      document.getElementById("lflImportTextarea").value = JSON.stringify(SAMPLE_OFFICIAL_LFL_EXPORT, null, 2);
    });
    document.getElementById("lflImportFileInput").addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        document.getElementById("lflImportTextarea").value = reader.result || "";
      };
      reader.readAsText(file);
      e.target.value = "";
    });
    document.getElementById("submitLflImportBtn").addEventListener("click", async () => {
      const rawData = document.getElementById("lflImportTextarea").value.trim();
      if (!rawData) {
        showToast("Paste an LFL JSON/GeoJSON/CSV dataset or load the sample export first.");
        return;
      }
      const btn = document.getElementById("submitLflImportBtn");
      btn.disabled = true;
      btn.textContent = "Importing...";
      try {
        const resp = await apiPost("/api/lfl/import", { raw_data: rawData });
        document.getElementById("lflImportModal").classList.add("hidden");
        if (resp.matched_box_id) state.selectedBoxId = resp.matched_box_id;
        if (resp.center) state.mapCenter = resp.center;
        const importedBox = (resp.state?.boxes || []).find((b) => b.id === resp.matched_box_id);
        state.activeRegion = importedBox ? getBoxRegionLabel(importedBox) : (resp.center?.label || "");
        state.mapViewBox = { x: 0, y: 0, w: 1000, h: 720 };
        applyStatePayload(resp.state);
        showToast(`Imported ${resp.imported_count} Little Free Library box(es)!`);
      } catch (err) {
        showToast(`Import failed: ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = "Import Boxes to Map";
      }
    });

    // Map controls & interactions
    document.getElementById("mapZoomInBtn").addEventListener("click", () => zoomMap(0.8));
    document.getElementById("mapZoomOutBtn").addEventListener("click", () => zoomMap(1.25));
    document.getElementById("mapResetBtn").addEventListener("click", resetMap);
    document.getElementById("toggleAddBoxModeBtn").addEventListener("click", () => {
      setAddBoxMode(!state.placingBoxMode);
    });
    document.getElementById("cancelAddBoxModeBtn").addEventListener("click", () => setAddBoxMode(false));

    const mapViewport = document.getElementById("mapViewport");
    const mapSvg = document.getElementById("neighborhoodMapSvg");

    mapViewport.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".map-pin-group")) return;
      state.mapDrag = {
        startX: e.clientX,
        startY: e.clientY,
        origX: state.mapViewBox.x,
        origY: state.mapViewBox.y,
        moved: false,
      };
    });

    window.addEventListener("pointermove", (e) => {
      if (!state.mapDrag) return;
      const dx = e.clientX - state.mapDrag.startX;
      const dy = e.clientY - state.mapDrag.startY;
      if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
        state.mapDrag.moved = true;
      }
      if (!state.mapDrag.moved) return;
      const rect = mapSvg.getBoundingClientRect();
      const scaleX = state.mapViewBox.w / Math.max(1, rect.width);
      const scaleY = state.mapViewBox.h / Math.max(1, rect.height);
      state.mapViewBox.x = Math.max(0, Math.min(1000 - state.mapViewBox.w, state.mapDrag.origX - dx * scaleX));
      state.mapViewBox.y = Math.max(0, Math.min(720 - state.mapViewBox.h, state.mapDrag.origY - dy * scaleY));
      renderMapSvg();
    });

    window.addEventListener("pointerup", (e) => {
      if (!state.mapDrag) return;
      const wasMoved = state.mapDrag.moved;
      state.mapDrag = null;
      if (!wasMoved && state.placingBoxMode && e.target.closest("#neighborhoodMapSvg")) {
        const pt = mapSvg.createSVGPoint();
        pt.x = e.clientX;
        pt.y = e.clientY;
        const ctm = mapSvg.getScreenCTM();
        if (ctm) {
          const svgPt = pt.matrixTransform(ctm.inverse());
          const proj = state.lastGeoProjection || getGeoProjection(getVisibleMapBoxes());
          const coords = proj.unproject(svgPt.x, svgPt.y);
          state.pendingNewBoxCoords = coords;
          document.getElementById("newBoxCoordsLabel").textContent = `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)}`;
          setAddBoxMode(false);
          document.getElementById("newMapBoxModal").classList.remove("hidden");
        }
      }
    });

    mapViewport.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        zoomMap(e.deltaY < 0 ? 0.9 : 1.1);
      },
      { passive: false }
    );

    mapSvg.addEventListener("click", (e) => {
      const pin = e.target.closest(".map-pin-group");
      if (!pin) return;
      state.selectedBoxId = Number(pin.dataset.boxId);
      renderMapView();
    });

    document.getElementById("mapBoxDrawer").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-action]");
      if (!btn) return;
      if (btn.dataset.action === "snap-for-box") {
        openSnapModal(Number(btn.dataset.boxId));
      } else if (btn.dataset.action === "toggle-book-status") {
        toggleBookStatus(Number(btn.dataset.bookId));
      }
    });

    // New Map Box modal
    document.getElementById("closeNewMapBoxBtn").addEventListener("click", () => {
      document.getElementById("newMapBoxModal").classList.add("hidden");
    });
    document.getElementById("newMapBoxForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const regionParts = (state.activeRegion || "Seattle, WA").split(",").map((s) => s.trim());
        const resp = await apiPost("/api/boxes", {
          name: document.getElementById("mapBoxName").value.trim(),
          address: document.getElementById("mapBoxAddress").value.trim(),
          neighborhood: document.getElementById("mapBoxNeighborhood").value.trim() || "Neighborhood",
          city: regionParts[0] || "Seattle",
          state: regionParts[1] || "WA",
          charter_number: document.getElementById("mapBoxCharter").value.trim(),
          steward_name: document.getElementById("mapBoxSteward").value.trim(),
          roof_color: document.getElementById("mapBoxRoofColor").value,
          description: document.getElementById("mapBoxDesc").value.trim(),
          lat: state.pendingNewBoxCoords.lat,
          lng: state.pendingNewBoxCoords.lng,
        });
        document.getElementById("newMapBoxForm").reset();
        document.getElementById("newMapBoxModal").classList.add("hidden");
        state.selectedBoxId = resp.box_id;
        applyStatePayload(resp.state);
        showToast("Added new Little Free Library box to the map!");
      } catch (err) {
        showToast(`Failed to create box: ${err.message}`);
      }
    });

    // Snap / Upload modal controls
    document.getElementById("openSnapModalBtn").addEventListener("click", () => openSnapModal(null));
    document.getElementById("mobileSnapBtn").addEventListener("click", () => openSnapModal(null));
    document.getElementById("closeSnapModalBtn").addEventListener("click", closeSnapModal);

    document.querySelectorAll(".capture-tab").forEach((tab) => {
      tab.addEventListener("click", () => switchCaptureTab(tab.dataset.captureTab));
    });

    const fileInput = document.getElementById("photoFileInput");
    fileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files[0]) {
        handleUploadedFile(e.target.files[0]);
        e.target.value = "";
      }
    });

    const dropzone = document.getElementById("uploadDropzone");
    dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleUploadedFile(e.dataTransfer.files[0]);
      }
    });

    document.getElementById("startCameraBtn").addEventListener("click", startLiveCamera);
    document.getElementById("captureFrameBtn").addEventListener("click", captureCameraFrame);

    document.getElementById("demoPresetsGrid").addEventListener("click", (e) => {
      const card = e.target.closest("[data-preset-id]");
      if (!card) return;
      const presetId = card.dataset.presetId;
      const photoUrl = window.ShelfPhotos.renderDemoPresetPhoto(presetId);
      runShelfAnalysis({ photoData: photoUrl, presetId });
    });

    document.getElementById("backToStep1Btn").addEventListener("click", () => {
      document.getElementById("snapStep2").classList.add("hidden");
      document.getElementById("snapStep1").classList.remove("hidden");
    });

    document.getElementById("reviewBboxLayer").addEventListener("click", (e) => {
      const box = e.target.closest("[data-review-idx]");
      if (!box) return;
      state.activeReviewIdx = Number(box.dataset.reviewIdx);
      renderReviewBboxesAndRows();
      const row = document.querySelector(`[data-row-idx="${state.activeReviewIdx}"]`);
      if (row) row.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });

    document.getElementById("detectedBooksList").addEventListener("input", (e) => {
      const idx = Number(e.target.dataset.idx);
      const field = e.target.dataset.field;
      if (Number.isNaN(idx) || !field || !state.snapBooks[idx]) return;
      state.snapBooks[idx][field] = e.target.value;
    });

    document.getElementById("detectedBooksList").addEventListener("change", (e) => {
      const idx = Number(e.target.dataset.idx);
      const field = e.target.dataset.field;
      if (Number.isNaN(idx) || !field || !state.snapBooks[idx]) return;
      state.snapBooks[idx][field] = e.target.value;
    });

    document.getElementById("detectedBooksList").addEventListener("click", (e) => {
      const delBtn = e.target.closest("[data-delete-idx]");
      if (delBtn) {
        const idx = Number(delBtn.dataset.deleteIdx);
        state.snapBooks.splice(idx, 1);
        state.activeReviewIdx = null;
        renderReviewBboxesAndRows();
        return;
      }
      const row = e.target.closest("[data-row-idx]");
      if (row) {
        const nextIdx = Number(row.dataset.rowIdx);
        if (state.activeReviewIdx !== nextIdx) {
          state.activeReviewIdx = nextIdx;
          document.querySelectorAll("#reviewBboxLayer .spine-bbox").forEach((el) => {
            el.classList.toggle("active", Number(el.dataset.reviewIdx) === nextIdx);
          });
        }
      }
    });

    document.getElementById("addManualBookRowBtn").addEventListener("click", () => {
      const n = state.snapBooks.length;
      const xStart = 14 + (n % 5) * 14;
      const yTop = n < 4 ? 20 : 57;
      state.snapBooks.push({
        title: "",
        author: "",
        genre: "Fiction",
        spine_color: "#2D5A43",
        confidence: 1.0,
        bbox: [yTop, xStart, yTop + 30, Math.min(92, xStart + 12)],
      });
      state.activeReviewIdx = state.snapBooks.length - 1;
      renderReviewBboxesAndRows();
    });

    document.getElementById("checkinBoxSelect").addEventListener("change", (e) => {
      document.getElementById("inlineNewBoxFields").classList.toggle("hidden", e.target.value !== "__new__");
    });

    document.getElementById("publishCheckinBtn").addEventListener("click", publishCheckin);

    // Lightbox modal
    document.getElementById("closeLightboxBtn").addEventListener("click", () => {
      document.getElementById("photoLightboxModal").classList.add("hidden");
    });

    // Settings modal
    function updateSettingsProviderView(selectedProvider) {
      const isDeepseek = selectedProvider === "deepseek";
      document.getElementById("deepseekSettingsGroup").classList.toggle("hidden", !isDeepseek);
      document.getElementById("geminiSettingsGroup").classList.toggle("hidden", isDeepseek);

      const envStatusBox = document.getElementById("envKeyStatusBox");
      if (isDeepseek) {
        envStatusBox.textContent = state.hasEnvDeepseekKey
          ? "Server environment variable DEEPSEEK_API_KEY is detected and active."
          : state.deepseekKey
          ? "Using your browser-saved DeepSeek API key."
          : "No DeepSeek API key configured. Demo shelf photos & local spine detector work out of the box.";
      } else {
        envStatusBox.textContent = state.hasEnvGeminiKey
          ? "Server environment variable GEMINI_API_KEY is detected and active."
          : state.apiKey
          ? "Using your browser-saved Gemini API key for uploaded photos."
          : "No Gemini API key configured. Demo shelf photos & local spine detector work out of the box.";
      }
    }

    document.getElementById("openSettingsBtn").addEventListener("click", () => {
      document.getElementById("aiProviderSelect").value = state.aiProvider;
      document.getElementById("deepseekApiKeyInput").value = state.deepseekKey;
      document.getElementById("deepseekModelInput").value = state.deepseekModel;
      document.getElementById("deepseekBaseUrlInput").value = state.deepseekBaseUrl;
      document.getElementById("geminiApiKeyInput").value = state.apiKey;
      updateSettingsProviderView(state.aiProvider);
      document.getElementById("settingsModal").classList.remove("hidden");
    });
    document.getElementById("aiProviderSelect").addEventListener("change", (e) => {
      updateSettingsProviderView(e.target.value);
    });
    document.getElementById("closeSettingsBtn").addEventListener("click", () => {
      document.getElementById("settingsModal").classList.add("hidden");
    });
    document.getElementById("saveApiKeyBtn").addEventListener("click", () => {
      state.aiProvider = document.getElementById("aiProviderSelect").value;
      localStorage.setItem("shelfspot_ai_provider", state.aiProvider);

      state.deepseekKey = document.getElementById("deepseekApiKeyInput").value.trim();
      state.deepseekModel = document.getElementById("deepseekModelInput").value.trim() || "deepseek-chat";
      state.deepseekBaseUrl =
        document.getElementById("deepseekBaseUrlInput").value.trim() || "https://api.deepseek.com/chat/completions";
      if (state.deepseekKey) localStorage.setItem("shelfspot_deepseek_key", state.deepseekKey);
      else localStorage.removeItem("shelfspot_deepseek_key");
      localStorage.setItem("shelfspot_deepseek_model", state.deepseekModel);
      localStorage.setItem("shelfspot_deepseek_base_url", state.deepseekBaseUrl);

      state.apiKey = document.getElementById("geminiApiKeyInput").value.trim();
      if (state.apiKey) localStorage.setItem("shelfspot_gemini_key", state.apiKey);
      else localStorage.removeItem("shelfspot_gemini_key");

      renderHeaderStats();
      document.getElementById("settingsModal").classList.add("hidden");
      showToast(
        state.aiProvider === "deepseek"
          ? state.deepseekKey
            ? "DeepSeek API settings saved."
            : "Switched to DeepSeek API."
          : state.apiKey
          ? "Gemini API settings saved."
          : "Switched to Gemini API."
      );
    });
    document.getElementById("clearApiKeyBtn").addEventListener("click", () => {
      if (document.getElementById("aiProviderSelect").value === "deepseek") {
        state.deepseekKey = "";
        localStorage.removeItem("shelfspot_deepseek_key");
        document.getElementById("deepseekApiKeyInput").value = "";
        showToast("Cleared saved DeepSeek API key.");
      } else {
        state.apiKey = "";
        localStorage.removeItem("shelfspot_gemini_key");
        document.getElementById("geminiApiKeyInput").value = "";
        showToast("Cleared saved Gemini API key.");
      }
      renderHeaderStats();
      document.getElementById("settingsModal").classList.add("hidden");
    });

    // Close modals on backdrop click
    document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
      backdrop.addEventListener("click", (e) => {
        if (e.target === backdrop) {
          if (backdrop.id === "snapModal") closeSnapModal();
          else backdrop.classList.add("hidden");
        }
      });
    });
  }

  // Initialize
  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadInitialState();
  });
})();
