(function () {
  const PHOTO_W = 800;
  const PHOTO_H = 600;
  const cache = new Map();

  const DEMO_PRESETS = [
    {
      id: "demo-cedar-creek",
      label: "Cedar Creek Box",
      subtitle: "6 books · Fiction, Sci-Fi & Mystery",
      roofColor: "#C85A32",
      charter: "Charter #104822",
      books: [
        { title: "The Midnight Library", author: "Matt Haig", spine_color: "#264653", bbox: [20, 14, 51, 28] },
        { title: "Station Eleven", author: "Emily St. John Mandel", spine_color: "#457B9D", bbox: [18, 30, 51, 44] },
        { title: "Bright Creatures", author: "Shelby Van Pelt", spine_color: "#E76F51", bbox: [21, 46, 51, 61] },
        { title: "The Creative Act", author: "Rick Rubin", spine_color: "#6D6875", bbox: [57, 15, 88, 30] },
        { title: "Vera Wong's Advice", author: "Jesse Q. Sutanto", spine_color: "#C85A32", bbox: [55, 32, 88, 47] },
        { title: "Cerulean Sea", author: "TJ Klune", spine_color: "#2A9D8F", bbox: [58, 49, 88, 63] },
      ],
    },
    {
      id: "demo-oak-street",
      label: "Rosewood Coffee Box",
      subtitle: "5 books · Cooking, Fiction & Mystery",
      roofColor: "#6E473B",
      charter: "Charter #89103",
      books: [
        { title: "Lessons in Chemistry", author: "Bonnie Garmus", spine_color: "#3D5A80", bbox: [19, 15, 51, 30] },
        { title: "Crying in H Mart", author: "Michelle Zauner", spine_color: "#B56576", bbox: [21, 32, 51, 46] },
        { title: "Orient Express", author: "Agatha Christie", spine_color: "#7F4F24", bbox: [18, 48, 51, 62] },
        { title: "Start Here", author: "Sohla El-Waylly", spine_color: "#D97236", bbox: [56, 17, 88, 33] },
        { title: "Piranesi", author: "Susanna Clarke", spine_color: "#3A5A40", bbox: [58, 35, 88, 50] },
      ],
    },
    {
      id: "demo-kids-classics",
      label: "Elmwood Kids & Classics",
      subtitle: "6 books · Children's & Fantasy",
      roofColor: "#3B6E5C",
      charter: "Charter #112095",
      books: [
        { title: "The Wild Robot", author: "Peter Brown", spine_color: "#4F772D", bbox: [20, 14, 51, 28] },
        { title: "Lightning Thief", author: "Rick Riordan", spine_color: "#2B59C3", bbox: [18, 30, 51, 44] },
        { title: "Green Gables", author: "L.M. Montgomery", spine_color: "#A44A3F", bbox: [21, 46, 51, 60] },
        { title: "Tale of Despereaux", author: "Kate DiCamillo", spine_color: "#7A5195", bbox: [57, 15, 88, 29] },
        { title: "Holes", author: "Louis Sachar", spine_color: "#BC6C25", bbox: [56, 31, 88, 45] },
        { title: "Wrinkle in Time", author: "Madeleine L'Engle", spine_color: "#3C3744", bbox: [58, 47, 88, 62] },
      ],
    },
  ];

  function hexToRgb(hex) {
    const clean = (hex || "#3B6E5C").replace("#", "");
    const full = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean;
    const num = parseInt(full, 16);
    if (Number.isNaN(num)) return { r: 59, g: 110, b: 92 };
    return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
  }

  function shadeColor(hex, amount) {
    const { r, g, b } = hexToRgb(hex);
    const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)));
    return `rgb(${clamp(r + amount)}, ${clamp(g + amount)}, ${clamp(b + amount)})`;
  }

  function isLightColor(hex) {
    const { r, g, b } = hexToRgb(hex);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return luminance > 0.62;
  }

  function drawRoundedRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  function drawBookSpine(ctx, book, index) {
    const bbox = Array.isArray(book.bbox) && book.bbox.length === 4 ? book.bbox : [20, 15 + index * 14, 51, 28 + index * 14];
    const [ymin, xmin, ymax, xmax] = bbox;
    const x = (xmin / 100) * PHOTO_W;
    const y = (ymin / 100) * PHOTO_H;
    const w = ((xmax - xmin) / 100) * PHOTO_W;
    const h = ((ymax - ymin) / 100) * PHOTO_H;
    const color = book.spine_color || "#3B6E5C";

    // Drop shadow behind spine
    ctx.save();
    ctx.fillStyle = "rgba(0, 0, 0, 0.34)";
    drawRoundedRect(ctx, x + 3, y + 2, w, h, 4);
    ctx.fill();

    // Spine cylinder gradient
    const grad = ctx.createLinearGradient(x, y, x + w, y);
    grad.addColorStop(0, shadeColor(color, 26));
    grad.addColorStop(0.24, shadeColor(color, 10));
    grad.addColorStop(0.75, color);
    grad.addColorStop(1, shadeColor(color, -34));
    ctx.fillStyle = grad;
    drawRoundedRect(ctx, x, y, w, h, 4);
    ctx.fill();

    // Top paper-edge peek
    ctx.fillStyle = "rgba(248, 240, 224, 0.85)";
    ctx.fillRect(x + 6, y + 1, Math.max(8, w - 12), 4);

    // Decorative top & bottom spine foil bands
    const light = isLightColor(color);
    const accent = light ? "rgba(42, 31, 24, 0.25)" : "rgba(244, 211, 94, 0.65)";
    ctx.fillStyle = accent;
    ctx.fillRect(x + 4, y + 16, w - 8, 3);
    ctx.fillRect(x + 4, y + h - 24, w - 8, 3);

    // Vertical spine title
    const textColor = light ? "#1F1B18" : "#FAF5EA";
    const subTextColor = light ? "rgba(31, 27, 24, 0.78)" : "rgba(250, 245, 234, 0.82)";

    ctx.save();
    ctx.translate(x + w / 2, y + h * 0.45);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const titleRaw = (book.title || "Untitled").trim();
    const displayTitle = titleRaw.length > 22 ? titleRaw.slice(0, 20) + "…" : titleRaw;
    const fontSize = Math.max(11, Math.min(16, Math.round(w * 0.2)));
    ctx.font = `700 ${fontSize}px Georgia, "Times New Roman", serif`;
    ctx.fillStyle = textColor;
    ctx.fillText(displayTitle, 0, 0, h * 0.68);
    ctx.restore();

    // Author surname near bottom
    const surname = (book.author || "").trim().split(/\s+/).slice(-1)[0] || "";
    if (surname) {
      ctx.font = `600 10px -apple-system, BlinkMacSystemFont, sans-serif`;
      ctx.fillStyle = subTextColor;
      ctx.textAlign = "center";
      ctx.fillText(surname.toUpperCase().slice(0, 10), x + w / 2, y + h - 10, w - 8);
    }

    ctx.restore();
  }

  function drawCozyShelfProp(ctx, maxTopX, maxBottomX) {
    // Draw a small potted succulent on empty space if room allows
    if (maxTopX < 74) {
      const px = Math.max(maxTopX + 10, 76) * (PHOTO_W / 100);
      const py = 51 * (PHOTO_H / 100);
      ctx.save();
      ctx.fillStyle = "#C85A32";
      ctx.beginPath();
      ctx.moveTo(px - 20, py - 34);
      ctx.lineTo(px + 20, py - 34);
      ctx.lineTo(px + 15, py);
      ctx.lineTo(px - 15, py);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = "#A94422";
      ctx.fillRect(px - 22, py - 39, 44, 7);

      ctx.fillStyle = "#4A7C59";
      for (let a = -2; a <= 2; a++) {
        ctx.beginPath();
        ctx.ellipse(px + a * 7, py - 46 - (2 - Math.abs(a)) * 4, 7, 14, a * 0.25, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    // Draw leaning horizontal stack on bottom right if room allows
    if (maxBottomX < 70) {
      const sx = Math.max(maxBottomX + 8, 70) * (PHOTO_W / 100);
      const by = 88 * (PHOTO_H / 100);
      ctx.save();
      ctx.fillStyle = "#E9DFCE";
      drawRoundedRect(ctx, sx, by - 16, 110, 16, 3);
      ctx.fill();
      ctx.fillStyle = "#457B9D";
      drawRoundedRect(ctx, sx + 6, by - 30, 98, 14, 3);
      ctx.fill();
      ctx.restore();
    }
  }

  function renderShelfCanvas({ books, roofColor, charter }) {
    const canvas = document.createElement("canvas");
    canvas.width = PHOTO_W;
    canvas.height = PHOTO_H;
    const ctx = canvas.getContext("2d");

    // 1. Soft sunlit park / garden background
    const bg = ctx.createLinearGradient(0, 0, 0, PHOTO_H);
    bg.addColorStop(0, "#D9E7D8");
    bg.addColorStop(0.6, "#B9D0B7");
    bg.addColorStop(1, "#8EAC8B");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, PHOTO_W, PHOTO_H);

    // Dappled bokeh circles
    const bokeh = [
      [80, 90, 65, "rgba(255,255,235,0.28)"],
      [720, 110, 80, "rgba(255,250,220,0.24)"],
      [60, 480, 75, "rgba(62,98,64,0.18)"],
      [750, 460, 90, "rgba(62,98,64,0.16)"],
    ];
    for (const [bx, by, br, bc] of bokeh) {
      ctx.fillStyle = bc;
      ctx.beginPath();
      ctx.arc(bx, by, br, 0, Math.PI * 2);
      ctx.fill();
    }

    // Cedar post at bottom center
    ctx.fillStyle = "#6F4E37";
    ctx.fillRect(PHOTO_W / 2 - 28, PHOTO_H * 0.92, 56, PHOTO_H * 0.08);

    // 2. Peaked Roof
    const rColor = roofColor || "#C85A32";
    ctx.fillStyle = "rgba(0,0,0,0.18)";
    ctx.beginPath();
    ctx.moveTo(PHOTO_W / 2, 18);
    ctx.lineTo(PHOTO_W * 0.96, 94);
    ctx.lineTo(PHOTO_W * 0.04, 94);
    ctx.closePath();
    ctx.fill();

    const roofGrad = ctx.createLinearGradient(0, 12, 0, 88);
    roofGrad.addColorStop(0, shadeColor(rColor, 20));
    roofGrad.addColorStop(1, shadeColor(rColor, -20));
    ctx.fillStyle = roofGrad;
    ctx.beginPath();
    ctx.moveTo(PHOTO_W / 2, 10);
    ctx.lineTo(PHOTO_W * 0.95, 86);
    ctx.lineTo(PHOTO_W * 0.05, 86);
    ctx.closePath();
    ctx.fill();

    // 3. Outer cedar box body
    const woodGrad = ctx.createLinearGradient(48, 75, 752, 560);
    woodGrad.addColorStop(0, "#B07D4F");
    woodGrad.addColorStop(0.5, "#9A6B42");
    woodGrad.addColorStop(1, "#7F5431");
    ctx.fillStyle = woodGrad;
    drawRoundedRect(ctx, PHOTO_W * 0.06, PHOTO_H * 0.12, PHOTO_W * 0.88, PHOTO_H * 0.83, 8);
    ctx.fill();

    // 4. Brass Charter Plaque above top interior
    ctx.fillStyle = "#D4AF37";
    drawRoundedRect(ctx, PHOTO_W * 0.34, PHOTO_H * 0.128, PHOTO_W * 0.32, 18, 4);
    ctx.fill();
    ctx.fillStyle = "#332211";
    ctx.font = "700 10px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(`LITTLE FREE LIBRARY · ${(charter || "CHARTERED").toUpperCase()}`, PHOTO_W * 0.5, PHOTO_H * 0.128 + 9);

    // 5. Interior recess
    const innerGrad = ctx.createLinearGradient(0, PHOTO_H * 0.16, 0, PHOTO_H * 0.91);
    innerGrad.addColorStop(0, "#2A1F18");
    innerGrad.addColorStop(0.48, "#3B2B21");
    innerGrad.addColorStop(1, "#241913");
    ctx.fillStyle = innerGrad;
    drawRoundedRect(ctx, PHOTO_W * 0.1, PHOTO_H * 0.16, PHOTO_W * 0.8, PHOTO_H * 0.74, 4);
    ctx.fill();

    // 6. Shelf planks
    const shelfGrad = ctx.createLinearGradient(0, PHOTO_H * 0.51, 0, PHOTO_H * 0.545);
    shelfGrad.addColorStop(0, "#C49566");
    shelfGrad.addColorStop(1, "#7C5230");
    ctx.fillStyle = shelfGrad;
    ctx.fillRect(PHOTO_W * 0.1, PHOTO_H * 0.51, PHOTO_W * 0.8, PHOTO_H * 0.032);

    ctx.fillStyle = "#9C6D44";
    ctx.fillRect(PHOTO_W * 0.1, PHOTO_H * 0.88, PHOTO_W * 0.8, PHOTO_H * 0.03);

    // 7. Draw books
    let maxTopX = 0;
    let maxBottomX = 0;
    (books || []).forEach((bk, idx) => {
      drawBookSpine(ctx, bk, idx);
      if (Array.isArray(bk.bbox)) {
        if (bk.bbox[0] < 50) maxTopX = Math.max(maxTopX, bk.bbox[3]);
        else maxBottomX = Math.max(maxBottomX, bk.bbox[3]);
      }
    });

    drawCozyShelfProp(ctx, maxTopX, maxBottomX);

    // 8. Subtle plexiglass window sheen
    ctx.save();
    ctx.fillStyle = "rgba(255, 255, 255, 0.06)";
    ctx.beginPath();
    ctx.moveTo(PHOTO_W * 0.11, PHOTO_H * 0.17);
    ctx.lineTo(PHOTO_W * 0.38, PHOTO_H * 0.17);
    ctx.lineTo(PHOTO_W * 0.16, PHOTO_H * 0.88);
    ctx.lineTo(PHOTO_W * 0.11, PHOTO_H * 0.88);
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    return canvas.toDataURL("image/png");
  }

  function resolveCheckinPhoto(checkin) {
    if (!checkin) return "";
    const raw = checkin.photo_data || "";
    if (raw.startsWith("data:image/")) {
      return raw;
    }
    const cacheKey = `${checkin.id || "c"}:${raw}:${(checkin.books || []).length}`;
    if (cache.has(cacheKey)) {
      return cache.get(cacheKey);
    }
    const url = renderShelfCanvas({
      books: checkin.books || [],
      roofColor: checkin.roof_color || "#C85A32",
      charter: checkin.charter_number || "Chartered",
    });
    cache.set(cacheKey, url);
    return url;
  }

  function renderDemoPresetPhoto(presetId) {
    const preset = DEMO_PRESETS.find((p) => p.id === presetId);
    if (!preset) return "";
    const key = `demo:${presetId}`;
    if (cache.has(key)) return cache.get(key);
    const url = renderShelfCanvas({
      books: preset.books,
      roofColor: preset.roofColor,
      charter: preset.charter,
    });
    cache.set(key, url);
    return url;
  }

  window.ShelfPhotos = {
    DEMO_PRESETS,
    resolveCheckinPhoto,
    renderDemoPresetPhoto,
    renderShelfCanvas,
  };
})();
