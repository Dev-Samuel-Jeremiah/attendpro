/* Front-camera selfie for face verification. AttendPro.selfie() resolves to a JPEG data URL,
   or rejects with {title, message}. The camera is switched off as soon as the photo is taken. */
window.AttendPro = window.AttendPro || {};
AttendPro.selfie = function () {
  return new Promise(function (resolve, reject) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.isSecureContext) {
      reject({title: "Camera not available", message: "This browser can't open the camera here. Use Chrome or Safari on your phone."});
      return;
    }
    const wrap = document.createElement("div");
    wrap.className = "selfie";
    wrap.innerHTML =
      '<div class="selfie-box" role="dialog" aria-modal="true" aria-label="Take a selfie">' +
      '<p class="selfie-title">Take a selfie</p>' +
      '<div class="selfie-frame"><video playsinline muted autoplay></video><div class="selfie-oval"></div></div>' +
      '<p class="selfie-hint">Face a light, keep your whole face inside the oval, then tap the button.</p>' +
      '<div class="selfie-actions"><button type="button" class="btn btn-ghost" data-cancel>Cancel</button>' +
      '<button type="button" class="btn btn-accent" data-snap disabled>Take selfie</button></div></div>';
    document.body.appendChild(wrap);
    const video = wrap.querySelector("video"), snap = wrap.querySelector("[data-snap]");
    let stream = null;
    function close() { if (stream) stream.getTracks().forEach(t => t.stop()); wrap.remove(); }
    navigator.mediaDevices.getUserMedia({video: {facingMode: "user", width: {ideal: 720}, height: {ideal: 720}}, audio: false})
      .then(function (s) { stream = s; video.srcObject = s; snap.disabled = false; snap.focus(); })
      .catch(function (err) {
        close();
        reject(err && err.name === "NotAllowedError"
          ? {title: "Camera permission needed", message: "Allow camera access for this site in your browser settings, then try again."}
          : {title: "Couldn't open the camera", message: "Close other apps using the camera and try again."});
      });
    snap.addEventListener("click", function () {
      const w = video.videoWidth, h = video.videoHeight;
      if (!w || !h) return;
      const scale = Math.min(1, 720 / Math.max(w, h));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(w * scale); canvas.height = Math.round(h * scale);
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      const url = canvas.toDataURL("image/jpeg", 0.86);
      close();
      resolve(url);
    });
    wrap.querySelector("[data-cancel]").addEventListener("click", function () {
      close();
      reject({title: "Selfie cancelled", message: "Your attendance wasn't recorded. Tap again when you're ready.", cancelled: true});
    });
  });
};

/* Post JSON; if the server asks for a selfie, take one and send the same request again. */
AttendPro.postWithSelfie = async function (url, body, csrf, onSelfie) {
  async function send(b) {
    const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrf},
                                body: JSON.stringify(b)});
    return r.json();
  }
  let d = await send(body);
  if (d.action === "need_selfie") {
    if (onSelfie) onSelfie();
    let photo;
    try { photo = await AttendPro.selfie(); }
    catch (e) { return {ok: false, action: "rejected", title: e.title, message: e.message}; }
    d = await send(Object.assign({}, body, {selfie: photo}));
  }
  return d;
};
