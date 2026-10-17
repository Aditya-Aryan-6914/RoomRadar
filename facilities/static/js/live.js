// Free-only toggle + silent auto-refresh of the live area every 30 seconds.
(function () {
  const btn = document.getElementById("freeOnly");
  if (btn) {
    if (localStorage.getItem("freeOnly") === "1") { document.body.classList.add("only-free"); btn.classList.add("active"); }
    btn.addEventListener("click", () => {
      const on = document.body.classList.toggle("only-free");
      localStorage.setItem("freeOnly", on ? "1" : "0");
      btn.textContent = on ? "Showing free rooms only" : "Show free rooms only";
    });
    if (document.body.classList.contains("only-free")) btn.textContent = "Showing free rooms only";
  }
  const live = document.getElementById("live");
  if (!live || live.dataset.today !== "1") return;
  setInterval(async () => {
    try {
      const r = await fetch(location.href, { headers: { "X-Requested-With": "fetch" } });
      const doc = new DOMParser().parseFromString(await r.text(), "text/html");
      const fresh = doc.getElementById("live");
      if (fresh) live.innerHTML = fresh.innerHTML;
    } catch (e) { /* offline: keep old data */ }
  }, 30000);
})();
