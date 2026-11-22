/* Analytics charts: plain SVG, no libraries. Data comes from <script id="chart-data" type="application/json">.
   Every value shown on hover is also in the table view under each chart. Labels are set with textContent. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const C = {
    onTime: "#119e72", late: "#c98300", absent: "#de4450", series: "#3b5bdb",
    grid: "#e5e9f2", axis: "#6b7489", surface: "#ffffff", text: "#1a2036"
  };
  const data = JSON.parse(document.getElementById("chart-data").textContent);

  function svgEl(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(parent, x, y, str, attrs) {
    const t = svgEl("text", Object.assign({x: x, y: y, fill: C.axis, "font-size": 11}, attrs || {}), parent);
    t.textContent = str;
    return t;
  }
  // Column with a 4px rounded data-end and a square base
  function column(parent, x, y, w, h, fill, round) {
    if (h <= 0) return null;
    const r = round ? Math.min(4, h, w / 2) : 0;
    const d = `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
    return svgEl("path", {d: d, fill: fill}, parent);
  }
  function tipFor(box) {
    const tip = document.createElement("div");
    tip.className = "viz-tip";
    tip.hidden = true;
    box.appendChild(tip);
    return {
      show(x, y, title, rows) {
        tip.replaceChildren();
        const h = document.createElement("div");
        h.className = "viz-tip-title";
        h.textContent = title;
        tip.appendChild(h);
        rows.forEach(r => {
          const row = document.createElement("div");
          row.className = "viz-tip-row";
          if (r.color) { const k = document.createElement("i"); k.style.background = r.color; row.appendChild(k); }
          const v = document.createElement("b"); v.textContent = r.value; row.appendChild(v);
          const l = document.createElement("span"); l.textContent = r.label; row.appendChild(l);
          tip.appendChild(row);
        });
        tip.hidden = false;
        const bw = box.clientWidth, tw = tip.offsetWidth;
        tip.style.left = Math.max(0, Math.min(bw - tw, x - tw / 2)) + "px";
        tip.style.top = Math.max(0, y - tip.offsetHeight - 12) + "px";
      },
      hide() { tip.hidden = true; }
    };
  }
  function frame(box, height) {
    box.querySelectorAll("svg").forEach(s => s.remove());
    const W = Math.max(box.clientWidth, 280);
    return {W: W, H: height, svg: svgEl("svg", {width: W, height: height, viewBox: `0 0 ${W} ${height}`, role: "img"}, null)};
  }
  function yGrid(svg, m, W, H, ticks, fmt) {
    ticks.forEach(v => {
      const y = m.y(v);
      svgEl("line", {x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: C.grid, "stroke-width": 1}, svg);
      text(svg, m.l - 8, y + 4, fmt(v), {"text-anchor": "end"});
    });
  }
  function niceMax(v) {
    if (v <= 4) return 4;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const s of [1, 2, 2.5, 5, 10]) if (s * p >= v) return s * p;
    return 10 * p;
  }

  // ---- Attendance rate trend: one series, line + wash, crosshair tooltip ----------------
  function trend(box) {
    const pts = data.trend;
    if (!pts.length) return;
    const f = frame(box, 230), svg = f.svg, W = f.W, H = f.H;
    const m = {l: 44, r: 52, t: 14, b: 30};
    m.y = v => m.t + (H - m.t - m.b) * (1 - v / 100);
    const x = i => pts.length === 1 ? (m.l + W - m.r) / 2 : m.l + (W - m.l - m.r) * i / (pts.length - 1);
    yGrid(svg, m, W, H, [0, 25, 50, 75, 100], v => v + "%");
    const step = Math.max(1, Math.ceil(pts.length / Math.max(2, Math.floor((W - m.l - m.r) / 70))));
    pts.forEach((p, i) => { if (i % step === 0 || i === pts.length - 1 && i % step > step / 2) text(svg, x(i), H - 10, p.label, {"text-anchor": "middle"}); });
    const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i)},${m.y(p.rate)}`).join("");
    svgEl("path", {d: `${line}L${x(pts.length - 1)},${m.y(0)}L${x(0)},${m.y(0)}Z`, fill: C.series, "fill-opacity": .1}, svg);
    svgEl("path", {d: line, fill: "none", stroke: C.series, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round"}, svg);
    const last = pts[pts.length - 1];
    svgEl("circle", {cx: x(pts.length - 1), cy: m.y(last.rate), r: 4, fill: C.series, stroke: C.surface, "stroke-width": 2}, svg);
    text(svg, x(pts.length - 1) + 8, m.y(last.rate) + 4, last.rate + "%", {fill: C.text, "font-weight": 600});
    const cross = svgEl("line", {y1: m.t, y2: H - m.b, stroke: C.axis, "stroke-width": 1, visibility: "hidden"}, svg);
    const dot = svgEl("circle", {r: 4, fill: C.series, stroke: C.surface, "stroke-width": 2, visibility: "hidden"}, svg);
    const hit = svgEl("rect", {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent"}, svg);
    const tip = tipFor(box);
    hit.addEventListener("pointermove", e => {
      const px = e.offsetX;
      let i = Math.round((px - m.l) / Math.max(1, (W - m.l - m.r)) * (pts.length - 1));
      i = Math.max(0, Math.min(pts.length - 1, i));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", m.y(pts[i].rate)); dot.setAttribute("visibility", "visible");
      tip.show(x(i), m.y(pts[i].rate), pts[i].label, [{color: C.series, value: pts[i].rate + "%", label: "attendance"}]);
    });
    hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hide(); });
    box.prepend(svg);
  }

  // ---- Weekday pattern: 100% stacked columns ----------------------------------------------
  function weekdays(box) {
    const rows = data.weekdays;
    if (!rows.length) return;
    const f = frame(box, 230), svg = f.svg, W = f.W, H = f.H;
    const m = {l: 44, r: 12, t: 14, b: 30};
    m.y = v => m.t + (H - m.t - m.b) * (1 - v / 100);
    yGrid(svg, m, W, H, [0, 25, 50, 75, 100], v => v + "%");
    const band = (W - m.l - m.r) / rows.length, bw = Math.min(24, band * .5);
    const tip = tipFor(box);
    const series = [["on_time", "On time", C.onTime], ["late", "Late", C.late], ["absent", "Absent", C.absent]];
    rows.forEach((r, i) => {
      const cx = m.l + band * i + band / 2, x0 = cx - bw / 2;
      const g = svgEl("g", {tabindex: 0, class: "viz-mark"}, svg);
      let acc = 0;
      const top = series.filter(s => r[s[0]] > 0).pop();
      series.forEach(s => {
        const v = r[s[0]];
        if (v <= 0) return;
        const y1 = m.y(acc + v), y0 = m.y(acc);
        column(g, x0, y1, bw, Math.max(0, y0 - y1 - (acc > 0 ? 2 : 0)), s[2], s === top);
        acc += v;
      });
      text(svg, cx, H - 10, r.label, {"text-anchor": "middle"});
      svgEl("rect", {x: m.l + band * i, y: m.t, width: band, height: H - m.t - m.b, fill: "transparent"}, g);
      const show = () => tip.show(cx, m.y(100), `${r.label} · ${r.n} expected days`,
        series.map(s => ({color: s[2], value: r[s[0]] + "%", label: s[1].toLowerCase()})));
      g.addEventListener("pointerenter", show); g.addEventListener("focus", show);
      g.addEventListener("pointerleave", () => tip.hide()); g.addEventListener("blur", () => tip.hide());
    });
    box.prepend(svg);
  }

  // ---- Arrival times: histogram, late buckets in amber, cut-off marked --------------------
  function arrivals(box) {
    const h = data.histogram, b = h.buckets;
    const max = Math.max(0, ...b.map(x => x.n));
    if (!max) return;
    const f = frame(box, 230), svg = f.svg, W = f.W, H = f.H;
    const m = {l: 44, r: 12, t: 22, b: 30};
    const top = niceMax(max);
    m.y = v => m.t + (H - m.t - m.b) * (1 - v / top);
    yGrid(svg, m, W, H, [0, top / 2, top], v => Math.round(v));
    const band = (W - m.l - m.r) / b.length, bw = Math.min(24, band - 2);
    const tip = tipFor(box);
    const cutIndex = b.findIndex(x => x.late);
    if (cutIndex > 0) {
      const cx = m.l + band * cutIndex - 1;
      svgEl("line", {x1: cx, x2: cx, y1: m.t - 8, y2: H - m.b, stroke: C.axis, "stroke-width": 1}, svg);
      text(svg, cx + 4, m.t - 10, "Late after " + h.cutoff, {fill: C.text});
    }
    const tallest = b.indexOf(b.reduce((a, c) => c.n > a.n ? c : a, b[0]));
    b.forEach((x, i) => {
      const cx = m.l + band * i + band / 2;
      const g = svgEl("g", {tabindex: 0, class: "viz-mark"}, svg);
      column(g, cx - bw / 2, m.y(x.n), bw, m.y(0) - m.y(x.n), x.late ? C.late : C.onTime, true);
      if (i === tallest) text(g, cx, m.y(x.n) - 5, String(x.n), {"text-anchor": "middle", fill: C.text, "font-weight": 600});
      if (i % 4 === 0) text(svg, cx - band / 2, H - 10, x.label.split("–")[0], {"text-anchor": "middle"});
      svgEl("rect", {x: m.l + band * i, y: m.t, width: band, height: H - m.t - m.b, fill: "transparent"}, g);
      const show = () => tip.show(cx, m.y(x.n), x.label, [{color: x.late ? C.late : C.onTime, value: String(x.n),
        label: x.n === 1 ? "arrival" : "arrivals"}]);
      g.addEventListener("pointerenter", show); g.addEventListener("focus", show);
      g.addEventListener("pointerleave", () => tip.hide()); g.addEventListener("blur", () => tip.hide());
    });
    box.prepend(svg);
  }

  const charts = [["chart-trend", trend], ["chart-weekdays", weekdays], ["chart-arrivals", arrivals]];
  function drawAll() { charts.forEach(([id, fn]) => { const box = document.getElementById(id); if (box) fn(box); }); }
  drawAll();
  let t;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(drawAll, 150); });
})();
