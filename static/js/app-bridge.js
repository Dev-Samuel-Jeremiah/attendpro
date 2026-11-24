/*
 * static/js/app-bridge.js: connects AttendPro to the phone when it runs inside the AttendPro
 * Android / iPhone app (mobile/). base.html loads it only for requests from the app.
 *
 * It is served by the website, so changing it here changes the apps for everyone at the next
 * page load, with no Play Store / App Store update.
 *
 *   - Android back button: back a page, or tuck the app away on the first page
 *   - Downloads: Android saves to Downloads natively (MainActivity); on iPhone, reports,
 *     payslips and backups open the share sheet (Save to Files, WhatsApp, Print…)
 *   - Print buttons → the phone's print dialog (AppPrint plugin)
 *   - Links that open a new tab: our pages open in place; other sites (WhatsApp, Maps, email…)
 *     open in the phone's browser or app
 *   - A short vibration when a clock-in / scan succeeds or is refused
 *   - "Update needed" screen when the installed app is older than APP_MIN_VERSION
 */
(function () {
  "use strict";

  function start(Cap) {
    if (window.__attendproBridge) return;
    window.__attendproBridge = true;
    var P = Cap.Plugins || {};
    var platform = Cap.getPlatform();              // "android" | "ios"
    document.documentElement.classList.add("in-app", "in-app-" + platform);

    // ── Small banner ───────────────────────────────────────────────────────────
    function banner(title, body) {
      var el = document.createElement("div");
      el.setAttribute("role", "status");
      el.style.cssText = "position:fixed;left:12px;right:12px;top:calc(env(safe-area-inset-top) + 12px);" +
        "z-index:2147483647;background:#0d1530;color:#f2f5fb;border-radius:14px;padding:12px 14px;" +
        "box-shadow:0 10px 30px rgba(0,0,0,.35);font:500 14px/1.35 system-ui,-apple-system,sans-serif;" +
        "transition:opacity .25s,transform .25s";
      var b = document.createElement("b");
      b.textContent = title || "";
      b.style.cssText = "display:block;color:#6ee7c0";
      el.appendChild(b);
      if (body) { var s = document.createElement("span"); s.textContent = body; el.appendChild(s); }
      document.body.appendChild(el);
      setTimeout(function () { el.style.opacity = "0"; el.style.transform = "translateY(-8px)"; }, 4000);
      setTimeout(function () { el.remove(); }, 4400);
      return el;
    }

    // ── Android back button ────────────────────────────────────────────────────
    if (platform === "android" && P.App) {
      P.App.addListener("backButton", function (e) {
        var open = document.querySelector(".selfie");      // close the selfie camera first
        if (open) { var c = open.querySelector("[data-cancel]"); if (c) { c.click(); return; } }
        if (document.body.classList.contains("nav-open")) { document.body.classList.remove("nav-open"); return; }
        if (e && e.canGoBack) history.back(); else P.App.minimizeApp();
      });
    }

    // ── Print buttons ──────────────────────────────────────────────────────────
    if (P.AppPrint) {
      window.print = function () { P.AppPrint.print({ name: document.title || "AttendPro" }); };
    }

    // ── Vibration on clock-in results (pages fire "attendpro:result") ──────────
    if (P.Haptics) {
      window.addEventListener("attendpro:result", function (e) {
        var d = (e && e.detail) || {};
        var type = !d.ok ? "ERROR" : d.action === "duplicate" ? "WARNING" : "SUCCESS";
        if (d.action === "need_selfie") return;
        P.Haptics.notification({ type: type }).catch(function () {});
      });
    }

    // ── Links ──────────────────────────────────────────────────────────────────
    var FILE_LINK = /(\.(pdf|xlsx?|csv|zip)(\?|#|$))|([?&]export=)|(\/download\/?)|(\/backups\/export\/?)|(\/payslips?\/\d+\/?)|(\/qr-print\/?)/i;

    function filenameFrom(res, url) {
      var cd = res.headers.get("Content-Disposition") || "";
      var m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i);
      if (m) return decodeURIComponent(m[1]).replace(/[\/\\]/g, "_");
      var last = new URL(url, location.href).pathname.split("/").filter(Boolean).pop() || "attendpro";
      var type = (res.headers.get("Content-Type") || "").split(";")[0];
      var ext = { "application/pdf": ".pdf", "text/csv": ".csv", "application/zip": ".zip",
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx" }[type] || "";
      return /\.[a-z0-9]{2,4}$/i.test(last) ? last : last + ext;
    }

    function blobToBase64(blob) {
      return new Promise(function (resolve, reject) {
        var r = new FileReader();
        r.onload = function () { resolve(String(r.result).split(",")[1]); };
        r.onerror = reject;
        r.readAsDataURL(blob);
      });
    }

    function shareDownload(url) {
      var note = banner("Preparing file…", "");
      return fetch(url, { credentials: "same-origin" }).then(function (res) {
        var type = res.headers.get("Content-Type") || "";
        var cd = res.headers.get("Content-Disposition") || "";
        if (!res.ok || (type.indexOf("text/html") === 0 && cd.indexOf("attachment") !== 0)) {
          note.remove();
          location.href = url;                       // an ordinary page after all (e.g. the print sheet)
          return;
        }
        var name = filenameFrom(res, url);
        return res.blob().then(blobToBase64).then(function (data) {
          return P.Filesystem.writeFile({ path: name, data: data, directory: "CACHE" });
        }).then(function (file) {
          note.remove();
          return P.Share.share({ title: name, files: [file.uri] });
        });
      }).catch(function (err) {
        note.remove();
        if (err && /cancel/i.test(String(err.message || err))) return;
        banner("Couldn't open the file", "Please try again.");
      });
    }

    function openOutside(url) {
      if (P.Browser && /^https?:/i.test(url)) P.Browser.open({ url: url }).catch(function () { location.href = url; });
      else location.href = url;                      // mailto:, tel:, whatsapp: → the phone's own app
    }

    document.addEventListener("click", function (e) {
      if (e.defaultPrevented || e.button !== 0) return;
      var a = e.target.closest && e.target.closest("a[href]");
      if (!a) return;
      var href = a.getAttribute("href");
      if (!href || href.charAt(0) === "#" || /^javascript:/i.test(href)) return;
      var u;
      try { u = new URL(a.href, location.href); } catch (err) { return; }
      var ours = u.origin === location.origin;
      if (ours && platform === "ios" && P.Filesystem && P.Share &&
          (a.hasAttribute("download") || FILE_LINK.test(u.pathname + u.search)) && !/qr-print/.test(u.pathname)) {
        e.preventDefault();
        shareDownload(u.href);
        return;
      }
      if (a.target === "_blank") {
        e.preventDefault();
        if (ours) location.href = u.href; else openOutside(u.href);
        return;
      }
      if (!ours && /^https?:$/.test(u.protocol) && !/paystack\.(com|co)$/i.test(u.hostname)) {
        e.preventDefault();
        openOutside(u.href);
      }
    }, false);

    // ── Update prompt ──────────────────────────────────────────────────────────
    function versionLess(a, b) {
      var x = String(a || "0").split("."), y = String(b || "0").split(".");
      for (var i = 0; i < Math.max(x.length, y.length); i++) {
        var p = parseInt(x[i] || 0, 10), q = parseInt(y[i] || 0, 10);
        if (p !== q) return p < q;
      }
      return false;
    }
    var session;
    try { session = window.sessionStorage; } catch (e) { session = null; }
    function checkVersion(cfg) {
      if (!P.App || !cfg || !cfg.min_version) return;
      P.App.getInfo().then(function (info) {
        if (!versionLess(info.version, cfg.min_version)) return;
        var url = platform === "ios" ? cfg.ios_url : cfg.android_url;
        var wrap = document.createElement("div");
        wrap.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:#0d1530;color:#f2f5fb;display:flex;" +
          "flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:32px;" +
          "font:400 16px/1.5 system-ui,-apple-system,sans-serif";
        wrap.innerHTML = '<div style="font-size:22px;font-weight:700;margin-bottom:8px">Update needed</div>' +
          '<div style="opacity:.75;max-width:320px;margin-bottom:24px">A newer version of AttendPro is available. ' +
          "Please update to keep using the app.</div>";
        if (url) {
          var a = document.createElement("a");
          a.href = url; a.textContent = "Update now";
          a.style.cssText = "background:#12b886;color:#fff;font-weight:700;padding:12px 28px;border-radius:12px;text-decoration:none";
          wrap.appendChild(a);
        }
        document.body.appendChild(wrap);
      }).catch(function () {});
    }
    if (!(session && session.getItem("attendproVersionChecked"))) {
      fetch("/app/config/", { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (cfg) { if (session) session.setItem("attendproVersionChecked", "1"); checkVersion(cfg); })
        .catch(function () {});
    }

    // Hide the splash screen as soon as the first page has drawn
    if (P.SplashScreen) P.SplashScreen.hide().catch(function () {});
  }

  // Capacitor's bridge is added by the app; wait briefly in case this runs first.
  var tries = 0;
  (function wait() {
    var Cap = window.Capacitor;
    if (Cap && Cap.isNativePlatform && Cap.isNativePlatform()) { start(Cap); return; }
    if (++tries < 40) setTimeout(wait, 50);
  })();
})();
