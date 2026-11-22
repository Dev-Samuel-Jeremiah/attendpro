/* Shared by the QR scanner and the scan confirmation page: ask the browser for a GPS fix.
   AttendPro.locate() resolves to {lat, lng, accuracy} or rejects with {title, message}. */
window.AttendPro = window.AttendPro || {};
AttendPro.locate = function (timeoutMs) {
  return new Promise(function (resolve, reject) {
    if (!navigator.geolocation) {
      reject({title: "Location not supported", message: "This browser can't share your location. Try Chrome or Safari on your phone."});
      return;
    }
    navigator.geolocation.getCurrentPosition(function (pos) {
      resolve({lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy});
    }, function (err) {
      reject(err.code === 1
        ? {title: "Location permission needed", message: "Allow location access for this site in your browser settings, then try again."}
        : {title: "Couldn't get your location", message: "Turn on location (GPS), move near a window or outside, and try again."});
    }, {enableHighAccuracy: true, timeout: timeoutMs || 20000, maximumAge: 15000});
  });
};
