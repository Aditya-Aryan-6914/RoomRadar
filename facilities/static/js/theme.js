// Light / dark mode toggle. Choice is remembered; defaults to the system setting.
(function () {
  const root = document.documentElement;
  const btn = document.getElementById("themeToggle");
  function set(t) {
    root.setAttribute("data-theme", t);
    try { localStorage.setItem("rr-theme", t); } catch (e) {}
    if (btn) btn.setAttribute("aria-pressed", t === "dark");
  }
  if (btn) {
    btn.setAttribute("aria-pressed", root.getAttribute("data-theme") === "dark");
    btn.addEventListener("click", () => set(root.getAttribute("data-theme") === "dark" ? "light" : "dark"));
  }
})();
