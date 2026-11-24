// PropCloser customer page: sector map, homes and the chat with the assistant.
(() => {
  const store = {
    get(k, area = localStorage) { try { return area.getItem(k); } catch { return null; } },
    set(k, v, area = localStorage) { try { area.setItem(k, v); } catch { /* storage blocked: still works for this visit */ } },
  };
  const API = (store.get("pc_api") || window.PROPCLOSER_API || "http://127.0.0.1:8000").replace(/\/$/, "");
  const newId = (p) => `${p}-${crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)}`;

  // One user_id per browser (long-term memory), one thread_id per conversation (short-term memory).
  const userId = store.get("pc_user_id") || newId("web");
  let threadId = store.get("pc_thread_id") || newId("chat");
  store.set("pc_user_id", userId);
  store.set("pc_thread_id", threadId);

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pkr = (n) => (n >= 1e7 ? `PKR ${+(n / 1e7).toFixed(2)} crore` : n >= 1e5 ? `PKR ${+(n / 1e5).toFixed(2)} lakh` : `PKR ${Number(n).toLocaleString("en")}`);

  // ── homes ──
  let purpose = "sale";
  const PRICES = {
    sale: [["", "Any"], [10e6, "Up to 1 crore"], [20e6, "Up to 2 crore"], [30e6, "Up to 3 crore"], [50e6, "Up to 5 crore"], [100e6, "Up to 10 crore"], [250e6, "Up to 25 crore"]],
    rent: [["", "Any"], [50e3, "Up to 50,000 a month"], [100e3, "Up to 1 lakh a month"], [150e3, "Up to 1.5 lakh a month"], [300e3, "Up to 3 lakh a month"]],
  };
  const fillPrices = () => { $("#f-price").innerHTML = PRICES[purpose].map(([v, l]) => `<option value="${v}">${l}</option>`).join(""); };

  function card(l) {
    const facts = [l.beds && `${l.beds} bed`, l.baths && `${l.baths} bath`, `${l.size_marla} marla`].filter(Boolean).join(" · ");
    const type = { house: "House", flat: "Flat", plot: "Plot" }[l.property_type] || l.property_type;
    return `<article class="card">
      <div class="locator">${SectorMap.mini(l.area)}<span class="sign">${esc(l.area)}</span></div>
      <div class="card-body">
        <div class="price">${pkr(l.price_pkr)}${l.purpose === "rent" ? " <small>a month</small>" : ""}</div>
        <h3>${esc(l.title)}</h3>
        <p class="facts">${type} for ${l.purpose === "rent" ? "rent" : "sale"} · ${facts}${l.sector && l.sector !== l.area ? ` · ${esc(l.sector)}` : ""}</p>
        <button class="btn btn-quiet" type="button" data-ask="${l.id}" aria-label="Ask about ${esc(l.title)}, ${esc(l.area)}">Ask about this home</button>
      </div></article>`;
  }

  async function getListings(params) {
    const res = await fetch(`${API}/listings?${new URLSearchParams(params)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  let request = 0;
  async function loadListings() {
    const mine = ++request;                                  // a slow earlier answer must not overwrite a newer one
    const params = { purpose };
    for (const [key, id] of [["area", "#f-area"], ["property_type", "#f-type"], ["min_beds", "#f-beds"], ["max_price_pkr", "#f-price"]]) {
      const v = $(id).value.trim();
      if (v) params[key] = v;
    }
    $("#clear").hidden = Object.keys(params).length === 1;
    $("#grid").innerHTML = '<div class="skeleton"></div>'.repeat(3);
    $("#result-note").textContent = "Loading homes";
    try {
      const { exact, listings } = await getListings(params);
      if (mine !== request) return;
      $("#result-note").textContent = exact ? `${listings.length} ${listings.length === 1 ? "home" : "homes"}` : "No exact match. These are the closest.";
      $("#grid").innerHTML = listings.map(card).join("");
    } catch (error) {
      if (mine !== request) return;
      console.error("PropCloser API", API, error);
      $("#result-note").textContent = "";
      $("#grid").innerHTML = '<div class="message"><p>Homes couldn\'t load. Check your connection, then try again.</p><button class="btn btn-quiet" type="button" data-retry>Try again</button></div>';
    }
  }

  async function loadMap() {
    try {
      const { listings } = await getListings({ purpose });
      const count = {};
      listings.forEach((l) => { count[l.area] = (count[l.area] || 0) + 1; });
      const areas = Object.entries(count).map(([area, n]) => ({ area, count: n })).sort((a, b) => a.area.localeCompare(b.area));
      const el = $("#map").cloneNode(false);                 // drop old listeners when switching buy / rent
      $("#map").replaceWith(el);
      SectorMap.full(el, areas, pickArea);
      SectorMap.select(el, $("#f-area").value);
      $("#areas").innerHTML = areas.map((a) => `<option value="${esc(a.area)}">`).join("");
    } catch { $("#map-note").textContent = "The map will appear when homes load."; }
  }

  function pickArea(area) {
    const same = $("#f-area").value === area;
    $("#f-area").value = same ? "" : area;
    showArea();
    loadListings();
    if (!same) $("#listings").scrollIntoView({ block: "start" });
  }
  function showArea() {
    const area = $("#f-area").value;
    SectorMap.select($("#map"), area);
    $("#map-note").textContent = area ? `Showing ${area}.` : "Choose a sector to see its homes.";
  }

  // ── chat ──
  const DID = {
    search_listings: "searched homes", get_listing: "opened the listing", check_slots: "checked visit times",
    calculate_installment: "worked out the installment", save_lead_profile: "noted your preferences", my_data: "looked up your data",
    forget_me: "deleted your data", request_visit: "held a visit time", reschedule_visit: "held a new time", confirm_visit: "booked the visit",
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

  function append(node) { const body = $("#chat-body"); body.appendChild(node); body.scrollTop = body.scrollHeight; return node; }
  function el(cls, html = "") { const n = document.createElement("div"); n.className = cls; n.innerHTML = html; return n; }

  function addBubble(role, text, tools = [], save = true) {
    const n = append(el(`bubble ${role}-msg`));
    if (role === "agent") n.innerHTML = md(text); else n.textContent = text;
    const did = [...new Set(tools)].map((t) => DID[t] || t.replace(/_/g, " "));
    if (did.length) append(el("did")).textContent = did.join(", ").replace(/^./, (c) => c.toUpperCase());
    if (save) { transcript.push({ role, text, tools }); store.set(key(), JSON.stringify(transcript.slice(-60)), sessionStorage); }
    return n;
  }

  function suggest(text) {
    const yes = text && ASKS_YES.test(text);
    $("#quick").innerHTML = yes ? '<button type="button" class="yes" data-say="Yes">Yes</button><button type="button" data-say="Not yet">Not yet</button>' : "";
  }

  function restore() {
    $("#chat-body").innerHTML = "";
    suggest("");
    try { transcript = JSON.parse(store.get(key(), sessionStorage) || "[]"); } catch { transcript = []; }
    if (!transcript.length) addBubble("agent", "Salam! Looking to buy or rent in Islamabad? Tell me the sector, your budget and what kind of home.", [], false);
    transcript.forEach((m) => addBubble(m.role, m.text, m.tools, false));
    const last = transcript[transcript.length - 1];
    if (last?.role === "agent") suggest(last.text);
  }

  async function send(text, retry = false) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; $("#send").disabled = true; suggest("");
    if (!retry) addBubble("user", text);
    const typing = append(el("bubble agent-msg typing", "<p>Thinking…</p>"));
    const thread = threadId;
    try {
      const res = await fetch(`${API}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: userId, thread_id: thread, message: text }) });
      const data = await res.json();
      typing.remove();
      if (thread !== threadId) return;                       // they started a new chat meanwhile
      addBubble("agent", data.reply, (data.tool_calls || []).map((c) => c.name));
      suggest(data.reply);
    } catch (error) {
      console.error("PropCloser API", API, error);
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
    if (say) send(say);
  }
  function closeChat() {
    $("#chat").classList.remove("open"); $("#chat").inert = true; $("#fab").hidden = false;
    (opener?.isConnected && opener !== document.body ? opener : $("#fab")).focus();
  }

  // ── wire up ──
  const filter = () => { showArea(); loadListings(); };
  $("#filters").addEventListener("submit", (e) => { e.preventDefault(); filter(); });
  ["#f-type", "#f-beds", "#f-price", "#f-area"].forEach((id) => $(id).addEventListener("change", filter));
  $("#clear").addEventListener("click", () => { $("#filters").reset(); filter(); });
  document.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".segmented button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    purpose = b.dataset.purpose; fillPrices(); loadListings(); loadMap();
  }));
  $("#grid").addEventListener("click", (e) => {
    if (e.target.closest("[data-retry]")) { loadListings(); loadMap(); return; }
    const b = e.target.closest("[data-ask]");
    if (b) openChat(`Tell me about listing #${b.dataset.ask}.`, b);
  });
  $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const t = $("#ask-text").value; $("#ask-text").value = ""; openChat(t, $("#ask-text")); });
  $("#examples").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) openChat(b.textContent, b); });
  $("#fab").addEventListener("click", () => openChat("", $("#fab")));
  $("#close-chat").addEventListener("click", closeChat);
  $("#chat").addEventListener("keydown", (e) => { if (e.key === "Escape") closeChat(); });
  $("#chat").addEventListener("click", (e) => { const b = e.target.closest("[data-say]"); if (b) send(b.dataset.say); });
  $("#new-chat").addEventListener("click", () => { threadId = newId("chat"); store.set("pc_thread_id", threadId); transcript = []; restore(); $("#chat-text").focus(); });
  $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); if (busy) return; const t = $("#chat-text").value; $("#chat-text").value = ""; send(t); });

  fillPrices(); restore(); loadListings(); loadMap();
})();
