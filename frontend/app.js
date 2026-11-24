// Dastak customer page: homes, the map, what we remember for the visitor, and the chat with the assistant.
(() => {
  const store = {
    get(k, area = localStorage) { try { return area.getItem(k); } catch { return null; } },
    set(k, v, area = localStorage) { try { area.setItem(k, v); } catch { /* storage blocked: still works for this visit */ } },
  };
  const API = (store.get("pc_api") || window.DASTAK_API || "http://127.0.0.1:8000").replace(/\/$/, "");
  const newId = (p) => `${p}-${crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)}`;

  // One user_id per browser (long-term memory), one thread_id per conversation (short-term memory).
  const userId = store.get("pc_user_id") || newId("web");
  let threadId = store.get("pc_thread_id") || newId("chat");
  store.set("pc_user_id", userId);
  store.set("pc_thread_id", threadId);

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name) => `<svg class="i" aria-hidden="true"><use href="icons.svg#${name}"/></svg>`;
  const pkr = (n) => (n >= 1e7 ? `PKR ${+(n / 1e7).toFixed(2)} crore` : n >= 1e5 ? `PKR ${+(n / 1e5).toFixed(2)} lakh` : `PKR ${Number(n).toLocaleString("en")}`);
  const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

  // ── homes ──
  const PAGE = 8;
  let purpose = "sale", shown = [], visible = PAGE, savedOnly = false;
  const catalog = new Map();                                   // every home by id, for saved homes and chat previews
  const PRICES = {
    sale: [["", "Any"], [10e6, "Up to 1 crore"], [20e6, "Up to 2 crore"], [30e6, "Up to 3 crore"], [50e6, "Up to 5 crore"], [100e6, "Up to 10 crore"], [250e6, "Up to 25 crore"]],
    rent: [["", "Any"], [50e3, "Up to 50,000 a month"], [100e3, "Up to 1 lakh a month"], [150e3, "Up to 1.5 lakh a month"], [300e3, "Up to 3 lakh a month"]],
  };
  const fillPrices = () => { $("#f-price").innerHTML = PRICES[purpose].map(([v, l]) => `<option value="${v}">${l}</option>`).join(""); };

  function card(l) {
    const type = { house: "House", flat: "Flat", plot: "Plot" }[l.property_type] || l.property_type;
    const place = l.sector && l.sector !== l.area ? `${l.sector}, ${l.area}` : l.area;
    const facts = [["home", type], l.beds && ["bed", plural(l.beds, "bed")], l.baths && ["bath", plural(l.baths, "bath")], ["size", `${l.size_marla} marla`]].filter(Boolean);
    return `<article class="card" data-id="${l.id}" data-area="${esc(l.area)}">
      <div class="photo">${Photos.img(l)}${Me.fits(l) ? `<span class="fits">${icon("check")}Fits your search</span>` : ""}<span class="plate">${esc(l.area)}</span>
        <button class="save" type="button" data-save="${l.id}" aria-pressed="${Me.isSaved(l.id)}" aria-label="Save ${esc(l.title)}, ${esc(l.area)}">${icon("heart")}</button></div>
      <div class="card-body">
        <p class="price">${pkr(l.price_pkr)}${l.purpose === "rent" ? " <small>a month</small>" : ""}</p>
        <h3>${esc(l.title)}</h3>
        <ul class="facts">${facts.map(([i, t]) => `<li>${icon(i)}${esc(t)}</li>`).join("")}<li>${icon("pin")}${esc(place)}</li></ul>
        ${l.description ? `<details class="more"><summary>About this home<svg class="i chev" aria-hidden="true"><use href="icons.svg#down"/></svg></summary><p>${esc(l.description)}</p></details>` : ""}
        <button class="btn btn-quiet" type="button" data-ask="${l.id}" aria-label="Ask about ${esc(l.title)}, ${esc(l.area)}">${icon("message")}Ask about this home</button>
      </div></article>`;
  }

  async function getListings(params) {
    const res = await fetch(`${API}/listings?${new URLSearchParams(params)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function draw() {
    $("#grid").innerHTML = shown.slice(0, visible).map(card).join("");
    const left = shown.length - visible;
    $("#more-homes").hidden = left <= 0;
    $("#more-homes").textContent = `Show ${plural(Math.max(left, 0), "more home", "more homes")}`;
  }

  let request = 0;
  async function loadListings() {
    const mine = ++request;                                  // a slow earlier answer must not overwrite a newer one
    visible = PAGE;
    if (savedOnly) {
      shown = Me.saved.map((id) => catalog.get(id)).filter(Boolean);
      $("#result-note").textContent = plural(shown.length, "saved home");
      $("#clear").hidden = false;
      draw();
      return;
    }
    const params = { purpose };
    for (const [key, id] of [["area", "#f-area"], ["property_type", "#f-type"], ["min_beds", "#f-beds"], ["max_price_pkr", "#f-price"]]) {
      const v = $(id).value.trim();
      if (v) params[key] = v;
    }
    $("#clear").hidden = Object.keys(params).length === 1;
    $("#more-homes").hidden = true;
    $("#grid").innerHTML = '<div class="skeleton"></div>'.repeat(4);
    $("#result-note").textContent = "Loading homes";
    try {
      const { exact, listings } = await getListings(params);
      if (mine !== request) return;
      $("#result-note").textContent = exact ? `${plural(listings.length, "home")} ${purpose === "rent" ? "to rent" : "for sale"}` : "No exact match. These are the closest.";
      shown = exact ? [...listings].sort((a, b) => Me.fits(b) - Me.fits(a)) : listings;   // homes that fit come first
      draw();
    } catch (error) {
      if (mine !== request) return;
      console.error("Dastak API", API, error);
      $("#result-note").textContent = "";
      $("#grid").innerHTML = '<div class="message"><p>Homes couldn\'t load. Check your connection, then try again.</p><button class="btn btn-quiet" type="button" data-retry>Try again</button></div>';
    }
  }

  // ── map ──
  let realMap = null, areas = [], mapStarted = false, schematic = false;

  async function loadAreas() {
    const wanted = purpose;
    try {
      const [sale, rent] = await Promise.all([getListings({ purpose: "sale" }), getListings({ purpose: "rent" })]);
      [...sale.listings, ...rent.listings].forEach((l) => catalog.set(l.id, l));
      if (wanted !== purpose) return;
      const count = {};
      (purpose === "rent" ? rent : sale).listings.forEach((l) => { count[l.area] = (count[l.area] || 0) + 1; });
      areas = Object.entries(count).map(([area, n]) => ({ area, count: n })).sort((a, b) => a.area.localeCompare(b.area, "en", { numeric: true }));
      const keep = $("#f-area").value;
      $("#f-area").innerHTML = '<option value="">Any</option>' + areas.map((a) => `<option>${esc(a.area)}</option>`).join("");
      $("#f-area").value = areas.some((a) => a.area === keep) ? keep : "";
      drawMap(); welcome(); fillFound();
    } catch { $("#map-note").textContent = "The map will fill in when homes load."; }
  }

  function drawMap() {
    if (realMap) { realMap.update(areas); realMap.select($("#f-area").value); return; }
    if (!schematic || !areas.length) return;
    const el = $("#map").cloneNode(false);                   // drop old listeners when switching buy / rent
    $("#map").replaceWith(el);
    SectorMap.full(el, areas, pickArea);
    SectorMap.select(el, $("#f-area").value);
  }

  async function startMap() {
    if (mapStarted) return;
    mapStarted = true;
    const holder = document.createElement("div");
    holder.style.cssText = "position:absolute;inset:0";
    $("#map").append(holder);
    try {
      realMap = await RealMap.create(holder, pickArea);
      $("#map .map-wait")?.remove();
    } catch (error) {
      console.warn("Street map unavailable, using the sector map:", error.message);
      schematic = true;
      $("#map").innerHTML = "";
      $("#map-fine").textContent = "Schematic, not to scale.";
    }
    drawMap();
  }
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((seen, watch) => { if (seen.some((s) => s.isIntersecting)) { watch.disconnect(); startMap(); } }, { rootMargin: "300px" }).observe($("#map"));
  } else startMap();

  function pickArea(area) {
    savedOnly = false;
    $("#f-area").value = $("#f-area").value === area ? "" : area;
    filter();
    if (matchMedia("(max-width: 1060px)").matches && $("#f-area").value) $("#grid").scrollIntoView({ block: "start" });
  }
  function showArea() {
    const area = $("#f-area").value;
    if (realMap) realMap.select(area); else if (schematic) SectorMap.select($("#map"), area);
    $("#map-note").textContent = area ? `Showing ${area}.` : "Choose an area to see its homes.";
  }

  // ── what we remember for this visitor (this device only) ──
  const returning = Me.facts().length > 0 || Me.upcoming().length > 0 || Me.saved.length > 0;
  function welcome() {
    const visit = Me.upcoming()[0], saved = Me.saved.filter((id) => catalog.has(id)).length, items = [];
    if (visit) items.push(["visit", "calendar", visit.when, `Visit to ${visit.title}, ${visit.area}`]);
    if (Me.knowsSearch()) items.push(["search", "search", Me.describe(), "Pick up your search"]);
    if (saved) items.push(["saved", "heart", plural(saved, "saved home"), "See your shortlist"]);
    $("#welcome-title").textContent = !returning ? "Your search so far" : Me.lead.name ? `Welcome back, ${Me.lead.name}` : "Pick up where you left off";
    $("#welcome-items").innerHTML = items.map(([go, i, title, note]) => `<button type="button" data-go="${go}">${icon(i)}<span><b>${esc(title)}</b><small>${esc(note)}</small></span>${icon("right")}</button>`).join("");
    $("#welcome").hidden = !items.length;

    $("#saved-only").hidden = !saved && !savedOnly;
    $("#saved-only span").textContent = `Saved (${saved})`;
    $("#saved-only").setAttribute("aria-pressed", String(savedOnly));

    const facts = Me.facts();
    $("#about").hidden = !facts.length;
    $("#about-line").textContent = `I remember: ${facts.join(", ")}`;
    $("#about-facts").innerHTML = facts.map((f) => `<li>${esc(f)}</li>`).join("");
  }

  function setPurpose(value) {
    document.querySelectorAll(".segmented button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.purpose === value)));
    if (purpose === value) return false;
    purpose = value; fillPrices();
    return true;
  }
  function resumeSearch() {
    const { lead } = Me;
    savedOnly = false;
    $("#filters").reset();
    if (setPurpose(lead.purpose || "sale")) loadAreas();
    const area = [...$("#f-area").options].find((o) => lead.area && o.value && (o.value.toLowerCase().includes(lead.area.toLowerCase()) || lead.area.toLowerCase().includes(o.value.toLowerCase())));
    if (area) $("#f-area").value = area.value;
    if (lead.property_type) $("#f-type").value = lead.property_type;
    if (lead.beds) $("#f-beds").value = String(Math.min(lead.beds, 5));
    if (lead.budget) {                                       // the exact budget, not the nearest step
      const opt = new Option(`Up to ${Me.facts().at(-1).replace("Up to ", "")}`, lead.budget);
      if (![...$("#f-price").options].some((o) => +o.value === lead.budget)) $("#f-price").add(opt);
      $("#f-price").value = String(lead.budget);
    }
    filter(); welcome();
    $("#homes").scrollIntoView({ block: "start" });
  }
  function showSaved(on) { savedOnly = on; if (on) { $("#filters").reset(); showArea(); } welcome(); loadListings(); }

  // ── chat ──
  const DID = {
    search_listings: "searched homes", get_listing: "opened the listing", check_slots: "checked visit times",
    calculate_installment: "worked out the installment", save_lead_profile: "noted your preferences", my_data: "looked up your data",
    forget_me: "deleted your data", request_visit: "checked the visit time", reschedule_visit: "checked the new time", confirm_visit: "booked the visit",
    cancel_visit: "cancelled the visit", my_visits: "looked up your visits", schedule_followup: "queued a follow-up for the agency",
  };
  const ASKS_YES = /shall i\b|should i (book|confirm|cancel|delete|move)|reply\s+["“']?yes|(haan|han) (kah|likh)|confirm kar/i;
  const key = () => `pc_transcript_${threadId}`;
  let transcript = [], busy = false, opener = null;

  function md(text) {                                        // tiny and safe: escape first, then bold, lists, paragraphs
    let html = "", list = false;
    for (const line of esc(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").split("\n")) {
      const item = line.match(/^\s*(?:[-•*]|\d+[.)])\s+(.*)/);
      if (item) { html += `${list ? "" : "<ul>"}<li>${item[1]}</li>`; list = true; continue; }
      if (list) { html += "</ul>"; list = false; }
      if (line.trim()) html += `<p>${line}</p>`;
    }
    return list ? `${html}</ul>` : html;
  }

  const body = $("#chat-body");
  function append(node) { body.appendChild(node); body.scrollTop = body.scrollHeight; return node; }
  function el(cls, html = "") { const n = document.createElement("div"); n.className = cls; n.innerHTML = html; return n; }

  // Photo previews for the homes a reply names by number. They wait for the catalog if it hasn't loaded yet.
  function fillFound() {
    document.querySelectorAll(".found[data-ids]").forEach((n) => {
      const homes = n.dataset.ids.split(",").map((id) => catalog.get(+id)).filter(Boolean);
      if (!homes.length) return;
      n.removeAttribute("data-ids");
      n.innerHTML = homes.map((l) => `<button type="button" data-say="Tell me about listing #${l.id}.">${Photos.thumb(l)}<span><b>${esc(l.title)}</b><small>${pkr(l.price_pkr)}${l.purpose === "rent" ? " a month" : ""}<br>${esc(l.area)}</small></span>${icon("right")}</button>`).join("");
      body.scrollTop = body.scrollHeight;
    });
  }

  function addBubble(role, text, tools = [], save = true) {
    const n = append(el(`bubble ${role}-msg`));
    if (role === "agent") n.innerHTML = md(text); else n.textContent = text;
    if (role === "agent" && tools.some((t) => /search_listings|get_listing/.test(t))) {
      const ids = [...new Set([...text.matchAll(/#(\d+)/g)].map((m) => m[1]))].slice(0, 4);
      if (ids.length) { append(el("found")).dataset.ids = ids.join(","); fillFound(); }
    }
    const nothingDone = /so nothing (was booked|changed)|kuch book nahi hua|kuch tabdeel nahi hua/.test(text);
    const did = nothingDone ? [] : [...new Set(tools)].map((t) => DID[t] || t.replace(/_/g, " "));
    if (did.length) append(el("did", `${icon("check")}<span>${esc(did.join(", ").replace(/^./, (c) => c.toUpperCase()))}</span>`));
    if (save) { transcript.push({ role, text, tools }); store.set(key(), JSON.stringify(transcript.slice(-60)), sessionStorage); }
    return n;
  }

  function suggest(text) {
    const yes = text && ASKS_YES.test(text);
    $("#quick").innerHTML = yes ? '<button type="button" class="yes" data-say="Yes">Yes</button><button type="button" data-say="Not yet">Not yet</button>' : "";
    body.scrollTop = body.scrollHeight;
  }

  function greeting() {
    const hi = Me.lead.name ? `Salam ${Me.lead.name}!` : "Salam!";
    return Me.knowsSearch() ? `${hi} Still looking for this? ${Me.describe()}. Ask me to search again, or tell me what changed.`
      : `${hi} Looking to buy or rent in Islamabad? Tell me the sector, your budget and what kind of home.`;
  }

  function restore() {
    body.innerHTML = "";
    suggest("");
    try { transcript = JSON.parse(store.get(key(), sessionStorage) || "[]"); } catch { transcript = []; }
    if (!transcript.length) addBubble("agent", greeting(), [], false);
    transcript.forEach((m) => addBubble(m.role, m.text, m.tools, false));
    const last = transcript[transcript.length - 1];
    if (last?.role === "agent") suggest(last.text);
  }

  async function send(text, retry = false) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; $("#send").disabled = true; suggest(""); $("#about").open = false;
    if (!retry) addBubble("user", text);
    const typing = append(el("bubble agent-msg typing", "<p>Thinking…</p>"));
    const thread = threadId;
    try {
      const res = await fetch(`${API}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: userId, thread_id: thread, message: text }) });
      const data = await res.json();
      if (typeof data.reply !== "string") throw new Error(`HTTP ${res.status}`);
      typing.remove();
      Me.learn(data.reply, data.tool_calls || []);
      welcome();
      if (thread !== threadId) return;                       // they started a new chat meanwhile
      if (Me.forgot(data.reply)) { transcript = []; body.innerHTML = ""; }   // the server erased the chat, so this browser does too
      addBubble("agent", data.reply, (data.tool_calls || []).map((c) => c.name));
      suggest(data.reply);
      if (!savedOnly && shown.length) draw();                // refresh "Fits your search"
    } catch (error) {
      console.error("Dastak API", API, error);
      typing.remove();
      const n = addBubble("error", "That didn't send. Check your connection, then try again.", [], false);
      const again = document.createElement("button");
      again.type = "button"; again.textContent = "Try again";
      again.onclick = () => { n.remove(); send(text, true); };
      n.appendChild(again);
    } finally { busy = false; $("#send").disabled = false; }
  }

  function openChat(say, from = document.activeElement) {
    opener = from;
    $("#chat").inert = false; $("#chat").classList.add("open"); $("#fab").hidden = true;
    $("#chat-text").focus();
    body.scrollTop = body.scrollHeight;
    if (say) send(say);
  }
  function closeChat() {
    $("#chat").classList.remove("open"); $("#chat").inert = true; $("#fab").hidden = false;
    if (opener?.isConnected && opener !== document.body) opener.focus();
    if (document.activeElement !== opener) $("#fab").focus();   // the opener is gone or folded away
  }

  // ── wire up ──
  function filter() { if (savedOnly) { savedOnly = false; welcome(); } showArea(); loadListings(); }
  function toggle(button, target) {
    const open = target.classList.toggle("open");
    button.setAttribute("aria-expanded", String(open));
  }
  $("#filters").addEventListener("submit", (e) => { e.preventDefault(); filter(); });
  ["#f-type", "#f-beds", "#f-price", "#f-area"].forEach((id) => $(id).addEventListener("change", filter));
  $("#clear").addEventListener("click", () => { $("#filters").reset(); filter(); });
  $("#saved-only").addEventListener("click", () => showSaved(!savedOnly));
  $("#toggle-filters").addEventListener("click", (e) => toggle(e.currentTarget, $("#filter-fields")));
  $("#toggle-map").addEventListener("click", (e) => toggle(e.currentTarget, $("#map-card")));
  document.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => {
    if (!setPurpose(b.dataset.purpose) && !savedOnly) return;
    savedOnly = false; welcome(); loadListings(); loadAreas();
  }));
  $("#more-homes").addEventListener("click", () => {
    const first = visible;
    visible = shown.length; draw();
    $("#grid").children[first]?.querySelector("button")?.focus();
  });

  const grid = $("#grid");
  grid.addEventListener("click", (e) => {
    if (e.target.closest("[data-retry]")) { loadListings(); loadAreas(); return; }
    const heart = e.target.closest("[data-save]");
    if (heart) { heart.setAttribute("aria-pressed", String(Me.toggleSaved(+heart.dataset.save))); welcome(); return; }
    const b = e.target.closest("[data-ask]");
    if (b) openChat(`Tell me about listing #${b.dataset.ask}.`, b);
  });
  const areaOf = (e) => e.target.closest?.(".card")?.dataset.area;
  grid.addEventListener("pointerover", (e) => realMap?.hover(areaOf(e)));
  grid.addEventListener("pointerleave", () => realMap?.hover(""));
  grid.addEventListener("focusin", (e) => realMap?.hover(areaOf(e)));
  grid.addEventListener("focusout", () => realMap?.hover(""));

  // A photo that can't load becomes a locator map, so a card is never broken.
  document.addEventListener("error", (e) => {
    const img = e.target;
    if (img.tagName !== "IMG") return;
    if (!img.dataset.again && img.closest(".photo, .found")) {   // one retry: phone networks drop requests
      img.dataset.again = "1"; img.removeAttribute("srcset");
      const { src } = img;
      setTimeout(() => { img.src = `${src}&again=1`; }, 1200);
    } else if (img.closest(".photo")) img.outerHTML = SectorMap.mini(img.closest(".card").dataset.area);
    else if (img.closest(".found")) img.outerHTML = '<span class="ph"></span>';
    else if (img.matches(".hero-photo")) img.remove();
    else if (img.closest(".how-photo")) img.closest(".how-photo").remove();
  }, true);

  $("#welcome-items").addEventListener("click", (e) => {
    const go = e.target.closest("[data-go]")?.dataset.go;
    if (go === "search") resumeSearch();
    if (go === "saved") { showSaved(true); $("#homes").scrollIntoView({ block: "start" }); }
    if (go === "visit") openChat("Show my visits", e.target.closest("button"));
  });
  $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const t = $("#ask-text").value; $("#ask-text").value = ""; openChat(t, $("#ask-text")); });
  $("#examples").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) openChat(b.textContent, b); });
  document.querySelectorAll("[data-open-say]").forEach((b) => b.addEventListener("click", () => openChat(b.dataset.openSay, b)));
  $("#fab").addEventListener("click", () => openChat("", $("#fab")));
  $("#close-chat").addEventListener("click", closeChat);
  $("#chat").addEventListener("keydown", (e) => { if (e.key === "Escape") closeChat(); });
  $("#chat").addEventListener("click", (e) => { const b = e.target.closest("[data-say]"); if (b) send(b.dataset.say); });
  $("#new-chat").addEventListener("click", () => { threadId = newId("chat"); store.set("pc_thread_id", threadId); transcript = []; restore(); $("#chat-text").focus(); });
  $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); if (busy) return; const t = $("#chat-text").value; $("#chat-text").value = ""; send(t); });

  fillPrices(); welcome(); restore(); loadListings(); loadAreas();
})();
