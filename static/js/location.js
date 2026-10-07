/* Location tracking for staff and supervisors.
 *
 * The phone reports its position; the server decides ON / NEAR / OFF and this
 * page only shows what the server says. Updates go out at most every 30
 * seconds (the server refuses more than one per 10 seconds).
 */
(function () {
  "use strict";

  var card = document.getElementById("location-card");
  if (!card) return;

  var SEND_EVERY_MS = 30000;
  var STALE_FIX_MS = 120000;

  var els = {
    toggle: document.getElementById("loc-toggle"),
    msg: document.getElementById("loc-msg"),
    status: document.getElementById("loc-status"),
    label: document.getElementById("loc-status-label"),
    text: document.getElementById("loc-status-text"),
    details: document.getElementById("loc-details"),
    required: document.getElementById("loc-required"),
  };
  var state = JSON.parse(document.getElementById("location-state").textContent);
  var watchId = null;
  var timer = null;
  var latest = null;       // newest position from the phone
  var lastSentAt = 0;      // timestamp of the newest position sent
  var wakeLock = null;
  var busy = false;

  function say(text, kind) {
    els.msg.textContent = text || "";
    els.msg.className = "loc-msg" + (kind ? " " + kind : "");
  }

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function timeOf(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function render(s) {
    state = s;
    els.status.className = "loc-status s-" + s.status;
    els.label.textContent = s.status_label;
    els.text.textContent = s.status_text;
    var bits = [];
    if (s.distance_m !== null && s.distance_m !== undefined) bits.push(s.distance_m + " m from your site");
    if (s.accuracy_m !== null && s.accuracy_m !== undefined) bits.push("GPS accuracy ±" + s.accuracy_m + " m");
    if (s.last_update) bits.push("last sent " + timeOf(s.last_update));
    els.details.textContent = bits.join(" · ");
    els.toggle.textContent = s.tracking_on ? "Turn off location" : "Turn on location";
    els.toggle.dataset.on = s.tracking_on ? "1" : "0";
    els.toggle.classList.toggle("secondary", !!s.tracking_on);
    els.required.hidden = !s.tracking_required;
  }

  // Calls the server. Resolves with the JSON body, or null when the problem was already shown.
  function call(url, body) {
    var opts = { method: body === undefined ? "GET" : "POST", credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.headers["X-CSRFToken"] = csrfToken();
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(
      function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (r.ok) return data;
          if (r.status === 401 || r.status === 403) {
            stopWatching();
            say("Your session has expired. Please sign in again to keep sharing your location.", "error");
            return null;
          }
          if (r.status === 429) return null; // too soon; the next update will go through
          say(data.error || "The server could not accept your location. It will try again.", "error");
          return null;
        });
      },
      function () {
        say("No internet connection. Your location will be sent when the connection returns.", "error");
        return null;
      }
    );
  }

  function explainError(err) {
    if (err.code === 1) {
      return "Location access is blocked. Please allow location for this website in your browser or phone settings, then press Turn on location again.";
    }
    if (err.code === 2) {
      return "Your phone cannot find your location. Check that the phone's location (GPS) is switched on and move to an open area.";
    }
    return "Still looking for your location. This can take a minute.";
  }

  function send(force) {
    if (!latest || !state.tracking_on) return;
    if (!force && latest.timestamp <= lastSentAt) return;
    var pos = latest;
    call(card.dataset.update, {
      latitude: pos.coords.latitude,
      longitude: pos.coords.longitude,
      accuracy: pos.coords.accuracy,
      timestamp: pos.timestamp,
    }).then(function (data) {
      if (!data) return;
      lastSentAt = pos.timestamp;
      render(data);
      if (!els.msg.classList.contains("ok")) say("Your location is being shared.", "ok");
    });
  }

  function onPosition(pos) {
    var first = latest === null;
    latest = pos;
    if (first) send(true);
  }

  function onPositionError(err) {
    say(explainError(err), "error");
    if (err.code === 1) {
      // Permission was taken away while tracking: tell the server so the manager sees it.
      stopWatching();
      call(card.dataset.stop, {}).then(function (data) { if (data) render(data); });
    }
  }

  function tick() {
    if (latest && Date.now() - latest.timestamp > STALE_FIX_MS) {
      // The phone has stopped giving fresh readings; ask for one directly.
      navigator.geolocation.getCurrentPosition(function (p) { latest = p; send(); }, onPositionError,
        { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 });
      return;
    }
    send();
  }

  function keepScreenOn() {
    if (!("wakeLock" in navigator) || wakeLock) return;
    navigator.wakeLock.request("screen").then(function (lock) {
      wakeLock = lock;
      lock.addEventListener("release", function () { wakeLock = null; });
    }).catch(function () { /* not allowed right now (battery saver, hidden page) */ });
  }

  function startWatching() {
    if (watchId !== null) return;
    watchId = navigator.geolocation.watchPosition(onPosition, onPositionError,
      { enableHighAccuracy: true, timeout: 30000, maximumAge: 10000 });
    timer = setInterval(tick, SEND_EVERY_MS);
    keepScreenOn();
  }

  function stopWatching() {
    if (watchId !== null) navigator.geolocation.clearWatch(watchId);
    if (timer) clearInterval(timer);
    watchId = timer = null;
    latest = null;
    if (wakeLock) wakeLock.release();
  }

  function canUseGps() {
    if (!("geolocation" in navigator)) {
      say("This browser cannot share location. Please use Chrome or Safari on your phone.", "error");
      return false;
    }
    if (!window.isSecureContext) {
      say("Location only works on a secure (https://) connection. Please tell your manager.", "error");
      return false;
    }
    return true;
  }

  function turnOn() {
    if (!canUseGps()) return;
    busy = true;
    els.toggle.disabled = true;
    say("Your phone will ask to share your location. Please press Allow.", "info");
    navigator.geolocation.getCurrentPosition(
      function (pos) {
        call(card.dataset.start, {}).then(function (data) {
          busy = false;
          els.toggle.disabled = false;
          if (!data) return;
          render(data);
          say("Your location is now being shared.", "ok");
          latest = pos;
          send(true);
          startWatching();
        });
      },
      function (err) {
        busy = false;
        els.toggle.disabled = false;
        say(explainError(err), "error");
      },
      { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 }
    );
  }

  function turnOff() {
    stopWatching();
    els.toggle.disabled = true;
    call(card.dataset.stop, {}).then(function (data) {
      els.toggle.disabled = false;
      if (!data) return;
      render(data);
      say(data.working_now
        ? "Location tracking has been turned off. Please turn it back on while you are working."
        : "Location sharing is now off.", data.working_now ? "error" : "ok");
    });
  }

  els.toggle.addEventListener("click", function () {
    if (busy) return;
    if (els.toggle.dataset.on === "1") turnOff(); else turnOn();
  });

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && state.tracking_on) {
      keepScreenOn();
      tick();
    }
  });

  if (navigator.permissions && navigator.permissions.query) {
    navigator.permissions.query({ name: "geolocation" }).then(function (p) {
      p.onchange = function () {
        if (p.state === "denied" && state.tracking_on) onPositionError({ code: 1 });
      };
    }).catch(function () {});
  }

  // Keep the reminder and status fresh even when not moving (e.g. a shift starts).
  setInterval(function () {
    if (watchId === null) call(card.dataset.me).then(function (data) { if (data) render(data); });
  }, 60000);

  render(state);
  if (state.tracking_on && canUseGps()) {
    // Tracking was left on (page reloaded or reopened): carry on without asking again.
    say("Resuming location sharing...", "info");
    startWatching();
  }
})();
