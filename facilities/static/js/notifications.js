// In-site notifications: bell + dropdown + pop-up toasts. Polls every 20 s.
(function () {
  const wrap = document.getElementById("notifWrap");
  if (!wrap) return;
  const $ = id => document.getElementById(id);
  const btn = $("bellBtn"), badge = $("bellBadge"), panel = $("notifPanel"), list = $("notifList"), toasts = $("toasts");
  const seenKey = "rr-toast-" + wrap.dataset.key;
  const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";
  const getSeen = () => { try { return +localStorage.getItem(seenKey) || 0; } catch (e) { return 0; } };
  const setSeen = n => { try { localStorage.setItem(seenKey, n); } catch (e) {} };

  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }

  function toast(n) {
    const t = el("div", "toast k-" + n.kind);
    t.style.setProperty("--c", "var(--" + ({ freed: "free", cancelled: "busy", booked: "booked", extra: "changed", reserved: "emer", updated: "changed", removed: "emer", timetable: "brand" }[n.kind] || "brand") + ")");
    const box = el("div"); box.append(el("b", "", n.title), el("span", "", n.body)); t.append(box);
    const close = () => { t.classList.add("out"); setTimeout(() => t.remove(), 260); };
    t.addEventListener("click", () => { close(); panel.hidden = false; });
    toasts.append(t); setTimeout(close, 8000);
  }

  function render(data) {
    badge.hidden = !data.unread;
    badge.textContent = data.unread > 9 ? "9+" : data.unread;
    list.replaceChildren();
    if (!data.items.length) { list.append(el("p", "muted small np-empty", "Nothing yet.")); return; }
    data.items.forEach(n => {
      const row = el("div", "ni k-" + n.kind + (n.read ? "" : " unread"));
      const d = el("div"); d.append(el("b", "", n.title), el("span", "", n.body), el("small", "", n.ago));
      row.append(el("i"), d); list.append(row);
    });
  }

  async function poll() {
    try {
      const r = await fetch(wrap.dataset.url, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" });
      if (!r.ok) return;
      const data = await r.json();
      render(data);
      const seen = getSeen();
      // pop up only unread, recent alerts we have not shown yet (max 3 at a time)
      data.items.filter(n => !n.read && n.id > seen && n.age_s < 600).slice(0, 3).reverse().forEach(toast);
      if (data.items.length) setSeen(Math.max(seen, data.items[0].id));
    } catch (e) { /* offline */ }
  }

  async function markRead() {
    await fetch(wrap.dataset.readUrl, { method: "POST", headers: { "X-CSRFToken": csrf }, credentials: "same-origin" });
    poll();
  }

  btn.addEventListener("click", e => {
    e.stopPropagation();
    panel.hidden = !panel.hidden;
    btn.setAttribute("aria-expanded", !panel.hidden);
  });
  $("markRead").addEventListener("click", markRead);
  document.addEventListener("click", e => { if (!wrap.contains(e.target)) { panel.hidden = true; btn.setAttribute("aria-expanded", false); } });
  document.addEventListener("keydown", e => { if (e.key === "Escape") panel.hidden = true; });
  poll();
  setInterval(poll, 20000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
})();
