// What this browser remembers for the visitor: their search, upcoming visits and saved homes.
// It is learned from what the assistant reports doing, stays on this device, and is wiped by "Delete my data".
window.Me = (() => {
  const read = (k, fallback) => { try { return JSON.parse(localStorage.getItem(k)) ?? fallback; } catch { return fallback; } };
  const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage blocked: still works for this visit */ } };
  let lead = read("pc_lead", {}), visits = read("pc_visits", []), saved = read("pc_saved", []);

  // Amounts the way people say them. Mirrors backend/app/money.py; anything unclear is null rather than a guess.
  const UNIT = { crore: 1e7, crores: 1e7, cr: 1e7, karor: 1e7, karore: 1e7, lakh: 1e5, lakhs: 1e5, lac: 1e5, lacs: 1e5, laakh: 1e5, k: 1e3, thousand: 1e3, hazar: 1e3, hazaar: 1e3, million: 1e6, mn: 1e6, arab: 1e9, billion: 1e9 };
  const NUM = { ek: 1, one: 1, do: 2, two: 2, teen: 3, three: 3, char: 4, chaar: 4, four: 4, paanch: 5, panch: 5, five: 5, chay: 6, chhe: 6, six: 6, saat: 7, seven: 7, aath: 8, eight: 8, nau: 9, nine: 9, das: 10, ten: 10, dedh: 1.5, derh: 1.5, dhai: 2.5, dhaai: 2.5, adhai: 2.5, aadha: 0.5, adha: 0.5, half: 0.5 };
  const SHIFT = { paune: -0.25, pone: -0.25, sawa: 0.25, sarhe: 0.5, saarhe: 0.5, sadhe: 0.5 };
  const FILLER = new Set("pkr rs rupees rupay about around approx roughly nearly tak qareeb lagbhag up to upto under below within less than max maximum budget price rent monthly aur and a the my is of for month mahina per only hai mein se kam".split(" "));
  function rupees(value) {
    if (typeof value === "number") return value >= 1000 ? Math.round(value) : null;
    const text = String(value ?? "").toLowerCase().replace(/(\d),(?=\d)/g, "$1");
    if (/\d\s*-\s*\d/.test(text)) return null;
    let total = 0, qty = null, shift = null, unit = false;
    for (const t of text.match(/\d+(?:\.\d+)?|[a-z]+/g) || []) {
      if (UNIT[t]) { total += ((qty ?? 1) + (shift ?? 0)) * UNIT[t]; qty = shift = null; unit = true; }
      else if (t in SHIFT && qty === null && shift === null) shift = SHIFT[t];
      else if (/^\d/.test(t) || t in NUM) { if (qty !== null) return null; qty = /^\d/.test(t) ? +t : NUM[t]; }
      else if (!FILLER.has(t)) return null;
    }
    if (qty !== null) { if (unit || shift !== null || qty < 1000) return null; total = qty; }
    return total >= 1000 ? Math.round(total) : null;
  }

  const money = (n) => (n >= 1e7 ? `${+(n / 1e7).toFixed(2)} crore` : n >= 1e5 ? `${+(n / 1e5).toFixed(2)} lakh` : Number(n).toLocaleString("en"));

  // "Sat 28 Nov, 5:00 PM" (Pakistan time) to a timestamp. Visits are only ever days ahead, so the nearest year is right.
  function slotTime(label) {
    const m = label.match(/(\d{1,2}) (\w{3}), (\d{1,2}):(\d{2}) ([AP]M)/);
    if (!m) return null;
    const month = "JanFebMarAprMayJunJulAugSepOctNovDec".indexOf(m[2]) / 3;
    if (month < 0) return null;
    const hour = (+m[3] % 12) + (m[5] === "PM" ? 12 : 0), year = new Date().getFullYear();
    const stamp = (y) => Date.UTC(y, month, +m[1], hour - 5, +m[4]);
    return [year - 1, year, year + 1].map(stamp).sort((a, b) => Math.abs(a - Date.now()) - Math.abs(b - Date.now()))[0];
  }

  const forgot = (reply) => /I've deleted what I had saved about you|saved maloomat aur chat history delete/.test(reply);

  // Learn from one answer of the assistant: the tools it used and its fixed confirmation sentences.
  function learn(reply, calls) {
    for (const { name, args = {} } of calls) {
      if (name !== "save_lead_profile") continue;
      for (const k of ["name", "area", "purpose", "property_type"]) if (args[k]) lead[k] = String(args[k]).slice(0, 60);
      if (+args.beds > 0) lead.beds = +args.beds;
      const budget = rupees(args.budget_pkr);
      if (budget) lead.budget = budget;
    }
    if (forgot(reply)) { lead = {}; saved = []; write("pc_saved", saved); }
    write("pc_lead", lead);

    const about = reply.match(/#(\d+) (.+?) \(([^)]+)\)(?: on (\w{3} \d{1,2} \w{3}, \d{1,2}:\d{2} [AP]M))?/);
    if (about) {
      const [, id, title, area, when] = about, others = visits.filter((v) => v.id !== +id);
      if (/visit to #.+ is cancelled|ka visit cancel ho gaya/.test(reply)) visits = others;
      else if (when && /I've booked your visit|ka visit book ho gaya|visit has been moved to|ka visit ab #/.test(reply)) visits = [...others, { id: +id, title, area, when, ts: slotTime(when) }];
      write("pc_visits", visits);
    }
  }

  const upcoming = () => visits.filter((v) => v.ts && v.ts > Date.now()).sort((a, b) => a.ts - b.ts);
  const knowsSearch = () => ["area", "beds", "budget", "property_type"].some((k) => lead[k]);

  function describe() {
    const kind = { house: "house", flat: "flat", plot: "plot" }[lead.property_type] || "home";
    const beds = lead.beds && kind !== "plot" ? `${lead.beds} bed ` : "";
    return `${beds}${kind}${lead.purpose === "rent" ? " to rent" : ""}${lead.area ? ` in ${lead.area}` : ""}${lead.budget ? `, up to ${money(lead.budget)}${lead.purpose === "rent" ? " a month" : ""}` : ""}`.replace(/^./, (c) => c.toUpperCase());
  }
  function facts() {
    return [lead.name, lead.purpose && (lead.purpose === "rent" ? "Renting" : "Buying"), lead.area, lead.property_type && lead.property_type.replace(/^./, (c) => c.toUpperCase()),
      lead.beds && `${lead.beds} bed`, lead.budget && `Up to ${money(lead.budget)}`].filter(Boolean);
  }
  // A home fits when at least two known wishes are met and none is broken.
  function fits(l) {
    const tests = [lead.area && l.area.toLowerCase().includes(lead.area.toLowerCase()), lead.beds && l.beds >= lead.beds, lead.budget && l.price_pkr <= lead.budget, lead.property_type && l.property_type === lead.property_type].filter((t) => t !== undefined && t !== "" && t !== 0);
    return l.purpose === (lead.purpose || "sale") && tests.length >= 2 && tests.every(Boolean);
  }

  const isSaved = (id) => saved.includes(id);
  function toggleSaved(id) { saved = isSaved(id) ? saved.filter((x) => x !== id) : [...saved, id]; write("pc_saved", saved); return isSaved(id); }

  return { learn, forgot, upcoming, knowsSearch, describe, facts, fits, isSaved, toggleSaved, rupees, slotTime, get lead() { return lead; }, get saved() { return saved; } };
})();
