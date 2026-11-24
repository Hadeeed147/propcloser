// Dastak agency desk. Five views, one at a time: today, approvals (a person decides what is sent), leads, visits, costs.
(() => {
  const store = {
    get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* ignore */ } },
    del(k) { try { sessionStorage.removeItem(k); } catch { /* ignore */ } },
  };
  let override = null;
  try { override = localStorage.getItem("pc_api"); localStorage.removeItem("pc_admin_token"); } catch { /* ignore */ }
  const API = (override || window.DASTAK_API || "http://127.0.0.1:8000").replace(/\/$/, "");
  const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name) => `<svg class="i" aria-hidden="true"><use href="icons.svg#${name}"/></svg>`;
  const pkr = (n) => (n >= 1e7 ? `${+(n / 1e7).toFixed(2)} crore` : n >= 1e5 ? `${+(n / 1e5).toFixed(2)} lakh` : Number(n).toLocaleString("en"));
  const usd = (n) => `$${n > 0 && n < 0.1 ? n.toFixed(4) : Number(n).toFixed(2)}`;
  const local = (d, o) => new Date(d).toLocaleString("en-GB", { timeZone: "Asia/Karachi", ...o });
  const time = (d) => local(d, { hour: "numeric", minute: "2-digit", hour12: true }).toUpperCase();
  const day = (d) => local(d, { weekday: "long", day: "numeric", month: "long" });
  const dayKey = (d) => new Date(d).toLocaleDateString("en-CA", { timeZone: "Asia/Karachi" });
  const ago = (iso) => { const m = Math.max(0, (Date.now() - new Date(iso)) / 6e4); return m < 1 ? "Just now" : m < 60 ? `${Math.floor(m)} min ago` : m < 1440 ? `${Math.floor(m / 60)} h ago` : `${Math.floor(m / 1440)} d ago`; };
  const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

  const STAGE = { new: "New", qualified: "Qualified", visit_booked: "Visit booked" };
  const TAG = {
    new: ["", "message", "New"], qualified: ["", "check", "Qualified"], visit_booked: ["good", "calendar", "Visit booked"],
    pending: ["wait", "clock", "Held, not confirmed"], confirmed: ["good", "done", "Confirmed"], cancelled: ["off", "ban", "Cancelled"],
    pending_approval: ["wait", "clock", "Waiting"], approved: ["good", "done", "Approved"], rejected: ["off", "ban", "Rejected"],
  };
  const tag = (s) => { const [cls, i, label] = TAG[s] || ["off", "info", s]; return `<span class="tag ${cls}">${icon(i)}${esc(label)}</span>`; };
  const empty = (i, text) => `<div class="empty">${icon(i)}<p>${text}</p></div>`;

  let token = store.get("pc_admin_token") || "", timer = null, loaded = false;
  let data = { leads: [], visits: [], followups: [], usage: null }, names = {};
  let leadFilter = "all", visitFilter = "upcoming", query = "", view = "today", chosen = "";

  const who = (id) => names[id] || `Lead ${String(id).replace(/^web-/, "").slice(0, 6)}`;
  const avatar = (id) => { const n = names[id]; return `<span class="avatar" aria-hidden="true">${n ? esc(n.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()) : icon("user")}</span>`; };
  const wants = (l) => [l.beds && `${l.beds} bed`, l.property_type || (l.area || l.budget_pkr ? "home" : ""), l.area && `in ${l.area}`, l.purpose === "rent" && "to rent"].filter(Boolean).join(" ").replace(/^./, (c) => c.toUpperCase()) || "Nothing known yet";

  async function api(path, body) {
    const res = await fetch(API + path, { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json", "X-Admin-Token": token }, body: body ? JSON.stringify(body) : undefined });
    if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
    return res.json();
  }

  // Replace a region only when it changed, and never under someone's keyboard focus.
  const painted = new WeakMap();
  function paint(sel, html, force = false) {
    const n = $(sel);
    if (painted.get(n) === html || (!force && n.contains(document.activeElement))) return;
    n.innerHTML = html;
    painted.set(n, html);
  }
  let toastTimer;
  function toast(text) { $("#toast").textContent = text; $("#toast").classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => $("#toast").classList.remove("show"), 4500); }

  function gate(message = "") {
    clearInterval(timer);
    token = ""; loaded = false; store.del("pc_admin_token");
    $("#gate").hidden = false; $("#desk").hidden = true;
    $("#gate-error").textContent = message; $("#token").value = ""; $("#token").focus();
  }

  // ── pieces ──
  function draft(f) {
    const open = f.status === "pending_approval";
    return `<article class="draft" data-draft="${f.id}"><div class="draft-head">${avatar(f.user_id)}<div><b>To ${esc(who(f.user_id))}</b><p>${f.due_at ? `Suggested for ${local(f.due_at, { weekday: "short", day: "numeric", month: "short" })}` : `Drafted ${ago(f.created_at).toLowerCase()}`}</p></div></div>
      <blockquote>${esc(f.message)}</blockquote>
      <div class="row">${open ? `<button class="btn btn-primary" type="button" data-id="${f.id}" data-status="approved">Approve</button><button class="btn btn-quiet" type="button" data-id="${f.id}" data-status="rejected">Reject</button>` : tag(f.status)}</div></article>`;
  }
  const visitRow = (v) => `<div class="visit"><time datetime="${esc(v.slot_time)}">${time(v.slot_time)}</time>${Photos.thumb({ id: v.listing_id, property_type: "house" })}<div><b>${esc(v.title)}</b><p>${esc(v.area)}, with ${esc(who(v.user_id))}</p></div>${tag(v.status)}</div>`;
  const shortVisit = (v) => `<div class="row-item">${Photos.thumb({ id: v.listing_id, property_type: "house" })}<div><b>${local(v.slot_time, { weekday: "short", day: "numeric", month: "short" })}, ${time(v.slot_time)}</b><p>${esc(v.title)}, ${esc(v.area)}, with ${esc(who(v.user_id))}</p></div>${tag(v.status)}</div>`;
  const kpi = ({ href, i, label, value, note, due }) => `<${href ? `a href="${href}"` : "div"} class="kpi ${due ? "due" : ""}"><span class="kpi-label">${icon(i)}${label}</span><b>${value}</b><small>${note}</small></${href ? "a" : "div"}>`;
  function meter(label, used, cap) {
    const share = cap > 0 ? Math.min(used / cap, 1) : 0;
    return `<div class="meter"><p><span>${label}</span><span>${usd(used)} of ${usd(cap)}</span></p><div class="track" role="meter" aria-label="${label}" aria-valuemin="0" aria-valuemax="${cap}" aria-valuenow="${used}"><i class="${share >= .9 ? "stop" : share >= .7 ? "warn" : ""}" style="width:${used > 0 ? Math.max(share * 100, 1) : 0}%"></i></div></div>`;
  }

  // ── views ──
  const waiting = () => data.followups.filter((f) => f.status === "pending_approval");
  const ahead = () => data.visits.filter((v) => v.status !== "cancelled" && new Date(v.slot_time) > Date.now()).sort((a, b) => new Date(a.slot_time) - new Date(b.slot_time));

  const VIEWS = {
    today: { title: "Today", note: () => local(Date.now(), { weekday: "long", day: "numeric", month: "long" }), draw(force) {
      const open = waiting(), next = ahead(), week = next.filter((v) => new Date(v.slot_time) - Date.now() < 7 * 864e5), u = data.usage, fresh = data.leads.filter((l) => Date.now() - new Date(l.created_at) < 864e5).length;
      paint("#kpis", [
        kpi({ href: "#approvals", i: "inbox", label: "Waiting for you", value: open.length, note: open.length ? "drafts to approve" : "nothing to approve", due: open.length > 0 }),
        kpi({ href: "#leads", i: "users", label: "Leads", value: data.leads.length, note: `${fresh} in the last day` }),
        kpi({ href: "#visits", i: "calendar", label: "Visits, 7 days", value: week.length, note: next[0] ? `next ${local(next[0].slot_time, { weekday: "short" })}, ${time(next[0].slot_time)}` : "none booked" }),
        kpi({ href: "#costs", i: "wallet", label: "AI spend", value: usd(u.total_usd), note: u.model_allowed ? `of a ${usd(u.total_cap_usd)} cap` : "paused by the cap", due: !u.model_allowed }),
      ].join(""), force);
      paint("#today-approvals", open.length ? `<div class="rows">${open.slice(0, 2).map(draft).join("")}</div>` : empty("inbox", "No drafts waiting. New ones appear here."), force);
      paint("#today-visits", next.length ? `<div class="rows">${next.slice(0, 4).map(shortVisit).join("")}</div>` : empty("calendar", "No visits coming up. Confirmed visits appear here."), force);
      const top = Math.max(1, ...Object.keys(STAGE).map((s) => data.leads.filter((l) => l.status === s).length));
      paint("#pipeline", Object.entries(STAGE).map(([s, label]) => { const n = data.leads.filter((l) => l.status === s).length; return `<a class="pipe" href="#leads" data-stage="${s}"><span>${label}</span><span class="track"><i style="width:${(n / top) * 100}%"></i></span><b>${n}</b></a>`; }).join(""), force);
    } },
    approvals: { title: "Approvals", note: () => { const n = waiting().length; return n ? `${plural(n, "draft")} waiting for you` : "Nothing is waiting for you"; }, draw(force) {
      const open = waiting(), done = data.followups.filter((f) => f.status !== "pending_approval");
      paint("#drafts", open.map(draft).join("") || `<div class="box">${empty("inbox", "All clear. Use Find quiet leads to check for anyone who stopped replying.")}</div>`, force);
      $("#handled-box").hidden = !done.length;
      $("#handled-title").textContent = `Already handled (${done.length})`;
      paint("#handled", `<div class="rows">${done.slice(0, 30).map((f) => `<div class="row-item">${avatar(f.user_id)}<div><b>To ${esc(who(f.user_id))}</b><p>${esc(f.message)}</p></div>${tag(f.status)}</div>`).join("")}</div>`, force);
    } },
    leads: { title: "Leads", note: () => `${plural(data.leads.length, "person", "people")} in the pipeline`, draw(force) {
      const count = (s) => (s === "all" ? data.leads.length : data.leads.filter((l) => l.status === s).length);
      paint("#lead-filter", [["all", "All"], ...Object.entries(STAGE)].map(([s, label]) => `<button type="button" data-filter="${s}" aria-pressed="${s === leadFilter}">${label}<small>${count(s)}</small></button>`).join(""), force);
      const q = query.trim().toLowerCase();
      const list = data.leads.filter((l) => (leadFilter === "all" || l.status === leadFilter) && (!q || [who(l.user_id), l.area, l.property_type, l.purpose === "rent" ? "rent" : "buy"].join(" ").toLowerCase().includes(q)))
        .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
      const wide = matchMedia("(min-width: 901px)").matches;
      const current = list.find((l) => l.user_id === chosen) || (wide ? list[0] : null);
      paint("#lead-list", list.map((l) => `<button type="button" class="lead" data-lead="${esc(l.user_id)}" ${current && l.user_id === current.user_id ? 'aria-current="true"' : ""}>${avatar(l.user_id)}<span style="min-width:0"><b>${esc(who(l.user_id))}</b><span class="line">${esc(wants(l))}${l.budget_pkr ? `, PKR ${pkr(l.budget_pkr)}` : ""}</span></span><span class="end">${tag(l.status)}<span>${ago(l.updated_at)}</span></span></button>`).join("")
        || empty("users", data.leads.length ? "No lead matches. Try another name or status." : "No leads yet. They appear when someone chats with the assistant."), force);
      $(".split").classList.toggle("open", Boolean(chosen && current) && !wide);
      paint("#lead-detail", current ? detail(current) : empty("user", "Choose a lead to see what they want."), force);
    } },
    visits: { title: "Visits", note: () => `${plural(ahead().length, "visit")} coming up`, draw(force) {
      const now = Date.now(), sets = { upcoming: ahead(), past: data.visits.filter((v) => v.status !== "cancelled" && new Date(v.slot_time) <= now).sort((a, b) => new Date(b.slot_time) - new Date(a.slot_time)), cancelled: data.visits.filter((v) => v.status === "cancelled").sort((a, b) => new Date(b.slot_time) - new Date(a.slot_time)) };
      paint("#visit-filter", [["upcoming", "Coming up"], ["past", "Past"], ["cancelled", "Cancelled"]].map(([s, label]) => `<button type="button" data-filter="${s}" aria-pressed="${s === visitFilter}">${label}<small>${sets[s].length}</small></button>`).join(""), force);
      const days = new Map();
      sets[visitFilter].forEach((v) => { const k = dayKey(v.slot_time); days.set(k, [...(days.get(k) || []), v]); });
      const today = dayKey(now), tomorrow = dayKey(now + 864e5);
      paint("#agenda", [...days].map(([k, list]) => `<section class="box day"><h2>${k === today ? "Today" : k === tomorrow ? "Tomorrow" : day(list[0].slot_time)}${k === today || k === tomorrow ? ` <span>${day(list[0].slot_time)}</span>` : ""}</h2>${list.map(visitRow).join("")}</section>`).join("")
        || `<div class="box">${empty("calendar", { upcoming: "No visits coming up. A lead books one by saying yes in the chat.", past: "No past visits yet.", cancelled: "No cancelled visits." }[visitFilter])}</div>`, force);
    } },
    costs: { title: "Costs", note: () => (data.usage.model_allowed ? "The assistant pauses by itself at the cap" : "The assistant is paused by the cap"), draw(force) {
      const u = data.usage;
      paint("#spend", `<p class="hero-figure">${usd(u.total_usd)} <small>spent of ${usd(u.total_cap_usd)}</small></p>${meter("Total", u.total_usd, u.total_cap_usd)}${meter("Last hour", u.last_hour_usd, u.hourly_cap_usd)}`, force);
      paint("#cost-tiles", [
        kpi({ i: "message", label: "Model calls", value: u.model_calls.toLocaleString("en"), note: "since the meter started" }),
        kpi({ i: "wallet", label: "Average per call", value: u.model_calls ? `$${(u.total_usd / u.model_calls).toFixed(5)}` : "None yet", note: "all tokens included" }),
        kpi({ i: "zap", label: "Read from cache", value: u.cache_hit_rate == null ? "None yet" : `${Math.round(u.cache_hit_rate * 100)}%`, note: "of input, at a lower price" }),
      ].join(""), force);
      const rows = Object.entries(u.tokens || {});
      paint("#tokens", rows.length ? `<table><tbody>${rows.map(([k, v]) => `<tr><th scope="row">${esc(k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()))}</th><td>${Number(v).toLocaleString("en")}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">No tokens used yet.</p>', force);
    } },
  };

  function detail(l) {
    const facts = [["Looking to", l.purpose && (l.purpose === "rent" ? "Rent" : "Buy")], ["Area", l.area], ["Type", l.property_type && l.property_type.replace(/^./, (c) => c.toUpperCase())], ["Bedrooms", l.beds], ["Budget", l.budget_pkr && `PKR ${pkr(l.budget_pkr)}`], ["Timeline", l.timeline], ["Financing", l.financing], ["First seen", ago(l.created_at)], ["Last active", ago(l.updated_at)]].filter(([, v]) => v);
    const visits = data.visits.filter((v) => v.user_id === l.user_id), notes = data.followups.filter((f) => f.user_id === l.user_id);
    return `<button class="btn btn-quiet back" type="button" data-back>All leads</button>
      <div class="detail-head">${avatar(l.user_id)}<div><h2>${esc(who(l.user_id))}</h2>${tag(l.status)}</div></div>
      <dl>${facts.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      ${visits.length ? `<h3>Visits</h3><div class="rows">${visits.map((v) => `<div class="row-item">${Photos.thumb({ id: v.listing_id, property_type: "house" })}<div><b>${local(v.slot_time, { weekday: "short", day: "numeric", month: "short" })}, ${time(v.slot_time)}</b><p>${esc(v.title)}, ${esc(v.area)}</p></div>${tag(v.status)}</div>`).join("")}</div>` : ""}
      ${notes.length ? `<h3>Follow-ups</h3><div class="rows">${notes.map((f) => `<div class="row-item" style="grid-template-columns:minmax(0,1fr) auto"><p>${esc(f.message)}</p>${tag(f.status)}</div>`).join("")}</div>` : ""}`;
  }

  function route(move = false) {
    const [name, id] = location.hash.slice(1).split("/");
    view = VIEWS[name] ? name : "today";
    chosen = view === "leads" && id ? decodeURIComponent(id) : "";
    $$("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== view; });
    $$("[data-view]").forEach((a) => (a.dataset.view === view ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    render(true);
    document.title = `${VIEWS[view].title}, Dastak agency desk`;
    if (move) { scrollTo({ top: 0, behavior: "instant" }); $("#view-title").focus({ preventScroll: true }); }
  }
  function render(force = false) {
    if (!loaded) return;
    $("#view-title").textContent = VIEWS[view].title;
    $("#view-note").textContent = VIEWS[view].note();
    const n = waiting().length;
    $("#badge").hidden = !n; $("#badge").textContent = n; $("#badge").setAttribute("aria-label", `${n} waiting`);
    VIEWS[view].draw(force);
  }

  async function refresh(force = false) {
    try {
      const [leads, visits, followups, usage] = await Promise.all([api("/admin/leads"), api("/admin/visits"), api("/admin/followups"), api("/admin/usage")]);
      data = { leads, visits, followups, usage };
      names = Object.fromEntries(leads.filter((l) => l.name).map((l) => [l.user_id, l.name]));
      const first = !loaded;
      loaded = true;
      $("#gate").hidden = true; $("#desk").hidden = false;
      if (first) route(); else render(force);
      $("#updated").textContent = `Updated ${local(Date.now(), { hour: "numeric", minute: "2-digit", hour12: true }).toUpperCase()}`;
    } catch (e) {
      if (e.status === 401) gate("That password isn't right. Try again.");
      else if (e.status === 503) gate("The server has no agency password yet. Set ADMIN_TOKEN (12 or more characters) and restart it.");
      else { console.error("Dastak API", API, e); if (!loaded) gate("The server can't be reached. Check your connection, then try again."); else $("#updated").textContent = "Can't update right now. Retrying."; }
    }
  }
  function start() { clearInterval(timer); refresh(); timer = setInterval(() => { if (!document.hidden) refresh(); }, 10000); }

  // ── wire up ──
  $("#gate-form").addEventListener("submit", (e) => { e.preventDefault(); token = $("#token").value.trim(); store.set("pc_admin_token", token); start(); });
  ["#logout", "#logout-2"].forEach((id) => $(id).addEventListener("click", () => gate()));
  $("#refresh").addEventListener("click", () => refresh(true));
  addEventListener("hashchange", () => { if (loaded) route(true); });
  matchMedia("(min-width: 901px)").addEventListener?.("change", () => render(true));
  $("#q").addEventListener("input", (e) => { query = e.target.value; render(true); });
  $("#lead-filter").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { leadFilter = b.dataset.filter; render(true); $(`#lead-filter [data-filter="${leadFilter}"]`)?.focus(); } });
  $("#visit-filter").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { visitFilter = b.dataset.filter; render(true); $(`#visit-filter [data-filter="${visitFilter}"]`)?.focus(); } });
  $("#pipeline").addEventListener("click", (e) => { const a = e.target.closest("[data-stage]"); if (a) leadFilter = a.dataset.stage; });
  $("#lead-list").addEventListener("click", (e) => {
    const b = e.target.closest("[data-lead]");
    if (!b) return;
    const id = b.dataset.lead;
    chosen = id;
    history.pushState(null, "", `#leads/${encodeURIComponent(id)}`);
    render(true);
    if (matchMedia("(min-width: 901px)").matches) $$(".lead").find((n) => n.dataset.lead === id)?.focus();
    else { scrollTo({ top: 0, behavior: "instant" }); $(".back")?.focus(); }
  });
  $("#lead-detail").addEventListener("click", (e) => { if (e.target.closest("[data-back]")) { chosen = ""; history.pushState(null, "", "#leads"); render(true); $(".lead")?.focus(); } });
  addEventListener("popstate", () => { if (loaded) route(); });

  $("#sweep").addEventListener("click", async () => {
    $("#sweep").disabled = true; toast("Looking for quiet leads");
    try {
      const { drafted } = await api("/admin/sweep", {});
      toast(drafted.length ? `Drafted ${plural(drafted.length, "follow-up")} for you to approve.` : "No leads have been quiet for a day or more.");
      await refresh(true);
    } catch { toast("Couldn't look for quiet leads. Try again."); }
    $("#sweep").disabled = false;
  });
  $("#main").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-id][data-status]");
    if (!b) return;
    const pair = [...b.parentElement.querySelectorAll("button")];
    pair.forEach((x) => { x.disabled = true; });
    try {
      await api(`/admin/followups/${b.dataset.id}`, { status: b.dataset.status });
      toast(b.dataset.status === "approved" ? "Approved." : "Rejected.");
      await refresh(true);
      $("#view-title").focus({ preventScroll: true });
    } catch { pair.forEach((x) => { x.disabled = false; }); toast("That didn't save. Try again."); }
  });
  document.addEventListener("error", (e) => { if (e.target.tagName === "IMG") e.target.style.visibility = "hidden"; }, true);

  token ? start() : gate();
})();
