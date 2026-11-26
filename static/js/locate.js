/* Precise location for clock-in, QR scans and setting a site's position.
 *
 * Phones usually answer a location request first with a rough, network-based fix (±500 m or worse)
 * and only reach GPS accuracy a few seconds later. So instead of taking the first answer, this
 * WATCHES the position with high accuracy and no cached readings, keeps the most precise one, and
 * finishes as soon as it is precise enough (or when time runs out, with the best it got).
 *
 * Inside the AttendPro Android / iPhone app it uses the native GPS (Capacitor Geolocation:
 * Android's fused provider / iOS Core Location), spots "Approximate location only", and when the
 * phone's Location is switched off, Android shows its own one-tap "Turn on location?" dialog.
 *
 *   AttendPro.locate({ target: 25, maxWait: 25000, onProgress: (accuracy, seconds) => {} })
 *     → Promise<{ lat, lng, accuracy }>
 *     or rejects with { kind, title, message }   kind: "off" | "denied" | "precise" | "weak" | "unsupported"
 *
 *   AttendPro.locationHelp(error, retry) shows a help panel for those errors (returns false if it
 *   isn't a location error), with steps to fix it and a "Try again" button that calls retry().
 */
window.AttendPro = window.AttendPro || {};
(function () {
  "use strict";
  var ua = navigator.userAgent || "";
  var inApp = /AttendProApp\//.test(ua);
  var android = /Android/i.test(ua), ios = /iPhone|iPad|iPod/i.test(ua);

  function preciseHelp() {
    if (inApp && android) return "On your phone: Settings → Apps → AttendPro → Permissions → Location → Allow, and turn on “Use precise location”. Also turn on Settings → Location → Google Location Accuracy.";
    if (inApp && ios) return "On your iPhone: Settings → AttendPro → Location → While Using the App, and turn on Precise Location.";
    if (android) return "On your phone: Settings → Apps → Chrome → Permissions → Location → turn on “Use precise location”. Also turn on Settings → Location → Google Location Accuracy.";
    if (ios) return "On your iPhone: Settings → Privacy & Security → Location Services → Safari Websites → While Using the App, and turn on Precise Location.";
    return "Turn on precise location / GPS for this browser.";
  }
  AttendPro.preciseHelp = preciseHelp;

  function offError() {
    return { kind: "off", title: "Turn on your Location",
             message: "Your phone's Location (GPS) is switched off. AttendPro needs it to confirm you're at work." };
  }
  function permissionError() {
    return { kind: "denied", title: "Allow AttendPro to use your location",
             message: (inApp ? "AttendPro needs your location to confirm you're at work. "
                             : "This site needs your location to confirm you're at work. ") + preciseHelp() };
  }
  function preciseError() {
    return { kind: "precise", title: "Turn on precise location",
             message: "AttendPro only has your approximate location, which can't confirm you're at work. " + preciseHelp() };
  }
  function weakError() {
    return { kind: "weak", title: "Couldn't find your location",
             message: "Your phone couldn't get a location in time. Check that Location is on, step outside or near a window, and try again." };
  }

  function nativeGeo() {
    var Cap = window.Capacitor;
    return Cap && Cap.isNativePlatform && Cap.isNativePlatform() && Cap.Plugins && Cap.Plugins.Geolocation;
  }
  // Errors from the native plugin: OS-PLUG-GLOC-0007 location off, -0009 user said no to turning it on,
  // -0003 permission denied.
  function isOff(err) {
    var s = String((err && (err.code || "")) + " " + (err && (err.message || err)) || "");
    return /GLOC-000[79]|not enabled|disabled|enable location was denied/i.test(s);
  }
  function isDenied(err) {
    var s = String((err && (err.code || "")) + " " + (err && (err.message || err)) || "");
    return /GLOC-0003|permission.*denied|denied.*permission/i.test(s);
  }

  // ── Warm-up ────────────────────────────────────────────────────────────────
  // Cheap phones can take 30-60 s to find GPS. Pages that will need the location call
  // AttendPro.warmUp() when they open (only if permission is already granted, so nobody is
  // prompted), and locate() starts from the best reading found so far.
  var listeners = [], warm = null;
  function share(coords, timestamp) {
    if (!coords) return;
    var r = { lat: coords.latitude, lng: coords.longitude, accuracy: Math.abs(Number(coords.accuracy) || 99999), t: Date.now() };
    if (!warm || r.accuracy <= warm.accuracy || Date.now() - warm.t > 20000) warm = r;
    listeners.slice().forEach(function (fn) { fn(coords, timestamp); });
  }
  AttendPro.warmUp = function (seconds) {
    if (AttendPro._warming) return;
    var G = nativeGeo(), stopAt = Date.now() + (seconds || 120) * 1000, stop = function () {};
    function start() {
      AttendPro._warming = true;
      if (G) {
        G.watchPosition({ enableHighAccuracy: true, maximumAge: 0 }, function (pos) { if (pos) share(pos.coords, pos.timestamp); })
          .then(function (id) { stop = function () { G.clearWatch({ id: id }); }; }).catch(function () {});
      } else if (navigator.geolocation) {
        var id = navigator.geolocation.watchPosition(function (pos) { share(pos.coords, pos.timestamp); }, function () {},
                                                     { enableHighAccuracy: true, maximumAge: 0 });
        stop = function () { navigator.geolocation.clearWatch(id); };
      }
      var iv = setInterval(function () {
        if (Date.now() > stopAt || document.visibilityState === "hidden") { clearInterval(iv); stop(); AttendPro._warming = false; }
      }, 2000);
    }
    if (G) {
      G.checkPermissions().then(function (p) { if (p.location === "granted") start(); }).catch(function () {});
    } else if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions.query({ name: "geolocation" }).then(function (p) { if (p.state === "granted") start(); }).catch(function () {});
    }
  };

  AttendPro.locate = function (opts) {
    if (typeof opts === "number") opts = { maxWait: opts };
    opts = opts || {};
    var target = opts.target || 25;           // metres: good enough to stop straight away
    var goodEnough = opts.goodEnough || 60;   // after `patience`, accept this
    var patience = opts.patience || 8000;
    var maxWait = opts.maxWait || 25000;
    var onProgress = opts.onProgress || function () {};
    var started = Date.now();

    return new Promise(function (resolve, reject) {
      var best = null, done = false, stop = function () {}, timer, unavailable = false;

      var fail = function (err) {
        if (done) return;
        done = true; clearTimeout(timer);
        try { stop(); } catch (e) { /* already stopped */ }
        reject(err);
      };
      var finish = function () {
        if (done) return;
        if (best) {
          done = true; clearTimeout(timer);
          try { stop(); } catch (e) { /* already stopped */ }
          resolve(best);
        } else fail(unavailable ? offError() : weakError());
      };

      function reading(coords, timestamp) {
        if (done || !coords) return;
        // Skip stale readings a browser may hand back from its cache.
        if (timestamp && timestamp < started - 3000 && best) return;
        var acc = Math.abs(Number(coords.accuracy) || 99999);
        if (!best || acc < best.accuracy) best = { lat: coords.latitude, lng: coords.longitude, accuracy: acc };
        var secs = Math.round((Date.now() - started) / 1000);
        onProgress(Math.round(best.accuracy), secs);
        if (best.accuracy <= target || (Date.now() - started >= patience && best.accuracy <= goodEnough)) finish();
      }

      listeners.push(reading);
      var cleanup = function () { var i = listeners.indexOf(reading); if (i > -1) listeners.splice(i, 1); };
      var _fail = fail, _finish = finish;
      fail = function (e) { cleanup(); _fail(e); };
      finish = function () { if (!done) cleanup(); _finish(); };
      timer = setTimeout(function () { finish(); }, maxWait);
      if (warm && Date.now() - warm.t < 60000) {   // start from what the warm-up already found
        setTimeout(function () { reading({ latitude: warm.lat, longitude: warm.lng, accuracy: warm.accuracy }, Date.now()); }, 0);
      }
      setTimeout(function () { if (!done && best && best.accuracy <= goodEnough) finish(); }, patience);

      var G = nativeGeo();
      if (G) {
        // Native GPS in the app. Spot "Approximate location" on Android 12+ (coarse only).
        G.checkPermissions().then(function (p) {
          if (p.location === "granted") return p;
          return G.requestPermissions({ permissions: ["location", "coarseLocation"] });
        }).then(function (p) {
          if (p.location === "granted") return nativeWatch();
          if (p.coarseLocation === "granted") fail(preciseError()); else fail(permissionError());
        }).catch(function (err) {
          // Location switched off: watching anyway makes Android offer its "Turn on location?" dialog.
          if (isOff(err)) nativeWatch(); else useBrowser();
        });
      } else {
        useBrowser();
      }

      function nativeWatch() {
        if (done) return;
        return G.watchPosition({ enableHighAccuracy: true, timeout: maxWait, maximumAge: 0 }, function (pos, err) {
          if (err) {
            if (isDenied(err)) fail(permissionError());
            else if (isOff(err) && !best) fail(offError());
            return;
          }
          if (pos) share(pos.coords, pos.timestamp);
        }).then(function (id) {
          stop = function () { G.clearWatch({ id: id }); };
          if (done) stop();
        }).catch(function (err) {
          if (isDenied(err)) fail(permissionError()); else if (isOff(err)) fail(offError()); else useBrowser();
        });
      }

      function useBrowser() {
        if (done) return;
        if (!navigator.geolocation) {
          fail({ kind: "unsupported", title: "Location not supported",
                 message: "This browser can't share your location. Try Chrome or Safari on your phone." });
          return;
        }
        var id = navigator.geolocation.watchPosition(
          function (pos) { share(pos.coords, pos.timestamp); },
          function (err) {
            if (err && err.code === 1) { fail(permissionError()); return; }
            if (err && err.code === 2) {          // usually: the phone's Location is switched off
              unavailable = true;
              if (!best && Date.now() - started > 5000) fail(offError());
            }
          },
          { enableHighAccuracy: true, timeout: maxWait, maximumAge: 0 });
        stop = function () { navigator.geolocation.clearWatch(id); };
        if (done) stop();
      }
    });
  };

  // ── Help panel ──────────────────────────────────────────────────────────────
  var PIN = '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5c0 1-.2 2-.6 3"/><circle cx="12" cy="9.5" r="2.5"/><path d="m16 16 5 5m0-5-5 5"/></svg>';
  var CSS = ".aplh{position:fixed;inset:0;z-index:2147483600;display:flex;align-items:flex-end;justify-content:center;" +
    "background:rgba(10,17,40,.55);animation:aplhIn .2s ease}" +
    ".aplh-box{width:100%;max-width:460px;background:#fff;color:#1a2036;border-radius:24px 24px 0 0;padding:24px 22px calc(22px + env(safe-area-inset-bottom));" +
    "font:15px/1.5 'Segoe UI',system-ui,-apple-system,Roboto,sans-serif;box-shadow:0 -20px 50px rgba(0,0,0,.25);animation:aplhUp .28s cubic-bezier(.2,.7,.2,1)}" +
    "@media(min-width:600px){.aplh{align-items:center}.aplh-box{border-radius:24px}}" +
    ".aplh-ico{width:58px;height:58px;border-radius:18px;display:grid;place-items:center;background:#fde7e8;color:#e8505b;margin-bottom:14px}" +
    ".aplh h3{margin:0 0 6px;font-size:21px;line-height:1.25;color:#0d1530}.aplh p{margin:0 0 14px;color:#5a6277}" +
    ".aplh ol{margin:0 0 18px;padding:0;list-style:none;counter-reset:s}" +
    ".aplh li{counter-increment:s;display:flex;gap:12px;align-items:flex-start;padding:9px 0;border-top:1px dashed #e5e9f2}" +
    ".aplh li:before{content:counter(s);flex-shrink:0;width:26px;height:26px;border-radius:50%;background:#e3f8f0;color:#0b8a64;" +
    "font-weight:800;font-size:13px;display:grid;place-items:center}" +
    ".aplh li b{color:#0d1530}" +
    ".aplh-btns{display:flex;flex-direction:column;gap:8px}" +
    ".aplh-btns button{border:0;border-radius:14px;padding:14px;font:inherit;font-weight:700;font-size:16px;cursor:pointer}" +
    ".aplh-go{background:#12b886;color:#fff}.aplh-x{background:#f1f3f8;color:#1a2036}" +
    "@keyframes aplhIn{from{opacity:0}}@keyframes aplhUp{from{transform:translateY(40px);opacity:.4}}";

  function steps(kind) {
    if (kind === "off") {
      if (ios) return ["Open <b>Settings → Privacy &amp; Security → Location Services</b>",
                       "Turn <b>Location Services</b> on", "Come back here and tap <b>Try again</b>"];
      return ["<b>Swipe down</b> from the top of your screen", "Tap the <b>Location</b> 📍 icon to turn it on",
              "Come back here and tap <b>Try again</b>"];
    }
    if (kind === "denied") {
      if (inApp && android) return ["Open <b>Settings → Apps → AttendPro → Permissions</b>",
                                    "Tap <b>Location</b> → <b>Allow only while using the app</b>, and turn on <b>Use precise location</b>",
                                    "Come back here and tap <b>Try again</b>"];
      if (inApp && ios) return ["Open <b>Settings → AttendPro → Location</b>", "Choose <b>While Using the App</b> and turn on <b>Precise Location</b>",
                                "Come back here and tap <b>Try again</b>"];
      return ["Tap the <b>🔒 or ⓘ icon</b> next to the web address", "Set <b>Location</b> to <b>Allow</b>",
              "Tap <b>Try again</b>"];
    }
    if (kind === "precise") return [preciseHelp(), "Come back here and tap <b>Try again</b>"];
    if (kind === "imprecise") {
      if (ios) return ["Turn on <b>Wi-Fi</b> (it helps even if you don't connect)",
                       "Open <b>Settings → AttendPro → Location</b> and turn on <b>Precise Location</b>",
                       "Go <b>outside or near a window</b> for a minute", "Tap <b>Try again</b>"];
      return ["Turn on <b>Wi-Fi</b>. It helps your phone find its location, even if you don't connect to a network",
              "Open <b>Settings → Location → Location services</b> and turn on <b>Google Location Accuracy</b>",
              "Go <b>outside or near a window</b> and wait about a minute", "Tap <b>Try again</b>"];
    }
    if (kind === "weak") return ["Check your phone's <b>Location</b> 📍 is on", "Step <b>outside or near a window</b> and wait a few seconds",
                                 "Tap <b>Try again</b>"];
    return [];
  }

  AttendPro.locationHelp = function (err, retry, extra) {
    if (!err || ["off", "denied", "precise", "weak", "imprecise"].indexOf(err.kind) === -1) return false;
    if (!document.getElementById("aplh-css")) {
      var st = document.createElement("style"); st.id = "aplh-css"; st.textContent = CSS; document.head.appendChild(st);
    }
    var old = document.querySelector(".aplh"); if (old) old.remove();
    var wrap = document.createElement("div");
    wrap.className = "aplh"; wrap.setAttribute("role", "dialog"); wrap.setAttribute("aria-modal", "true");
    var box = document.createElement("div"); box.className = "aplh-box";
    box.innerHTML = '<div class="aplh-ico">' + PIN + "</div>";
    var h = document.createElement("h3"); h.textContent = err.title; box.appendChild(h);
    var p = document.createElement("p");
    p.textContent = err.kind === "precise" || err.kind === "denied" ? err.message.split(". ")[0] + "." : err.message;
    box.appendChild(p);
    var ol = document.createElement("ol");
    steps(err.kind).forEach(function (s) { var li = document.createElement("li"); var span = document.createElement("span"); span.innerHTML = s; li.appendChild(span); ol.appendChild(li); });
    box.appendChild(ol);
    var btns = document.createElement("div"); btns.className = "aplh-btns";
    var go = document.createElement("button"); go.type = "button"; go.className = "aplh-go"; go.textContent = "Try again";
    var x = document.createElement("button"); x.type = "button"; x.className = "aplh-x"; x.textContent = "Close";
    btns.appendChild(go);
    if (extra) {   // e.g. "Pick on map" when setting a location
      var ex = document.createElement("button"); ex.type = "button"; ex.className = "aplh-x"; ex.textContent = extra.label;
      ex.onclick = function () { close(); extra.run(); }; btns.appendChild(ex);
    }
    btns.appendChild(x); box.appendChild(btns); wrap.appendChild(box);
    function close() { wrap.remove(); document.removeEventListener("visibilitychange", back); }
    function back() {  // returning from the phone's settings: try again straight away
      if (document.visibilityState === "visible" && retry) { close(); retry(); }
    }
    go.onclick = function () { close(); if (retry) retry(); };
    x.onclick = close;
    wrap.addEventListener("click", function (e) { if (e.target === wrap) close(); });
    document.addEventListener("visibilitychange", back);
    document.body.appendChild(wrap);
    go.focus();
    return true;
  };
})();
