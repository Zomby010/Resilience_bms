/* Attendance sign-in. The phone sends one position; the server decides if the person is at their site. */
(function () {
  "use strict";

  var btn = document.getElementById("sign-in-btn");
  if (!btn) return;
  var msg = document.getElementById("sign-in-msg");

  function say(text, kind) {
    msg.textContent = text;
    msg.className = "loc-msg" + (kind ? " " + kind : "");
  }

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function send(pos) {
    say("Checking that you are at your site...");
    fetch(btn.dataset.url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify({
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        timestamp: pos.timestamp
      })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (r.ok) {
          say(data.message || "Signed in.", "ok");
          btn.hidden = true;
          setTimeout(function () { window.location.reload(); }, 2500);
        } else if (r.status === 401 || r.status === 403) {
          say("Your session has expired. Please sign in to the system again.", "error");
          btn.disabled = false;
        } else {
          say(data.error || "Could not sign you in. Please try again.", "error");
          btn.disabled = false;
        }
      });
    }).catch(function () {
      say("No internet connection. Please try again.", "error");
      btn.disabled = false;
    });
  }

  btn.addEventListener("click", function () {
    if (!navigator.geolocation) {
      say("This phone cannot share its location. Ask your supervisor to mark you present.", "error");
      return;
    }
    btn.disabled = true;
    say("Finding your location. Please wait...");
    navigator.geolocation.getCurrentPosition(send, function (err) {
      btn.disabled = false;
      if (err.code === err.PERMISSION_DENIED) {
        say("Location is blocked. Allow location for this site in your browser settings, then try again.", "error");
      } else {
        say("Could not find your location. Go outside and try again.", "error");
      }
    }, { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 });
  });
})();
