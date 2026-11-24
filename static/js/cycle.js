/* Monthly / yearly switch on plan grids: shows the matching prices and carries the choice into
   checkout forms and sign-up links. Without JavaScript the server-rendered cycle is used. */
(function () {
  document.querySelectorAll("[data-cycle-switch]").forEach(function (sw) {
    let grid = sw.nextElementSibling;
    while (grid && !grid.classList.contains("plans")) grid = grid.nextElementSibling;
    if (!grid) return;
    function set(cycle) {
      grid.dataset.cycle = cycle;
      sw.querySelectorAll("[data-cycle]").forEach(b => b.setAttribute("aria-checked", String(b.dataset.cycle === cycle)));
      grid.querySelectorAll("[data-cycle-input]").forEach(i => { i.value = cycle; });
      grid.querySelectorAll("[data-cycle-link]").forEach(a => {
        const u = new URL(a.href, location.href); u.searchParams.set("cycle", cycle); a.href = u.pathname + u.search;
      });
    }
    sw.querySelectorAll("[data-cycle]").forEach(b => b.addEventListener("click", () => set(b.dataset.cycle)));
    sw.addEventListener("keydown", e => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        const next = grid.dataset.cycle === "yearly" ? "monthly" : "yearly"; set(next);
        sw.querySelector(`[data-cycle="${next}"]`).focus();
      }
    });
  });
})();
