/* Precise location for clock-in, QR scans and setting a site's position.
 *
 * Phones usually answer a location request first with a rough, network-based fix (±500 m or worse)
 * and only reach GPS accuracy a few seconds later. So instead of taking the first answer, this
 * WATCHES the position with high accuracy and no cached readings, keeps the most precise one, and
 * finishes as soon as it is precise enough (or when time runs out, with the best it got).
 *
 * Inside the AttendPro Android / iPhone app it uses the native GPS (Capacitor Geolocation:
 * Android's fused provider / iOS Core Location) and spots "Approximate location only".
 *
 *   AttendPro.locate({ target: 25, maxWait: 25000, onProgress: (accuracy, seconds) => {} })
 *     → Promise<{ lat, lng, accuracy }>   or rejects with { title, message }
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

  function permissionError() {
    return { title: "Location permission needed",
             message: (inApp ? "AttendPro needs your location to confirm you're at work. " : "Allow location for this site, then try again. ") + preciseHelp() };
  }

  function nativeGeo() {
    var Cap = window.Capacitor;
    return Cap && Cap.isNativePlatform && Cap.isNativePlatform() && Cap.Plugins && Cap.Plugins.Geolocation;
  }

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
      var best = null, done = false, stop = function () {}, timer;

      function finish(err) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        try { stop(); } catch (e) { /* already stopped */ }
        if (best) resolve(best); else reject(err || {
          title: "Couldn't get your location",
          message: "Turn on location (GPS), step near a window or outside, and try again. " + preciseHelp() });
      }

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

      function failed(code) {
        if (code === 1) { done = true; clearTimeout(timer); try { stop(); } catch (e) {} reject(permissionError()); }
        // Other errors (no fix yet / timeout): keep waiting until the deadline.
      }

      timer = setTimeout(function () { finish(); }, maxWait);
      setTimeout(function () { if (!done && best && best.accuracy <= goodEnough) finish(); }, patience);

      var G = nativeGeo();
      if (G) {
        // Native GPS in the app. Spot "Approximate location" on Android 12+ (coarse only).
        G.checkPermissions().then(function (p) {
          if (p.location === "granted") return p;
          return G.requestPermissions({ permissions: ["location", "coarseLocation"] });
        }).then(function (p) {
          if (p.location !== "granted") {
            done = true; clearTimeout(timer);
            if (p.coarseLocation === "granted") {
              reject({ title: "Precise location is off",
                       message: "AttendPro only has your approximate location, which can't confirm you're at work. " + preciseHelp() });
            } else reject(permissionError());
            return;
          }
          return G.watchPosition({ enableHighAccuracy: true, timeout: maxWait, maximumAge: 0 }, function (pos, err) {
            if (err) {
              var why = String(err.message || err);
              if (/denied|permission/i.test(why)) failed(1);
              else if (/disabled|services? (are |is )?(off|not enabled)/i.test(why) && !best) {
                done = true; clearTimeout(timer); try { stop(); } catch (e) {}
                reject({ title: "Location is turned off",
                         message: "Turn on Location on your phone (swipe down from the top of the screen and tap Location), then try again." });
              }
              return;
            }
            if (pos) reading(pos.coords, pos.timestamp);
          }).then(function (id) {
            stop = function () { G.clearWatch({ id: id }); };
            if (done) stop();
          });
        }).catch(function () { useBrowser(); });
      } else {
        useBrowser();
      }

      function useBrowser() {
        if (done) return;
        if (!navigator.geolocation) {
          done = true; clearTimeout(timer);
          reject({ title: "Location not supported", message: "This browser can't share your location. Try Chrome or Safari on your phone." });
          return;
        }
        var id = navigator.geolocation.watchPosition(
          function (pos) { reading(pos.coords, pos.timestamp); },
          function (err) { failed(err && err.code); },
          { enableHighAccuracy: true, timeout: maxWait, maximumAge: 0 });
        stop = function () { navigator.geolocation.clearWatch(id); };
        if (done) stop();
      }
    });
  };
})();
