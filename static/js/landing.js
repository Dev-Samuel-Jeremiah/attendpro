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

  // Phone: plays itself until the visitor taps it, then it's theirs to try
  const now = new Date();
  $("lp-today").textContent = now.toLocaleDateString([], {weekday: "long", day: "numeric", month: "long"});
  const btn = $("lp-btn"), status = $("lp-status"), burst = $("lp-burst"), tryme = $("lp-tryme"), inTime = $("lp-in");
  let autoplay = null, resetTimer = null;
  function clockIn(fromVisitor) {
    if (btn.classList.contains("done")) {                 // tapping again resets, like clocking out
      btn.classList.remove("done"); status.textContent = "You're on site · 18 m away"; return;
    }
    btn.classList.add("press");
    setTimeout(() => {
      btn.classList.remove("press"); btn.classList.add("done");
      const t = fromVisitor ? new Date() : null;
      inTime.textContent = t ? t.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}) : "7:52 AM";
      status.textContent = "Checked in · on time";
      if (!calm) { burst.classList.remove("go"); void burst.offsetWidth; burst.classList.add("go"); }
    }, 200);
    clearTimeout(resetTimer);
    resetTimer = setTimeout(() => { btn.classList.remove("done"); status.textContent = "You're on site · 18 m away"; },
                            fromVisitor ? 6000 : 4400);
  }
  btn.addEventListener("click", () => {
    const first = autoplay !== null;                     // the visitor's first tap always clocks them in
    clearInterval(autoplay); autoplay = null; tryme.classList.add("gone");
    if (first && btn.classList.contains("done")) btn.classList.remove("done");
    clockIn(true);
  });
  if (!calm) { setTimeout(() => autoplay && clockIn(false), 1400); autoplay = setInterval(() => clockIn(false), 7000); }
  else { btn.classList.add("done"); status.textContent = "Checked in · on time"; }

  // Rotating word in the badge
  const words = ["schools", "offices", "clinics", "factories", "churches", "branches"];
  const rot = $("lp-rotate");
  let w = 0;
  if (!calm) setInterval(() => {
    rot.classList.add("out");
    setTimeout(() => { w = (w + 1) % words.length; rot.textContent = words[w]; rot.classList.remove("out"); }, 300);
  }, 2400);

  // Gentle 3D tilt of the hero illustration (mouse only)
  const art = $("lp-art");
  if (!calm && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    const hero = document.querySelector(".lp-hero");
    hero.addEventListener("pointermove", e => {
      const r = hero.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
      art.style.transform = `perspective(1200px) rotateY(${x * 6}deg) rotateX(${-y * 5}deg)`;
    });
    hero.addEventListener("pointerleave", () => { art.style.transform = ""; });
  }

  // Cursor glow on feature cards
  document.querySelectorAll(".lp-cell").forEach(cell => cell.addEventListener("pointermove", e => {
    const r = cell.getBoundingClientRect();
    cell.style.setProperty("--mx", (e.clientX - r.left) + "px");
    cell.style.setProperty("--my", (e.clientY - r.top) + "px");
  }));

  // Count-up facts, the steps connector, and anything else that animates once when seen
  function countUp(el) {
    const target = +el.dataset.count, t0 = performance.now(), dur = 1100;
    (function step(t) {
      const k = Math.min(1, (t - t0) / dur), eased = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(target * eased);
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }
  const once = (els, fn, threshold) => {
    if (calm || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { fn(e.target); io.unobserve(e.target); } }),
                                        {threshold: threshold || .4});
    els.forEach(el => io.observe(el));
  };
  const counters = document.querySelectorAll("[data-count]");
  if (!calm) counters.forEach(el => { el.textContent = "0"; });
  once(counters, countUp, .6);
  const steps = $("lp-steps");
  if (calm) steps.classList.add("drawn"); else once([steps], el => el.classList.add("drawn"), .35);

  // Reading progress + highlight the section in view
  const progress = $("lp-progress");
  const links = [...document.querySelectorAll(".lp-links a")];
  const sections = links.map(a => document.querySelector(a.getAttribute("href")));
  function onScrollMore() {
    const h = document.documentElement.scrollHeight - window.innerHeight;
    progress.style.width = (h > 0 ? window.scrollY / h * 100 : 0) + "%";
    let active = -1;
    sections.forEach((sec, i) => { if (sec && sec.getBoundingClientRect().top < window.innerHeight * .35) active = i; });
    links.forEach((a, i) => a.classList.toggle("on", i === active));
  }
  window.addEventListener("scroll", onScrollMore, {passive: true}); onScrollMore();

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
