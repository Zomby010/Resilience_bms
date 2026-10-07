/* Site location picker: click the map to fill in latitude and longitude. */
(function () {
  "use strict";
  var box = document.getElementById("site-map");
  if (!box || !window.L) return;
  var latIn = document.getElementById(box.dataset.latInput);
  var lngIn = document.getElementById(box.dataset.lngInput);
  var radiusIn = document.getElementById(box.dataset.radiusInput);
  var msg = document.getElementById("map-msg");

  var map = L.map(box).setView([-0.0917, 34.768], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  var marker = null, inner = null, outer = null;

  function current() {
    var lat = parseFloat(latIn.value), lng = parseFloat(lngIn.value);
    return isFinite(lat) && isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? [lat, lng] : null;
  }

  function draw(pan) {
    var c = current();
    [marker, inner, outer].forEach(function (l) { if (l) map.removeLayer(l); });
    marker = inner = outer = null;
    if (!c) return;
    var r = parseInt(radiusIn.value, 10) || 30;
    outer = L.circle(c, { radius: 50, color: "#f59e0b", weight: 1, fillOpacity: 0.05 }).addTo(map);
    inner = L.circle(c, { radius: r, color: "#15803d", weight: 2, fillOpacity: 0.15 }).addTo(map);
    marker = L.marker(c).addTo(map);
    if (pan) map.setView(c, Math.max(map.getZoom(), 17));
  }

  function set(lat, lng) {
    latIn.value = lat.toFixed(6);
    lngIn.value = lng.toFixed(6);
    draw(false);
  }

  map.on("click", function (e) { set(e.latlng.lat, e.latlng.lng); });
  [latIn, lngIn, radiusIn].forEach(function (i) { i.addEventListener("change", function () { draw(true); }); });

  document.getElementById("use-my-location").addEventListener("click", function () {
    if (!navigator.geolocation || !window.isSecureContext) {
      msg.textContent = "Your browser cannot share location here. Click the map instead.";
      return;
    }
    msg.textContent = "Finding your location...";
    navigator.geolocation.getCurrentPosition(function (p) {
      set(p.coords.latitude, p.coords.longitude);
      map.setView([p.coords.latitude, p.coords.longitude], 18);
      msg.textContent = "Done. GPS accuracy ±" + Math.round(p.coords.accuracy) + " m. Adjust by clicking the map if needed.";
    }, function () {
      msg.textContent = "Could not get your location. Click the map instead.";
    }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
  });

  draw(true);
})();
