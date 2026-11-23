// PropCloser agency dashboard: pipeline, visits and follow-up approvals (human-in-the-loop for sending).
(() => {
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
  };
  const API = (store.get("pc_api") || window.PROPCLOSER_API || "http://127.0.0.1:8000").replace(/\/$/, "");
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pkr = (n) => (n == null ? null : n >= 1e7 ? `${+(n / 1e7).toFixed(2)} crore` : n >= 1e5 ? `${+(n / 1e5).toFixed(2)} lakh` : Number(n).toLocaleString());
  const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "-");
  const ago = (iso) => {
    if (!iso) return "";
    const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
    return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : `${Math.floor(s / 86400)} d ago`;
  };

  let token = store.get("pc_admin_token") || "";
  let lastUpdate = null, timer = null;

  async function api(path, opts = {}) {
    const res = await fetch(`${API}${path}`, { ...opts, headers: { "Content-Type": "application/json", "X-Admin-Token": token, ...(opts.headers || {}) } });
    if (res.status === 401) throw Object.assign(new Error("unauthorized"), { status: 401 });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function showGate(msg = "") {
    $("#gate").hidden = false; $("#board").hidden = true; $("#gate-error").textContent = msg;
    clearInterval(timer);
  }

  function leadCard(l) {
    const kv = [
      l.purpose && (l.purpose === "rent" ? "Rent" : "Buy"),
      l.area, l.property_type, l.beds && `${l.beds} bed`,
      l.budget_pkr && `PKR ${pkr(l.budget_pkr)}`, l.timeline, l.financing,
    ].filter(Boolean);
    return `<div class="lead"><b>${esc(l.name || l.user_id)}</b>
      ${kv.length ? `<div class="row">${kv.map((x) => `<span class="kv">${esc(x)}</span>`).join("")}</div>` : '<small>Not qualified yet</small>'}
      <small>Updated ${ago(l.updated_at)}</small></div>`;
  }

  async function refresh() {
    try {
      const [stats, leads, visits, followups] = await Promise.all([
        api("/admin/stats"), api("/admin/leads"), api("/admin/visits"), api("/admin/followups"),
      ]);
      $("#gate").hidden = true; $("#board").hidden = false;
      $("#s-leads").textContent = stats.leads; $("#s-qualified").textContent = stats.qualified;
      $("#s-visits").textContent = stats.visits_booked; $("#s-followups").textContent = stats.followups_pending;

      for (const status of ["new", "qualified", "visit_booked"]) {
        const items = leads.filter((l) => l.status === status);
        $(`#c-${status}`).textContent = items.length;
        $(`#k-${status}`).innerHTML = items.length ? items.map(leadCard).join("") : '<div class="none">No leads</div>';
      }

      $("#visits").innerHTML = visits.length
        ? visits.map((v) => `<tr><td>#${v.listing_id} ${esc(v.title)}<br><small style="color:var(--muted)">${esc(v.area)}</small></td>
            <td>${when(v.slot_time)}</td><td>${esc(v.user_id)}</td><td><span class="status ${esc(v.status)}">${esc(v.status)}</span></td></tr>`).join("")
        : '<tr><td colspan="4" class="none">No visits yet</td></tr>';

      const pending = followups.filter((f) => f.status === "pending_approval");
      const done = followups.filter((f) => f.status !== "pending_approval").slice(0, 5);
      $("#followups").innerHTML = (pending.length || done.length)
        ? [...pending, ...done].map((f) => `<div class="fu"><p>${esc(f.message)}</p><div class="fu-meta">
            <span>To ${esc(f.user_id)}</span><span>· due ${when(f.due_at)}</span>
            ${f.status === "pending_approval"
              ? `<div class="actions"><button class="btn btn-sm btn-ok" data-fu="${f.id}" data-status="approved">Approve</button>
                 <button class="btn btn-sm btn-no" data-fu="${f.id}" data-status="rejected">Reject</button></div>`
              : `<span class="status ${esc(f.status)}" style="margin-left:auto">${esc(f.status)}</span>`}
          </div></div>`).join("")
        : '<div class="none">Nothing waiting for approval</div>';

      lastUpdate = Date.now(); tick();
    } catch (e) {
      if (e.status === 401) { store.del("pc_admin_token"); showGate(token ? "That token was rejected." : ""); }
      else { $("#updated").textContent = `Can't reach API at ${API}`; }
    }
  }

  function tick() {
    if (lastUpdate) $("#updated").textContent = `Updated ${Math.round((Date.now() - lastUpdate) / 1000)}s ago`;
  }

  $("#gate-form").addEventListener("submit", (e) => {
    e.preventDefault();
    token = $("#token").value.trim(); store.set("pc_admin_token", token); start();
  });
  $("#refresh").addEventListener("click", refresh);
  $("#logout").addEventListener("click", () => { token = ""; store.del("pc_admin_token"); showGate(); });
  $("#followups").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-fu]");
    if (!b) return;
    b.disabled = true;
    try { await api(`/admin/followups/${b.dataset.fu}`, { method: "POST", body: JSON.stringify({ status: b.dataset.status }) }); }
    finally { refresh(); }
  });

  function start() {
    clearInterval(timer);
    refresh();
    timer = setInterval(() => { refresh(); }, 10000);
  }
  setInterval(tick, 1000);
  token ? start() : showGate();
})();
