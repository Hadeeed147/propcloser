// PropCloser customer page: listings + chat with the agent API.
(() => {
  // ── storage helpers (never crash if storage is blocked) ──
  const store = {
    get(k, area = localStorage) { try { return area.getItem(k); } catch { return null; } },
    set(k, v, area = localStorage) { try { area.setItem(k, v); } catch { /* ignore */ } },
  };
  const API = (store.get("pc_api") || window.PROPCLOSER_API || "http://127.0.0.1:8000").replace(/\/$/, "");
  const newId = (p) => `${p}-${crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)}`;

  // One user_id per browser (long-term memory), one thread_id per conversation (short-term memory).
  let userId = store.get("pc_user_id") || newId("web");
  let threadId = store.get("pc_thread_id") || newId("chat");
  store.set("pc_user_id", userId);
  store.set("pc_thread_id", threadId);

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const pkr = (n) => {
    if (n >= 1e7) return `PKR ${+(n / 1e7).toFixed(2)} crore`;
    if (n >= 1e5) return `PKR ${+(n / 1e5).toFixed(2)} lakh`;
    return `PKR ${Number(n).toLocaleString()}`;
  };

  // ── listings ──
  let purpose = "sale";
  const PRICES = {
    sale: [["", "Any budget"], [10e6, "Up to 1 crore"], [20e6, "Up to 2 crore"], [30e6, "Up to 3 crore"], [50e6, "Up to 5 crore"], [100e6, "Up to 10 crore"], [250e6, "Up to 25 crore"]],
    rent: [["", "Any rent"], [50e3, "Up to 50k / month"], [100e3, "Up to 1 lakh / month"], [150e3, "Up to 1.5 lakh / month"], [300e3, "Up to 3 lakh / month"]],
  };
  const ICONS = {
    house: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>',
    flat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1M11 21v-3h2v3"/></svg>',
    plot: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18l6-12 6 12"/><path d="M13 18l4-7 4 7"/><path d="M2 18h20"/></svg>',
  };

  function fillPrices() {
    $("#f-price").innerHTML = PRICES[purpose].map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
  }

  async function loadListings() {
    const params = new URLSearchParams({ purpose });
    const area = $("#f-area").value.trim(), type = $("#f-type").value, beds = $("#f-beds").value, price = $("#f-price").value;
    if (area) params.set("area", area);
    if (type) params.set("property_type", type);
    if (beds) params.set("min_beds", beds);
    if (price) params.set("max_price_pkr", price);
    const grid = $("#grid");
    grid.innerHTML = '<div class="empty">Loading…</div>';
    try {
      const res = await fetch(`${API}/listings?${params}`);
      if (!res.ok) throw new Error(res.status);
      const data = await res.json();
      $("#result-note").textContent = data.exact
        ? `${data.listings.length} ${data.listings.length === 1 ? "property" : "properties"} match`
        : "No exact match — here are the closest options";
      grid.innerHTML = data.listings.length ? data.listings.map(card).join("") : '<div class="empty">No listings yet.</div>';
    } catch {
      $("#result-note").textContent = "";
      grid.innerHTML = `<div class="error-box">Can't reach the agent API at <b>${esc(API)}</b>. Start the backend or set the URL in <code>config.js</code>.</div>`;
    }
  }

  function card(l) {
    const rent = l.purpose === "rent";
    const beds = l.beds ? `<span>🛏 ${l.beds} bed</span><span>🛁 ${l.baths} bath</span>` : "";
    return `<article class="card">
      <div class="thumb" style="--h:${(l.id * 47) % 360}">${ICONS[l.property_type] || ICONS.house}
        <span class="badge ${rent ? "rent" : ""}">${rent ? "For rent" : "For sale"}</span><span class="tag">${esc(l.property_type)}</span></div>
      <div class="card-body">
        <div class="price">${pkr(l.price_pkr)}${rent ? "<small> / month</small>" : ""}</div>
        <h3>${esc(l.title)}</h3>
        <div class="meta">${beds}<span>📐 ${l.size_marla} marla</span></div>
        <p class="loc">📍 ${esc(l.area)}${l.sector ? ", " + esc(l.sector) : ""}</p>
        <button class="btn btn-soft" type="button" data-ask="${l.id}" data-title="${esc(l.title)}" data-area="${esc(l.area)}">Ask about this</button>
      </div></article>`;
  }

  // ── chat ──
  const TOOL_LABELS = {
    search_listings: "Searched listings", get_listing: "Opened listing", check_slots: "Checked visit slots",
    calculate_installment: "Calculated installment", save_lead_profile: "Saved your preferences",
    request_visit: "Held a visit slot", confirm_visit: "Booked your visit", my_visits: "Looked up your visits",
    schedule_followup: "Queued a follow-up",
  };
  const transcriptKey = () => `pc_transcript_${threadId}`;
  let transcript = [];

  function md(text) {
    // tiny, safe markdown: escape first, then bold, lists and paragraphs
    const lines = esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split(/\n/);
    let html = "", list = null;
    for (const line of lines) {
      const m = line.match(/^\s*(?:[-•*]|\d+[.)])\s+(.*)/);
      if (m) { if (!list) { html += "<ul>"; list = true; } html += `<li>${m[1]}</li>`; continue; }
      if (list) { html += "</ul>"; list = null; }
      if (line.trim()) html += `<p>${line}</p>`;
    }
    return list ? html + "</ul>" : html;
  }

  function addBubble(role, text, tools = [], save = true) {
    const body = $("#chat-body");
    const b = document.createElement("div");
    b.className = `bubble ${role}-msg`;
    if (role === "agent") b.innerHTML = md(text); else b.textContent = text;
    body.appendChild(b);
    if (tools.length) {
      const t = document.createElement("div");
      t.className = "tools";
      t.innerHTML = tools.map((n) => `<span class="tool-chip">${esc(TOOL_LABELS[n] || n)}</span>`).join("");
      body.appendChild(t);
    }
    body.scrollTop = body.scrollHeight;
    if (save && role !== "error") {
      transcript.push({ role, text, tools });
      store.set(transcriptKey(), JSON.stringify(transcript.slice(-60)), sessionStorage);
    }
  }

  function restoreTranscript() {
    $("#chat-body").innerHTML = "";
    try { transcript = JSON.parse(store.get(transcriptKey(), sessionStorage) || "[]"); } catch { transcript = []; }
    if (!transcript.length) {
      addBubble("agent", "Hi! I'm PropCloser 👋 Looking to **buy** or **rent** in Islamabad? Tell me the area, budget and what kind of place you want.", [], false);
    }
    transcript.forEach((m) => addBubble(m.role, m.text, m.tools, false));
  }

  let busy = false;
  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; $("#send").disabled = true;
    addBubble("user", text);
    const typing = document.createElement("div");
    typing.className = "bubble agent-msg typing";
    typing.innerHTML = "<i></i><i></i><i></i>";
    $("#chat-body").appendChild(typing);
    $("#chat-body").scrollTop = $("#chat-body").scrollHeight;
    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, thread_id: threadId, message: text }),
      });
      const data = await res.json();
      typing.remove();
      addBubble("agent", data.reply || "Sorry, I didn't catch that.", (data.tool_calls || []).map((c) => c.name));
    } catch {
      typing.remove();
      addBubble("error", "I couldn't reach the agent. Please check your connection and try again.");
    } finally {
      busy = false; $("#send").disabled = false; $("#chat-text").focus();
    }
  }

  function openChat(prefill) {
    $("#chat").classList.add("open");
    $("#chat").setAttribute("aria-hidden", "false");
    if (prefill) send(prefill); else $("#chat-text").focus();
  }

  // ── wire up ──
  document.querySelectorAll("[data-open-chat]").forEach((b) => b.addEventListener("click", () => openChat()));
  $("#close-chat").addEventListener("click", () => { $("#chat").classList.remove("open"); $("#chat").setAttribute("aria-hidden", "true"); });
  $("#new-chat").addEventListener("click", () => {
    threadId = newId("chat"); store.set("pc_thread_id", threadId); transcript = []; restoreTranscript();
  });
  $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); const t = $("#chat-text").value; $("#chat-text").value = ""; send(t); });
  $("#chips").addEventListener("click", (e) => { if (e.target.matches("button")) send(e.target.textContent); });
  $("#grid").addEventListener("click", (e) => {
    const b = e.target.closest("[data-ask]");
    if (b) openChat(`I'm interested in listing #${b.dataset.ask} (${b.dataset.title}, ${b.dataset.area}). Is it available, and when can I visit?`);
  });
  document.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".segmented button").forEach((x) => x.classList.toggle("active", x === b));
    purpose = b.dataset.purpose; fillPrices(); loadListings();
  }));
  $("#filters").addEventListener("submit", (e) => { e.preventDefault(); loadListings(); });

  fillPrices();
  restoreTranscript();
  loadListings();
})();
