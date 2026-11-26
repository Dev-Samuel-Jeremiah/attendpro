/* Setting where a site is (Settings → attendance location, Branches): "Use my current location"
 * or "Pick on map". A rough reading would put the pin on a phone mast instead of the building and
 * then refuse everyone's clock-in, so readings worse than ±MAX_M are not used. */
window.AttendPro = window.AttendPro || {};
(function () {
  "use strict";
  var MAX_M = 100;

  AttendPro.siteLocation = function (o) {
    var $ = function (id) { return document.getElementById(id); };
    var lat = $(o.lat), lng = $(o.lng), radius = $(o.radius), mapLink = $(o.mapLink), status = $(o.status);
    var useBtn = $(o.use), pickBtn = $(o.pick);
    function updateMap() {
      if (lat.value && lng.value) { mapLink.href = "https://www.google.com/maps?q=" + lat.value + "," + lng.value; mapLink.hidden = false; }
    }
    function fill(p, how) {
      lat.value = (+p.lat).toFixed(6); lng.value = (+p.lng).toFixed(6); updateMap();
      lat.dispatchEvent(new Event("change"));
      status.textContent = how + " Click " + o.saveLabel + " to keep it.";
    }
    function pick(start) {
      AttendPro.pickOnMap({ lat: parseFloat(lat.value) || null, lng: parseFloat(lng.value) || null,
                            radius: parseInt(radius && radius.value, 10) || null, start: start })
        .then(function (p) { fill(p, "Location set from the map."); }, function () {});
    }
    lat.addEventListener("change", updateMap); lng.addEventListener("change", updateMap);
    pickBtn.addEventListener("click", function () { pick(null); });

    useBtn.addEventListener("click", function () {
      status.textContent = "Getting your location…";
      AttendPro.locate({ target: 15, goodEnough: 30, patience: 15000, maxWait: 45000, onProgress: function (acc, secs) {
        status.textContent = acc > MAX_M && secs >= 12
          ? "Still rough (±" + acc + " m). Turn on Wi-Fi, or step outside…" : "Getting a precise location… (±" + acc + " m)";
      } }).then(function (p) {
        var acc = Math.round(p.accuracy);
        if (p.accuracy > MAX_M) {
          status.textContent = "Your phone could only place you within " + acc + " m, which is too rough. Nothing was changed.";
          AttendPro.locationHelp({ kind: "imprecise", title: "Too rough to set your location (±" + acc + " m)",
            message: "Setting your workplace needs a precise location, or the pin may land on a nearby phone mast instead of your building. " +
                     "Pick the spot on the map instead, or improve your phone's location and try again." },
            function () { useBtn.click(); }, { label: "Pick on map instead", run: function () { pick(p); } });
          return;
        }
        fill(p, "Location filled in (accurate to about " + acc + " m).");
      }, function (e) {
        status.textContent = e.message;
        AttendPro.locationHelp(e, function () { useBtn.click(); }, { label: "Pick on map instead", run: function () { pick(null); } });
      });
    });
    AttendPro.warmUp(180);   // start finding GPS now, so the button is quicker
  };
})();
