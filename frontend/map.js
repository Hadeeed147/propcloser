// The sector map: Islamabad is a planned grid, so "where" is the first thing a buyer says. Schematic, not to scale.
window.SectorMap = (() => {
  const COL = 18, ROW = 18, X0 = 34, Y0 = 46, MAX = 17;
  const ROWS = ["B", "C", "D", "E", "F", "G", "H", "I"];
  const RANGE = { B: [17, 17], C: [13, 17], D: [10, 17], E: [7, 17], F: [5, 17], G: [5, 17], H: [8, 17], I: [8, 17] };
  // Housing societies outside the lettered grid.
  const SOCIETY = {
    "bahria enclave": [346, 92], "park view city": [344, 116], "gulberg residencia": [334, 212], "pakistan town": [300, 190],
    "dha phase 2": [308, 236], "dha phase 5": [340, 254], "bahria town phase 8": [100, 252], "top city 1": [40, 226],
  };
  const x = (n) => X0 + (MAX - n) * COL, y = (r) => Y0 + ROWS.indexOf(r) * ROW;

  function place(area) {
    const key = (area || "").toLowerCase().trim();
    const m = key.match(/^([b-i])-?(\d{1,2})/);
    if (m) return { x: x(+m[2]) + COL / 2, y: y(m[1].toUpperCase()) + ROW / 2, cell: true };
    const s = SOCIETY[key];
    return s ? { x: s[0], y: s[1], cell: false } : null;
  }

  const grid = ROWS.map((r) => {
    let out = "";
    for (let n = RANGE[r][0]; n <= RANGE[r][1]; n++) out += `<rect x="${x(n) + 1}" y="${y(r) + 1}" width="${COL - 2}" height="${ROW - 2}" rx="2"/>`;
    return out;
  }).join("");
  const ridge = `<path class="ridge" d="M6 34 34 20 58 30 88 12 118 26 150 8 184 24 214 10 246 26 280 14 312 30 346 18 356 26"/>`;
  const base = `${ridge}<g class="cells">${grid}</g>`;
  const axes = ROWS.map((r) => `<text class="axis" x="${X0 - 9}" y="${y(r) + 13}">${r}</text>`).join("")
    + [17, 15, 13, 11, 9].map((n) => `<text class="axis" x="${x(n) + COL / 2}" y="${y("I") + ROW + 13}">${n}</text>`).join("");

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // Big interactive map. areas: [{area, count}]
  function full(el, areas, onPick) {
    const marks = areas.map(({ area, count }) => {
      const p = place(area);
      return p && `<g class="mark" role="button" tabindex="0" data-area="${esc(area)}" aria-pressed="false" aria-label="${esc(area)}, ${count} ${count === 1 ? "home" : "homes"}">
        <circle class="hit" cx="${p.x}" cy="${p.y}" r="17"/>${p.cell ? "" : `<text class="name" x="${p.x + (p.x > 250 ? -12 : 12)}" y="${p.y + 3.4}" ${p.x > 250 ? 'data-end' : ""}>${esc(area)}</text>`}<circle class="dot" cx="${p.x}" cy="${p.y}" r="8"/><text class="count" x="${p.x}" y="${p.y + 3.4}">${count}</text><title>${esc(area)}</title></g>`;
    }).filter(Boolean).join("");
    el.innerHTML = `<svg class="map" viewBox="0 0 362 268" role="group" aria-label="Map of sectors with homes"><text class="where" x="181" y="36">Margalla Hills</text>${base}${axes}${marks}</svg>`;
    const pick = (e) => { const g = e.target.closest(".mark"); if (g) { e.preventDefault(); onPick(g.dataset.area); } };
    el.addEventListener("click", pick);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") pick(e); });
  }

  function select(el, area) {
    el.querySelectorAll(".mark").forEach((g) => g.setAttribute("aria-pressed", String(g.dataset.area === area)));
  }

  // Small decorative locator for a card.
  function mini(area) {
    const p = place(area);
    return `<svg class="mini" viewBox="0 0 362 268" aria-hidden="true">${base}${p ? `<circle class="pin" cx="${p.x}" cy="${p.y}" r="13"/>` : ""}</svg>`;
  }

  return { full, select, mini, place };
})();
