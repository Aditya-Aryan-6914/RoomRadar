// Dashboard behaviour: view switch (Now / Day timeline), free-only filter, search, 30 s live refresh.
(function () {
  const live = document.getElementById("live");
  if (!live) return;
  const today = live.dataset.today === "1";
  const store = (k, v) => { try { v === undefined ? localStorage.getItem(k) : localStorage.setItem(k, v); } catch (e) {} };
  const get = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  let view = today ? (get("rr-view") || "cards") : "timeline";
  const q = document.getElementById("q");

  function apply() {
    document.body.classList.remove("view-cards", "view-timeline");
    document.body.classList.add("view-" + view);
    document.body.classList.toggle("only-free", get("rr-free") === "1");
    document.querySelectorAll(".seg [data-view]").forEach(b => {
      b.classList.toggle("active", b.dataset.view === view);
      if (!today && b.dataset.view === "cards") b.style.display = "none";
    });
    const f = document.getElementById("freeOnly");
    if (f) f.classList.toggle("active", get("rr-free") === "1");
    const term = (q ? q.value : "").trim().toLowerCase();
    live.querySelectorAll("[data-s]").forEach(el => el.classList.toggle("hide", term && !el.dataset.s.toLowerCase().includes(term)));
  }
  document.addEventListener("click", e => {
    const b = e.target.closest(".seg button");
    if (!b) return;
    if (b.dataset.view) { view = b.dataset.view; store("rr-view", view); }
    else if (b.id === "freeOnly") store("rr-free", get("rr-free") === "1" ? "0" : "1");
    apply();
  });
  if (q) q.addEventListener("input", apply);
  apply();

  if (!today) return;
  setInterval(async () => {
    try {
      const open = {};
      live.querySelectorAll("details.dept").forEach(d => open[d.id] = d.open);
      const r = await fetch(location.href, { headers: { "X-Requested-With": "fetch" } });
      const doc = new DOMParser().parseFromString(await r.text(), "text/html");
      const fresh = doc.getElementById("live");
      if (!fresh) return;
      live.innerHTML = fresh.innerHTML;
      live.querySelectorAll("details.dept").forEach(d => { if (d.id in open) d.open = open[d.id]; });
      const c = doc.getElementById("clock"), mine = document.getElementById("clock");
      if (c && mine) mine.textContent = c.textContent;
      apply();
    } catch (e) { /* offline: keep old data */ }
  }, 30000);
})();
