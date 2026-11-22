/* Landing page: scroll reveals, the clock-in demo on the phone, the live feed and the rotating QR.
   Everything is decorative; the page reads fine with JavaScript off or reduced motion on. */
(function () {
  const $ = id => document.getElementById(id);
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Reveal sections as they scroll in
  const items = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !calm) {
    const io = new IntersectionObserver(entries => entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }), {threshold: .12, rootMargin: "0px 0px -40px 0px"});
    items.forEach((el, i) => { el.style.transitionDelay = (i % 4) * 70 + "ms"; io.observe(el); });
  } else {
    items.forEach(el => el.classList.add("in"));
  }

  // Nav border once scrolled
  const nav = document.querySelector(".lp-nav");
  const onScroll = () => nav.classList.toggle("scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, {passive: true}); onScroll();

  // Phone demo: today's date, then tap the round "Clock in" button → green tick and time
  const now = new Date();
  $("lp-today").textContent = now.toLocaleDateString([], {weekday: "long", day: "numeric", month: "long"});
  const btn = $("lp-btn"), status = $("lp-status");
  function demo() {
    btn.classList.add("press");
    setTimeout(() => {
      btn.classList.remove("press"); btn.classList.add("done");
      status.textContent = "Checked in · on time";
    }, 240);
    setTimeout(() => { btn.classList.remove("done"); status.textContent = "You're on site · 18 m away"; }, 4400);
  }
  if (!calm) { setTimeout(demo, 1400); setInterval(demo, 7000); }
  else { btn.classList.add("done"); status.textContent = "Checked in · on time"; }

  // Live feed: a new arrival slides in at the top every few seconds
  const feed = $("lp-feed");
  const people = [["Musa Bello", "MB", "In · 7:58", "ok"], ["Esther Pam", "EP", "In · 8:01", "ok"],
    ["Ibrahim Choji", "IC", "Late · 8:17", "late"], ["Ruth Dung", "RD", "In · 7:49", "ok"],
    ["Peter Adeyemi", "PA", "In · 8:05", "ok"], ["Naomi Danjuma", "ND", "In · 7:57", "ok"]];
  let k = 0;
  function arrive() {
    const [name, initials, when, kind] = people[k++ % people.length];
    const row = document.createElement("div");
    const av = document.createElement("span"); av.className = "lp-av"; av.textContent = initials;
    const b = document.createElement("b"); b.textContent = name;
    const em = document.createElement("em"); em.className = kind; em.textContent = when;
    row.append(av, b, em); row.classList.add("fresh");
    feed.prepend(row);
    setTimeout(() => row.classList.remove("fresh"), 1600);
    while (feed.children.length > 3) feed.lastElementChild.remove();
  }
  if (!calm) setInterval(arrive, 3800);

  // Kiosk: a QR-like pattern that changes every few seconds, with a countdown
  const qr = $("lp-qr"), bar = $("lp-bar"), secs = $("lp-secs"), clock = $("lp-clock");
  const N = 25, NS = "http://www.w3.org/2000/svg";
  function finder(svg, x, y) {
    [[7, "#0d1530"], [5, "#fff"], [3, "#0d1530"]].forEach(([s, c], i) => {
      const r = document.createElementNS(NS, "rect");
      r.setAttribute("x", x + i); r.setAttribute("y", y + i); r.setAttribute("width", s); r.setAttribute("height", s);
      r.setAttribute("rx", i === 2 ? .6 : 1.2); r.setAttribute("fill", c); svg.appendChild(r);
    });
  }
  function drawQr() {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${N} ${N}`);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const inFinder = (x < 8 && y < 8) || (x > N - 9 && y < 8) || (x < 8 && y > N - 9);
      if (inFinder || Math.random() < .52) continue;
      const r = document.createElementNS(NS, "rect");
      r.setAttribute("x", x + .08); r.setAttribute("y", y + .08); r.setAttribute("width", .84); r.setAttribute("height", .84);
      r.setAttribute("rx", .25); r.setAttribute("fill", "#0d1530"); svg.appendChild(r);
    }
    finder(svg, 0, 0); finder(svg, N - 7, 0); finder(svg, 0, N - 7);
    qr.classList.add("swap");
    setTimeout(() => { qr.replaceChildren(svg); qr.classList.remove("swap"); }, 200);
  }
  const ROT = 30;
  let left = ROT;
  drawQr();
  function tick() {
    const t = new Date();
    clock.textContent = t.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
    left -= 1;
    if (left <= 0) { left = ROT; drawQr(); }
    secs.textContent = left;
    bar.style.width = (left / ROT * 100) + "%";
  }
  tick();
  setInterval(tick, 1000);
})();
