/* Pricing page: sliding pill on the Monthly/Yearly switch, and the "Which plan fits?" helper. */
(function () {
  const $ = id => document.getElementById(id);
  const grid = document.querySelector(".pr-cards");
  const sw = document.querySelector(".pr-switch");
  const plans = JSON.parse($("pr-plans").textContent);
  const naira = n => "₦" + Number(n).toLocaleString("en-NG");
  const cycle = () => (grid && grid.dataset.cycle) || "monthly";

  // Pill behind the selected option
  const pill = sw && sw.querySelector(".pr-switch-pill");
  function movePill() {
    const on = sw.querySelector('[aria-checked="true"]');
    if (!pill || !on) return;
    pill.style.width = on.offsetWidth + "px";
    pill.style.transform = `translateX(${on.offsetLeft - 4}px)`;
  }
  if (sw) {
    sw.classList.add("ready");
    movePill();
    window.addEventListener("resize", movePill);
    sw.addEventListener("cyclechange", () => {
      movePill();
      grid.classList.remove("swap"); void grid.offsetWidth; grid.classList.add("swap");
      fit();
    });
  }

  // Which plan fits?
  const range = $("pr-range"), out = $("pr-n");
  function fit() {
    if (!range) return;
    const n = Number(range.value);
    out.textContent = n >= 200 ? "200+" : n;
    range.style.setProperty("--p", ((n - 1) / (Number(range.max) - 1) * 100) + "%");
    const pick = plans.find(p => p.limit === null || p.limit >= n) || plans[plans.length - 1];
    $("pr-pick").textContent = pick.name;
    const yearly = cycle() === "yearly" && pick.yearly;
    $("pr-pick-price").textContent = pick.free ? "Free, no card needed"
      : yearly ? `${naira(pick.yearly)} a year` : `${naira(pick.price)} a month`;
    const link = $("pr-pick-link");
    link.href = `/register/?plan=${encodeURIComponent(pick.slug)}${pick.free ? "" : "&cycle=" + cycle()}`;
    if (touched) document.querySelectorAll(".pr-card").forEach(c => c.classList.toggle("pr-picked", c.dataset.plan === pick.slug));
  }
  let touched = false;
  if (range) range.addEventListener("input", () => { touched = true; fit(); });
  fit();
})();
