// The real map: OpenStreetMap streets (OpenFreeMap tiles) with the Margalla Hills in relief, drawn by MapLibre.
// It loads only when it is about to be seen. If the library or the tiles can't load, the schematic SectorMap takes over.
window.RealMap = (() => {
  const LIB = "https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl";
  const JS_SRI = "sha384-GfxBM9x46BaAFxtCq39Fxir8fNZ4VDnwgfi6Kzi5/F1tAFsm0amuuV8kd+Pxzuf/";
  const CSS_SRI = "sha384-Nq6PQ+9vJPvw7U/VfDELyrWoGQMsy0gi6QShhaSrGzkpF5KkM40csg2leky+YMTd";
  const RELIEF = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";

  // Centre of each area, [longitude, latitude]. Geocoded from OpenStreetMap; DHA Phase 5 and Park View City are estimates.
  const AT = {
    "f-7": [73.0561, 33.7204], "f-11": [72.9895, 33.6844], "e-11": [72.9724, 33.6951], "g-11": [72.9987, 33.6687],
    "g-13": [72.9621, 33.6515], "b-17": [72.8286, 33.6904], "top city 1": [72.8693, 33.5763], "bahria town phase 8": [73.0727, 33.4877],
    "dha phase 2": [73.157, 33.5307], "dha phase 5": [73.196, 33.53], "bahria enclave": [73.214, 33.6877],
    "park view city": [73.198, 33.705], "gulberg residencia": [73.2119, 33.6002], "pakistan town": [73.1439, 33.5755],
  };
  const at = (area) => AT[(area || "").toLowerCase().trim()];
  const dark = () => matchMedia("(prefers-color-scheme: dark)").matches;
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  let library = null;
  function load() {
    library ??= new Promise((ok, fail) => {
      const css = Object.assign(document.createElement("link"), { rel: "stylesheet", href: `${LIB}.css`, integrity: CSS_SRI, crossOrigin: "anonymous" });
      const js = Object.assign(document.createElement("script"), { src: `${LIB}.js`, integrity: JS_SRI, crossOrigin: "anonymous" });
      js.onload = () => (window.maplibregl ? ok(window.maplibregl) : fail(new Error("map library missing")));
      js.onerror = () => fail(new Error("map library blocked"));
      document.head.append(css, js);
      setTimeout(() => fail(new Error("map library timed out")), 20000);
    });
    return library;
  }

  // Warm the stock street style towards the page palette, and raise the hills.
  function tint(map) {
    const night = dark();
    const set = (id, prop, value) => { try { if (map.getLayer(id)) map.setPaintProperty(id, prop, value); } catch { /* style changed upstream */ } };
    set("background", "background-color", night ? "#111c36" : "#f6f1e7");
    set("water", "fill-color", night ? "#1c3358" : "#b9d3e3");
    for (const layer of map.getStyle().layers) {
      if (/^(poi|label_other_poi)/.test(layer.id) || /oneway|housenum/.test(layer.id)) map.setLayoutProperty(layer.id, "visibility", "none");
      if (!night) continue;                                  // the stock night style is too dim to read
      if (layer.type === "symbol") { set(layer.id, "text-color", "#b7c2da"); set(layer.id, "text-halo-color", "#0d162b"); set(layer.id, "text-halo-width", 1.2); }
      else if (layer.type === "line" && /motorway|major|trunk/.test(layer.id)) set(layer.id, "line-color", "#55699c");
      else if (layer.type === "line" && /highway|road|street|minor|path/.test(layer.id)) set(layer.id, "line-color", "#33446f");
    }
    try {
      map.addSource("relief", { type: "raster-dem", tiles: [RELIEF], encoding: "terrarium", tileSize: 256, maxzoom: 12, attribution: "Relief: Mapzen, AWS" });
      const before = map.getStyle().layers.find((l) => /^(tunnel|road|bridge|building|highway|aeroway)/.test(l.id))?.id;
      map.addLayer({ id: "relief", type: "hillshade", source: "relief", paint: {
        "hillshade-exaggeration": night ? 0.45 : 0.5,
        "hillshade-shadow-color": night ? "#050a18" : "#4d5a4a", "hillshade-highlight-color": night ? "#33456f" : "#fffaf0", "hillshade-accent-color": night ? "#0a1228" : "#6b7a5e",
      } }, before);
    } catch { /* relief is a bonus */ }
  }

  // Returns { update(areas), select(area), hover(area) }.
  async function create(el, onPick) {
    const gl = await load();
    const map = new gl.Map({
      container: el, style: `https://tiles.openfreemap.org/styles/${dark() ? "dark" : "liberty"}`,
      bounds: [[72.80, 33.45], [73.25, 33.76]], fitBoundsOptions: { padding: 34 },
      minZoom: 8.5, maxZoom: 15, cooperativeGestures: true, dragRotate: false, pitchWithRotate: false, touchPitch: false,
      attributionControl: { compact: true },
      locale: { "CooperativeGesturesHandler.WindowsHelpText": "Hold Ctrl and scroll to zoom", "CooperativeGesturesHandler.MacHelpText": "Hold ⌘ and scroll to zoom", "CooperativeGesturesHandler.MobileHelpText": "Use two fingers to move the map", "Map.Title": "Map of Islamabad" },
    });
    map.on("styleimagemissing", (e) => { if (!map.hasImage(e.id)) map.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) }); });
    map.touchZoomRotate.disableRotation();
    map.addControl(new gl.NavigationControl({ showCompass: false }), "top-right");
    await new Promise((ok, fail) => {
      const timer = setTimeout(() => fail(new Error("map tiles timed out")), 20000);
      map.once("style.load", () => { clearTimeout(timer); ok(); });
      map.once("error", (e) => { if (!map.isStyleLoaded()) { clearTimeout(timer); fail(e.error || new Error("map style failed")); } });
    }).catch((e) => { map.remove(); throw e; });
    tint(map);

    let pins = [], chosen = "";
    const overview = () => map.fitBounds([[72.80, 33.45], [73.25, 33.76]], { padding: 34, animate: !still() });

    // Show a name only where it doesn't cover another pin.
    function label() {
      const taken = pins.map((p) => { const q = map.project(p.at); return { x: q.x - 16, y: q.y - 16, w: 32, h: 32 }; });
      const hits = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      pins.forEach((p, i) => {
        const q = map.project(p.at), w = p.area.length * 6.6 + 8, box = { x: q.x - w / 2, y: q.y + 16, w, h: 18 };
        const room = !taken.some((t, j) => j !== i && hits(t, box)) && box.x > 0 && box.x + w < map.getContainer().clientWidth;
        p.node.classList.toggle("named", room);
        if (room) taken.push(box);
      });
    }
    map.on("moveend", label);
    map.on("resize", label);

    function update(areas) {
      pins.forEach((p) => p.marker.remove());
      pins = areas.filter((a) => at(a.area)).map(({ area, count }) => {
        const node = document.createElement("button");
        node.type = "button"; node.className = "map-pin";
        node.setAttribute("aria-label", `${area}, ${count} ${count === 1 ? "home" : "homes"}`);
        node.setAttribute("aria-pressed", String(area === chosen));
        node.innerHTML = `<b>${count}</b><span></span>`;
        node.querySelector("span").textContent = area;
        node.addEventListener("click", (e) => { e.stopPropagation(); onPick(area); });
        return { area, node, at: at(area), marker: new gl.Marker({ element: node }).setLngLat(at(area)).addTo(map) };
      });
      label();
    }
    function select(area) {
      const before = chosen;
      chosen = at(area) ? area : "";
      pins.forEach((p) => p.node.setAttribute("aria-pressed", String(p.area === chosen)));
      if (chosen) map.flyTo({ center: at(chosen), zoom: 12.6, duration: still() ? 0 : 1100 });
      else if (before) overview();
    }
    const hover = (area) => pins.forEach((p) => p.node.classList.toggle("lit", p.area === area));

    const appearance = matchMedia("(prefers-color-scheme: dark)");
    appearance.addEventListener?.("change", () => {
      map.setStyle(`https://tiles.openfreemap.org/styles/${dark() ? "dark" : "liberty"}`, { diff: false });
      map.once("style.load", () => tint(map));
    });
    return { update, select, hover };
  }

  return { create, at };
})();
