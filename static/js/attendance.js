/* Attendance sign-in and sign-out. The phone sends one position; the server decides.
   When the location fails or is refused, the "Location not working?" form opens (ATT-01). */
(function () {
  "use strict";

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function say(msg, text, kind) {
    msg.textContent = text;
    msg.className = "loc-msg" + (kind ? " " + kind : "");
  }

  function openFallback(box) {
    var d = box && box.querySelector("[data-no-loc]");
    if (d) { d.open = true; }
  }

  function post(btn, msg, box, pos, checking) {
    say(msg, checking);
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
          say(msg, data.message || "Done.", "ok");
          btn.hidden = true;
          setTimeout(function () { window.location.reload(); }, 2500);
        } else if (r.status === 401 || r.status === 403) {
          say(msg, "Your session has expired. Please log in again.", "error");
          btn.disabled = false;
        } else {
          say(msg, data.error || "That did not work. Please try again.", "error");
          btn.disabled = false;
          openFallback(box);
        }
      });
    }).catch(function () {
      say(msg, "No internet connection. Please try again.", "error");
      btn.disabled = false;
    });
  }

  function wire(btn, msg, box, checking) {
    btn.addEventListener("click", function () {
      if (!navigator.geolocation) {
        say(msg, "This phone cannot share its location. Use the button below instead.", "error");
        openFallback(box);
        return;
      }
      btn.disabled = true;
      say(msg, "Finding your location. Please wait...");
      navigator.geolocation.getCurrentPosition(function (pos) {
        post(btn, msg, box, pos, checking);
      }, function (err) {
        btn.disabled = false;
        if (err.code === err.PERMISSION_DENIED) {
          say(msg, "Location is blocked. Allow it in your browser settings, or use the button below.", "error");
        } else {
          say(msg, "Could not find your location. Go outside and try again, or use the button below.", "error");
        }
        openFallback(box);
      }, { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 });
    });
  }

  var signIn = document.getElementById("sign-in-btn");
  if (signIn) {
    wire(signIn, document.getElementById("sign-in-msg"), signIn.parentNode, "Checking that you are at your site...");
  }
  Array.prototype.forEach.call(document.querySelectorAll(".js-sign-out"), function (btn) {
    var box = btn.closest("[data-sign-out]");
    wire(btn, box.querySelector(".loc-msg"), box, "Signing you out...");
  });
})();
