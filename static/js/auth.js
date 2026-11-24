/* Sign-in and create-organisation pages. Everything still works as a plain form without this script. */
(function () {
  const $ = id => document.getElementById(id);
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
    del(k) { try { localStorage.removeItem(k); } catch (e) {} }
  };

  // ---- Brand panel: live clock and rotating highlights ----
  function tick() {
    const now = new Date();
    if ($("ap-time")) $("ap-time").textContent = now.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
    if ($("ap-date")) $("ap-date").textContent = now.toLocaleDateString([], {weekday: "long", day: "numeric", month: "long"});
  }
  tick(); setInterval(tick, 1000);
  const points = document.querySelectorAll("#ap-points li");
  let p = 0;
  if (points.length && !calm) setInterval(() => {
    points[p].classList.remove("on"); p = (p + 1) % points.length; points[p].classList.add("on");
  }, 3600);

  // ---- Shared: show/hide password, busy submit, open help ----
  document.querySelectorAll("[data-eye]").forEach(btn => btn.addEventListener("click", () => {
    const input = $(btn.dataset.eye), show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.setAttribute("aria-pressed", String(show));
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    input.focus();
  }));
  document.querySelectorAll("[data-open]").forEach(b => b.addEventListener("click", () => {
    const d = $(b.dataset.open); d.open = true; d.scrollIntoView({behavior: calm ? "auto" : "smooth", block: "center"});
  }));
  function busy(form) {
    form.addEventListener("submit", e => {
      const btn = form.querySelector('button[type="submit"]:not([hidden])');
      if (btn && btn.classList.contains("busy")) { e.preventDefault(); return; }
      if (btn) btn.classList.add("busy");
    });
  }

  // ---- Sign in ----
  const login = $("af-login");
  if (login) {
    const user = $("id_username"), pass = $("id_password");
    busy(login);
    user.addEventListener("input", () => {
      const pos = user.selectionStart;
      user.value = user.value.toUpperCase().replace(/\s+/g, "");
      user.setSelectionRange(pos, pos);
    });
    const caps = $("af-caps");
    ["keydown", "keyup"].forEach(ev => pass.addEventListener(ev, e => {
      if (e.getModifierState) caps.hidden = !e.getModifierState("CapsLock");
    }));
    pass.addEventListener("blur", () => { caps.hidden = true; });
    login.addEventListener("submit", () => { if (user.value.trim()) store.set("attendpro:lastId", user.value.trim().toUpperCase()); });

    // Remembered ID on this device
    const last = store.get("attendpro:lastId");
    if (last && !user.value) {
      $("af-recent").hidden = false;
      $("af-recent-id").textContent = last;
      $("af-recent-av").textContent = last.split("-")[0].slice(0, 3);
      $("af-recent-use").addEventListener("click", () => { user.value = last; pass.focus(); $("af-recent").hidden = true; });
      $("af-recent-forget").addEventListener("click", () => { store.del("attendpro:lastId"); $("af-recent").hidden = true; user.focus(); });
    } else if (!user.value) {
      user.focus();
    } else {
      pass.focus();
    }
  }

  // ---- Create organisation: 4-step wizard ----
  const reg = $("af-reg");
  if (!reg) return;
  busy(reg);
  const steps = [...reg.querySelectorAll(".af-step")];
  const marks = [...document.querySelectorAll("#af-steps li")];
  const back = $("af-back"), next = $("af-next"), create = $("af-create");
  const f = name => reg.querySelector(`[name="${name}"]`);
  let current = 1, codeState = {code: "", ok: false};
  let codeTouched = !!f("code").value;

  function setError(input, msg) {
    const field = input.closest(".af-field") || input.closest(".af-step");
    let el = field.querySelector(".af-err-js");
    if (!el) { el = document.createElement("div"); el.className = "af-err af-err-js"; field.appendChild(el); }
    el.textContent = msg || "";
    field.classList.toggle("bad", !!msg);
    if (input.setAttribute) input.setAttribute("aria-invalid", msg ? "true" : "false");
    return !msg;
  }

  function show(n, focus) {
    current = n;
    steps.forEach(s => s.classList.toggle("on", +s.dataset.step === n));
    marks.forEach(m => {
      const i = +m.dataset.go;
      m.classList.toggle("on", i === n); m.classList.toggle("done", i < n);
      m.setAttribute("aria-current", i === n ? "step" : "false");
    });
    $("af-progress").style.width = (n / 4 * 100) + "%";
    back.classList.toggle("hide", n === 1);
    next.style.display = n === 4 ? "none" : "";
    create.classList.toggle("show", n === 4);
    if (n === 4) review();
    if (focus !== false) {
      const first = steps[n - 1].querySelector("input:not([type=radio]):not([type=hidden]), select, input[type=radio]:checked, input[type=radio]");
      if (first && window.innerWidth > 960) first.focus({preventScroll: true});
      reg.closest(".af-inner").scrollIntoView({behavior: calm ? "auto" : "smooth", block: "start"});
    }
  }

  async function valid(n) {
    if (n === 1) {
      const picked = reg.querySelector('input[name="plan"]:checked');
      return setError(reg.querySelector('input[name="plan"]'), picked ? "" : "Choose a plan to continue.");
    }
    if (n === 2) {
      let ok = setError(f("org_name"), f("org_name").value.trim() ? "" : "Enter your organisation's name.");
      const code = f("code").value.trim().toUpperCase();
      if (!/^[A-Z0-9]{2,6}$/.test(code)) {
        codeMsg("2–6 letters or numbers.", "bad"); f("code").setAttribute("aria-invalid", "true"); return false;
      }
      if (codeState.code !== code) await checkCode();
      if (!codeState.ok) { f("code").setAttribute("aria-invalid", "true"); return false; }
      return ok;
    }
    if (n === 3) {
      let ok = true;
      ok = setError(f("first_name"), f("first_name").value.trim() ? "" : "Enter your first name.") && ok;
      ok = setError(f("last_name"), f("last_name").value.trim() ? "" : "Enter your last name.") && ok;
      ok = setError(f("email"), /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f("email").value.trim()) ? "" : "Enter a valid email address.") && ok;
      ok = setError(f("password1"), f("password1").value.length >= 6 ? "" : "Use at least 6 characters.") && ok;
      ok = setError(f("password2"), f("password2").value === f("password1").value && f("password2").value ? "" : "The passwords don't match.") && ok;
      return ok;
    }
    return true;
  }

  next.addEventListener("click", async () => {
    if (await valid(current)) show(current + 1);
    else { const bad = steps[current - 1].querySelector('[aria-invalid="true"], .bad input'); if (bad) bad.focus(); }
  });
  back.addEventListener("click", () => show(Math.max(1, current - 1)));
  marks.forEach(m => m.addEventListener("click", () => { if (m.classList.contains("done")) show(+m.dataset.go); }));
  reg.querySelectorAll("[data-go]").forEach(b => { if (b.tagName === "BUTTON") b.addEventListener("click", () => show(+b.dataset.go)); });
  reg.addEventListener("keydown", e => {
    if (e.key === "Enter" && current < 4 && e.target.tagName === "INPUT") { e.preventDefault(); next.click(); }
  });

  // Monthly / yearly
  const cycleInput = $("af-cycle"), plansBox = $("af-plans");
  function price(r) {
    return cycleInput.value === "yearly" && r.dataset.priceYearly ? r.dataset.priceYearly : r.dataset.price;
  }
  $("af-cycle-switch").querySelectorAll("[data-cycle]").forEach(b => b.addEventListener("click", () => {
    cycleInput.value = b.dataset.cycle; plansBox.dataset.cycle = b.dataset.cycle;
    $("af-cycle-switch").querySelectorAll("[data-cycle]").forEach(x => x.setAttribute("aria-checked", String(x === b)));
    planChanged();
  }));

  // Plan → summary card in the brand panel
  function planChanged() {
    const r = reg.querySelector('input[name="plan"]:checked');
    const card = $("ap-plan");
    if (!r || !card) return;
    card.hidden = false;
    $("ap-plan-name").textContent = r.dataset.name;
    $("ap-plan-price").textContent = price(r);
    $("ap-plan-staff").textContent = r.dataset.staff;
    $("ap-plan-next").textContent = r.dataset.free === "1" ? "Free forever. You'll go straight to your dashboard."
      : "You'll pay securely with Paystack right after creating your account.";
    setError(r, "");
  }
  reg.querySelectorAll('input[name="plan"]').forEach(r => r.addEventListener("change", () => {
    planChanged();
    if (!calm) setTimeout(() => show(2), 260); else show(2);
  }));
  planChanged();

  // Short code: suggestion from the name, live availability, ID preview
  const codeInput = f("code"), state = $("af-code-state"), msg = $("af-code-msg");
  function codeMsg(text, kind, suggestion) {
    msg.replaceChildren();
    const s = document.createElement("span"); s.className = kind || ""; s.textContent = text; msg.appendChild(s);
    if (suggestion) {
      const b = document.createElement("button"); b.type = "button"; b.className = "af-link"; b.textContent = `Use ${suggestion}`;
      b.addEventListener("click", () => { codeInput.value = suggestion; codeTouched = true; checkCode(); });
      msg.appendChild(b);
    }
    state.className = "af-code-state " + (kind === "good" ? "ok" : kind === "bad" ? "bad" : kind === "wait" ? "wait" : "");
  }
  function preview() {
    const code = codeInput.value.trim().toUpperCase() || "TTC";
    [1, 2, 3].forEach(i => { $("af-id" + i).textContent = `${code}-000${i}`; });
    $("af-id-you").textContent = `${code}-0001`;
    $("af-ids").hidden = !codeInput.value.trim();
  }
  let seq = 0;
  async function checkCode(fromName) {
    const my = ++seq;
    const code = codeInput.value.trim().toUpperCase();
    const params = new URLSearchParams({code: fromName ? "" : code, name: f("org_name").value});
    if (!fromName && code.length < 2) { codeMsg("2–6 letters or numbers"); codeState = {code, ok: false}; return; }
    if (!fromName) codeMsg("Checking…", "wait");
    try {
      const d = await (await fetch(`${reg.dataset.checkUrl}?${params}`, {headers: {"Accept": "application/json"}})).json();
      if (my !== seq) return;
      if (fromName) {
        if (d.suggestion && !codeTouched) { codeInput.value = d.suggestion; preview(); return checkCode(); }
        return;
      }
      codeState = {code: d.code, ok: d.ok};
      codeMsg(d.message, d.ok ? "good" : "bad", d.ok ? "" : d.suggestion);
    } catch (e) {
      if (my === seq) { codeState = {code, ok: true}; codeMsg("Couldn't check right now; we'll check when you create."); }
    }
    preview();
  }
  let t1, t2;
  f("org_name").addEventListener("input", () => {
    setError(f("org_name"), "");
    clearTimeout(t1); t1 = setTimeout(() => { if (!codeTouched) checkCode(true); }, 350);
  });
  codeInput.addEventListener("input", () => {
    codeTouched = !!codeInput.value;
    codeInput.value = codeInput.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
    preview();
    clearTimeout(t2); t2 = setTimeout(checkCode, 300);
  });
  if (codeInput.value) { preview(); if (!msg.querySelector(".bad")) checkCode(); }

  // Password strength and match
  const p1 = f("password1"), p2 = f("password2");
  function strength() {
    const v = p1.value;
    let s = 0;
    if (v.length >= 6) s++; if (v.length >= 10) s++;
    if (/[a-z]/.test(v) && /[A-Z]/.test(v)) s++; if (/\d/.test(v)) s++; if (/[^A-Za-z0-9]/.test(v)) s++;
    const levels = [["", "At least 6 characters", ""], ["#e8505b", "Weak: add more characters", "bad"],
                    ["#f59f00", "Okay: add a number or symbol", ""], ["#f59f00", "Good", ""],
                    ["#12b886", "Strong", "good"], ["#0b8a64", "Very strong", "good"]];
    const [color, text, cls] = v ? levels[Math.max(1, s)] : levels[0];
    const bar = $("af-meter");
    bar.style.width = v ? (Math.max(1, s) / 5 * 100) + "%" : "0"; bar.style.background = color;
    const label = $("af-meter-text"); label.textContent = text; label.className = "af-meter-text " + cls;
    match();
  }
  function match() {
    const ok = p2.value && p2.value === p1.value;
    $("af-match").className = "af-match" + (ok ? " ok" : "");
    const t = $("af-match-text");
    t.textContent = !p2.value ? "" : ok ? "Passwords match" : "Not the same yet";
    t.className = "af-meter-text " + (!p2.value ? "" : ok ? "good" : "bad");
  }
  p1.addEventListener("input", () => { setError(p1, ""); strength(); });
  p2.addEventListener("input", () => { setError(p2, ""); match(); });
  ["first_name", "last_name", "email"].forEach(n => f(n).addEventListener("input", () => setError(f(n), "")));

  // Review
  function review() {
    const r = reg.querySelector('input[name="plan"]:checked');
    const type = f("org_type");
    const code = codeInput.value.trim().toUpperCase();
    $("rv-plan").textContent = r ? `${r.dataset.name} · ${price(r)}` : "—";
    $("rv-org").textContent = `${f("org_name").value.trim()} (${type.options[type.selectedIndex].text})`;
    $("rv-id").textContent = code ? `${code}-0001` : "—";
    $("rv-admin").textContent = `${f("first_name").value.trim()} ${f("last_name").value.trim()} · ${f("email").value.trim()}`;
    $("rv-next").textContent = r && r.dataset.free === "0"
      ? "Next: pay securely with Paystack. You can use the free plan until the payment is confirmed."
      : "Next: your dashboard, where you can add your team.";
  }

  // Start: on the step the server flagged, or the first one
  const start = +reg.dataset.errorStep || 1;
  show(start, start !== 1);
})();
