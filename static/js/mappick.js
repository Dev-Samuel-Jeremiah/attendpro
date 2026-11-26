/* "Pick on map": choose a site's location by placing a pin on a map (no GPS needed).
 * Used by Settings and Branches. Leaflet + OpenStreetMap / Esri satellite tiles, loaded on first use.
 *
 *   AttendPro.pickOnMap({ lat, lng, radius, start: {lat, lng, accuracy} }) → Promise<{lat, lng}> (rejects if cancelled)
 */
window.AttendPro = window.AttendPro || {};
(function () {
  "use strict";
  var LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
  var loading = null;

  function loadLeaflet() {
    if (window.L) return Promise.resolve();
    if (loading) return loading;
    loading = new Promise(function (resolve, reject) {
      var css = document.createElement("link"); css.rel = "stylesheet"; css.href = LEAFLET + "leaflet.css";
      document.head.appendChild(css);
      var js = document.createElement("script"); js.src = LEAFLET + "leaflet.js";
      js.onload = resolve; js.onerror = function () { loading = null; reject(new Error("map")); };
      document.head.appendChild(js);
    });
    return loading;
  }

  var CSS = ".mpk{position:fixed;inset:0;z-index:2147483500;background:#0a1128;display:flex;flex-direction:column;" +
    "font:15px/1.45 'Segoe UI',system-ui,-apple-system,Roboto,sans-serif}" +
    ".mpk-top{padding:calc(12px + env(safe-area-inset-top)) 14px 12px;background:#0d1530;color:#fff;display:flex;flex-direction:column;gap:10px}" +
    ".in-app-android .mpk-top{padding-top:12px}" +
    ".mpk-row{display:flex;align-items:center;gap:10px}.mpk-row b{flex:1;font-size:17px}" +
    ".mpk-x{border:0;background:rgba(255,255,255,.12);color:#fff;border-radius:99px;padding:7px 14px;font:inherit;font-weight:600;cursor:pointer}" +
    ".mpk-search{display:flex;gap:8px}.mpk-search input{flex:1;min-width:0;border:0;border-radius:12px;padding:11px 14px;font:inherit}" +
    ".mpk-search button{border:0;border-radius:12px;padding:0 16px;background:#20c997;color:#06231a;font:inherit;font-weight:700;cursor:pointer}" +
    ".mpk-hits{background:#fff;border-radius:12px;overflow:hidden;max-height:200px;overflow-y:auto}" +
    ".mpk-hits button{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid #eef0f6;background:#fff;padding:10px 14px;font:inherit;font-size:14px;color:#1a2036;cursor:pointer}" +
    ".mpk-map{flex:1;position:relative}#mpk-map{position:absolute;inset:0}" +
    ".mpk-pin{position:absolute;left:50%;top:50%;z-index:500;transform:translate(-50%,-100%);pointer-events:none;filter:drop-shadow(0 6px 8px rgba(0,0,0,.35))}" +
    ".mpk-layer{position:absolute;right:12px;top:12px;z-index:600;display:flex;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.2)}" +
    ".mpk-layer button{border:0;background:#fff;padding:8px 12px;font:inherit;font-size:13px;font-weight:600;color:#5a6277;cursor:pointer}" +
    ".mpk-layer button.on{background:#0d1530;color:#fff}" +
    ".mpk-tip{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);z-index:600;background:rgba(13,21,48,.88);color:#fff;" +
    "font-size:13px;padding:7px 14px;border-radius:99px;white-space:nowrap}" +
    ".mpk-bot{padding:12px 14px calc(12px + env(safe-area-inset-bottom));background:#fff;display:flex;flex-direction:column;gap:8px}" +
    ".mpk-coords{font-size:13px;color:#6b7489;text-align:center;font-variant-numeric:tabular-nums}" +
    ".mpk-use{border:0;border-radius:14px;padding:15px;background:#12b886;color:#fff;font:inherit;font-weight:700;font-size:16px;cursor:pointer}";

  AttendPro.pickOnMap = function (opts) {
    opts = opts || {};
    return new Promise(function (resolve, reject) {
      if (!document.getElementById("mpk-css")) {
        var st = document.createElement("style"); st.id = "mpk-css"; st.textContent = CSS; document.head.appendChild(st);
      }
      var w = document.createElement("div"); w.className = "mpk"; w.setAttribute("role", "dialog"); w.setAttribute("aria-modal", "true");
      w.innerHTML =
        '<div class="mpk-top"><div class="mpk-row"><b>Pick your location</b><button type="button" class="mpk-x">Cancel</button></div>' +
        '<form class="mpk-search"><input type="search" placeholder="Search a place, street or area…" aria-label="Search a place"><button>Search</button></form>' +
        '<div class="mpk-hits" hidden></div></div>' +
        '<div class="mpk-map"><div id="mpk-map"></div>' +
        '<svg class="mpk-pin" width="38" height="50" viewBox="0 0 38 50"><path d="M19 0C8.5 0 0 8.4 0 18.8 0 32.9 19 50 19 50s19-17.1 19-31.2C38 8.4 29.5 0 19 0z" fill="#12b886"/><circle cx="19" cy="18.5" r="7" fill="#fff"/></svg>' +
        '<div class="mpk-layer"><button type="button" data-l="sat" class="on">Satellite</button><button type="button" data-l="map">Map</button></div>' +
        '<div class="mpk-tip">Move the map so the pin sits on your building</div></div>' +
        '<div class="mpk-bot"><div class="mpk-coords">Loading map…</div><button type="button" class="mpk-use">Use this spot</button></div>';
      document.body.appendChild(w);
      var $ = function (s) { return w.querySelector(s); };
      function close() { w.remove(); }
      $(".mpk-x").onclick = function () { close(); reject(new Error("cancelled")); };

      loadLeaflet().then(function () {
        var L = window.L;
        var has = opts.lat && opts.lng;
        var c = has ? [opts.lat, opts.lng] : opts.start ? [opts.start.lat, opts.start.lng] : [9.0765, 7.3986];
        var zoom = has ? 18 : opts.start ? (opts.start.accuracy > 300 ? 16 : 17) : 6;
        var map = L.map("mpk-map", { zoomControl: true, attributionControl: true }).setView(c, zoom);
        var street = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
          { maxZoom: 19, attribution: "© OpenStreetMap" });
        var sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
          { maxZoom: 19, attribution: "Imagery © Esri" });
        var labels = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
          { maxZoom: 19 });
        sat.addTo(map); labels.addTo(map);   // satellite first: easiest way to find your own roof
        var circle = opts.radius ? L.circle(c, { radius: opts.radius, color: "#12b886", weight: 2, fillOpacity: .12 }).addTo(map) : null;
        function update() {
          var p = map.getCenter();
          if (circle) circle.setLatLng(p);
          $(".mpk-coords").textContent = p.lat.toFixed(6) + ", " + p.lng.toFixed(6) +
            (opts.radius ? " · circle shows the " + opts.radius + " m allowed distance" : "");
        }
        map.on("move", update); update();
        w.querySelectorAll("[data-l]").forEach(function (b) {
          b.onclick = function () {
            w.querySelectorAll("[data-l]").forEach(function (x) { x.classList.toggle("on", x === b); });
            if (b.dataset.l === "sat") { map.removeLayer(street); sat.addTo(map); labels.addTo(map); }
            else { map.removeLayer(sat); map.removeLayer(labels); street.addTo(map); }
          };
        });
        $(".mpk-search").onsubmit = function (e) {
          e.preventDefault();
          var q = $(".mpk-search input").value.trim(), hits = $(".mpk-hits");
          if (!q) return;
          hits.hidden = false; hits.innerHTML = '<button type="button" disabled>Searching…</button>';
          fetch("https://nominatim.openstreetmap.org/search?format=json&limit=6&countrycodes=ng&q=" + encodeURIComponent(q),
                { headers: { "Accept-Language": "en" } })
            .then(function (r) { return r.json(); })
            .then(function (list) {
              hits.innerHTML = "";
              if (!list.length) { hits.innerHTML = '<button type="button" disabled>No places found. Try a nearby landmark or area.</button>'; return; }
              list.forEach(function (it) {
                var b = document.createElement("button"); b.type = "button"; b.textContent = it.display_name;
                b.onclick = function () { map.setView([+it.lat, +it.lon], 17); hits.hidden = true; };
                hits.appendChild(b);
              });
            }).catch(function () { hits.innerHTML = '<button type="button" disabled>Search isn\'t available right now.</button>'; });
        };
        $(".mpk-use").onclick = function () { var p = map.getCenter(); close(); resolve({ lat: p.lat, lng: p.lng }); };
        setTimeout(function () { map.invalidateSize(); }, 200);
      }).catch(function () {
        $(".mpk-coords").textContent = "The map couldn't load. Check your internet connection and try again.";
      });
    });
  };
})();
