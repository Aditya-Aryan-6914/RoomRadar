// Turns Django messages into pop-ups: errors/warnings -> alert dialog, others -> toast.
(function () {
  const items = Array.from(document.querySelectorAll(".js-flash"));
  if (!items.length) return;
  const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x) e.textContent = x; return e; };

  function alertBox(title, text, kind) {
    const back = el("div", "modal-back");
    const box = el("div", "modal " + kind);
    box.setAttribute("role", "alertdialog"); box.setAttribute("aria-modal", "true");
    const ok = el("button", "btn", "OK");
    box.append(el("div", "modal-ic", kind === "error" ? "!" : "i"), el("h3", "", title), el("p", "", text), ok);
    back.append(box); document.body.append(back);
    const close = () => { back.remove(); document.removeEventListener("keydown", esc); };
    const esc = e => { if (e.key === "Escape") close(); };
    ok.addEventListener("click", close);
    back.addEventListener("click", e => { if (e.target === back) close(); });
    document.addEventListener("keydown", esc);
    ok.focus();
  }

  function toast(text, kind) {
    let box = document.getElementById("toasts");
    if (!box) { box = el("div", "toasts"); box.id = "toasts"; document.body.append(box); }
    const t = el("div", "toast");
    t.style.setProperty("--c", kind === "success" ? "var(--free)" : "var(--booked)");
    const d = el("div"); d.append(el("b", "", kind === "success" ? "Done" : "Notice"), el("span", "", text)); t.append(d);
    const close = () => { t.classList.add("out"); setTimeout(() => t.remove(), 260); };
    t.addEventListener("click", close); box.append(t); setTimeout(close, 6000);
  }

  items.forEach(m => {
    const text = m.textContent.trim();
    const kind = ["error", "warning", "success"].find(k => m.classList.contains(k)) || "info";
    m.hidden = true;
    if (kind === "error") alertBox("Couldn't complete that", text, "error");
    else if (kind === "warning") alertBox("Heads up", text, "warning");
    else toast(text, kind);
  });
})();
