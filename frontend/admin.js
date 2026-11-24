// PropCloser agency desk: approvals first (human-in-the-loop for sending), then leads, visits and costs.
(() => {
  const store = {
    get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* ignore */ } },
    del(k) { try { sessionStorage.removeItem(k); } catch { /* ignore */ } },
  };
  let override = null;
  try { override = localStorage.getItem("pc_api"); localStorage.removeItem("pc_admin_token"); } catch { /* ignore */ }
  const API = (override || window.PROPCLOSER_API || "http://127.0.0.1:8000").replace(/\/$/, "");
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pkr = (n) => (n >= 1e7 ? `${+(n / 1e7).toFixed(2)} crore` : n >= 1e5 ? `${+(n / 1e5).toFixed(2)} lakh` : Number(n).toLocaleString("en"));
  const when = (iso) => new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Karachi", weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
  const ago = (iso) => { const m = Math.max(0, (Date.now() - new Date(iso)) / 6e4); return m < 1 ? "just now" : m < 60 ? `${Math.floor(m)} min ago` : m < 1440 ? `${Math.floor(m / 60)} h ago` : `${Math.floor(m / 1440)} d ago`; };
  const STATUS = { pending: "Held, not confirmed", confirmed: "Confirmed", cancelled: "Cancelled", pending_approval: "Waiting", approved: "Approved", rejected: "Rejected" };
  let token = store.get("pc_admin_token") || "", timer = null, names = {};

  const who = (id) => names[id] || `Lead ${String(id).replace(/^web-/, "").slice(0, 6)}`;

  async function api(path, body) {
    const res = await fetch(API + path, { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json", "X-Admin-Token": token }, body: body ? JSON.stringify(body) : undefined });
    if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
    return res.json();
  }

  function gate(message = "") {
    clearInterval(timer);
    token = ""; store.del("pc_admin_token");
    $("#gate").hidden = false; $("#board").hidden = true; $("#logout").hidden = true;
    $("#gate-error").textContent = message; $("#token").value = ""; $("#token").focus();
  }

  function lead(l) {
    const facts = [l.purpose && (l.purpose === "rent" ? "Rent" : "Buy"), l.area, l.property_type, l.beds && `${l.beds} bed`, l.budget_pkr && `PKR ${pkr(l.budget_pkr)}`, l.timeline, l.financing].filter(Boolean);
    return `<div class="item"><b>${esc(who(l.user_id))}</b><p>${facts.map(esc).join(" · ") || "Nothing known yet"}</p><p class="fine">Active ${ago(l.updated_at)}</p></div>`;
  }

  function draft(f) {
    const open = f.status === "pending_approval";
    return `<div class="item ${open ? "waiting" : ""}"><b>To ${esc(who(f.user_id))}</b><p>${esc(f.message)}</p><div class="act">${open
      ? `<button class="btn btn-primary" type="button" data-id="${f.id}" data-status="approved">Approve</button><button class="btn btn-quiet" type="button" data-id="${f.id}" data-status="rejected">Reject</button>`
      : `<span class="tag ${esc(f.status)}">${STATUS[f.status] || esc(f.status)}</span>`}</div></div>`;
  }

  async function refresh() {
    try {
      const [leads, visits, followups, usage] = await Promise.all([api("/admin/leads"), api("/admin/visits"), api("/admin/followups"), api("/admin/usage")]);
      names = Object.fromEntries(leads.filter((l) => l.name).map((l) => [l.user_id, l.name]));
      $("#gate").hidden = true; $("#board").hidden = false; $("#logout").hidden = false;
      const open = followups.filter((f) => f.status === "pending_approval"), done = followups.filter((f) => f.status !== "pending_approval").slice(0, 3);
      $("#todo-title").textContent = open.length ? `Waiting for you: ${open.length}` : "Nothing waiting for you";
      $("#followups").innerHTML = [...open, ...done].map(draft).join("");
      for (const s of ["new", "qualified", "visit_booked"]) {
        const items = leads.filter((l) => l.status === s);
        $(`#c-${s}`).textContent = items.length;
        $(`#k-${s}`).innerHTML = items.map(lead).join("") || '<p class="empty">None yet</p>';
      }
      $("#visits").innerHTML = visits.map((v) => `<tr><td>${when(v.slot_time)}</td><td>#${v.listing_id} ${esc(v.title)}<br><span class="fine">${esc(v.area)}</span></td><td>${esc(who(v.user_id))}</td><td><span class="tag ${esc(v.status)}">${STATUS[v.status] || esc(v.status)}</span></td></tr>`).join("") || '<tr><td colspan="4" class="empty">No visits yet</td></tr>';
      const stat = (k, v) => `<div><span class="v">${v}</span><span class="k">${k}</span></div>`;
      $("#usage").innerHTML = stat("spent of $" + usage.total_cap_usd.toFixed(2) + " cap", "$" + usage.total_usd.toFixed(4)) + stat("model calls", usage.model_calls) + stat("input read from cache", usage.cache_hit_rate == null ? "–" : Math.round(usage.cache_hit_rate * 100) + "%") + (usage.model_allowed ? "" : stat("assistant", "Paused by cap"));
      $("#updated").textContent = `Updated ${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
    } catch (e) {
      if (e.status === 401) gate("That password isn't right. Try again.");
      else if (e.status === 503) gate("The server has no agency password yet. Set ADMIN_TOKEN (12 or more characters) and restart it.");
      else { console.error("PropCloser API", API, e); if ($("#board").hidden) gate("The server can't be reached. Check your connection, then try again."); else $("#updated").textContent = "Can't update right now. Retrying."; }
    }
  }

  function start() { clearInterval(timer); refresh(); timer = setInterval(() => { if (!document.hidden && !$("#followups").contains(document.activeElement)) refresh(); }, 10000); }

  $("#gate-form").addEventListener("submit", (e) => { e.preventDefault(); token = $("#token").value.trim(); store.set("pc_admin_token", token); start(); });
  $("#logout").addEventListener("click", () => gate());
  $("#sweep").addEventListener("click", async () => {
    $("#sweep").disabled = true; $("#sweep-note").textContent = "Looking for quiet leads";
    try {
      const { drafted } = await api("/admin/sweep", {});
      $("#sweep-note").textContent = drafted.length ? `Drafted ${drafted.length} follow-${drafted.length === 1 ? "up" : "ups"} for you to approve.` : "No leads have been quiet for a day or more.";
      await refresh();
    } catch { $("#sweep-note").textContent = "Couldn't look for quiet leads. Try again."; }
    $("#sweep").disabled = false;
  });
  $("#followups").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-id]");
    if (!b) return;
    b.disabled = true;
    try { await api(`/admin/followups/${b.dataset.id}`, { status: b.dataset.status }); $("#sweep-note").textContent = b.dataset.status === "approved" ? "Approved." : "Rejected."; $("#todo-title").focus?.(); await refresh(); }
    catch { b.disabled = false; $("#sweep-note").textContent = "That didn't save. Try again."; }
  });
  token ? start() : gate();
})();
