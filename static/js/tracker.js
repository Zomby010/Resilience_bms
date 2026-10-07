/* Manager GPS Tracker: refreshes every 15 seconds from the server. */
(function () {
  "use strict";

  var root = document.getElementById("tracker");
  if (!root) return;
  var REFRESH_MS = 15000;
  var COLORS = { on: "#15803d", near: "#f59e0b", off: "#d10012", weak: "#64748b", lost: "#334155", waiting: "#1d4ed8" };

  var map = null, siteLayer = null, peopleLayer = null, fitted = false;
  if (window.L) {
    map = L.map("trk-map", { scrollWheelZoom: false }).setView([-0.0917, 34.768], 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      // OpenStreetMap refuses tile requests without a Referer, and Django sends
      // "Referrer-Policy: same-origin" by default, so allow the site's origin here.
      referrerPolicy: "strict-origin-when-cross-origin",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    siteLayer = L.layerGroup().addTo(map);
    peopleLayer = L.layerGroup().addTo(map);
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function time(iso) {
    if (!iso) return "never";
    var d = new Date(iso), now = new Date();
    var t = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return d.toDateString() === now.toDateString() ? t : d.toLocaleDateString([], { day: "numeric", month: "short" }) + " " + t;
  }

  function personLink(id, name) {
    var a = el("a", null, name);
    a.href = root.dataset.personUrl.replace("/0/", "/" + id + "/");
    return a;
  }

  function render(data) {
    Object.keys(data.counts).forEach(function (k) {
      var n = document.getElementById("c-" + k);
      if (n) n.textContent = data.counts[k];
    });

    var alerts = document.getElementById("trk-alerts");
    alerts.replaceChildren();
    if (!data.alerts.length) alerts.appendChild(el("li", "muted", "No alerts. Everyone expected at work is sharing their location."));
    data.alerts.forEach(function (a) {
      var li = el("li", "alert-item k-" + a.kind);
      li.appendChild(el("span", null, a.message + " "));
      li.appendChild(el("span", "muted small", "since " + time(a.since) + " "));
      var link = personLink(a.user_id, "View");
      link.className = "small";
      li.appendChild(link);
      alerts.appendChild(li);
    });

    var rows = document.getElementById("trk-rows");
    rows.replaceChildren();
    if (!data.people.length) {
      var tr = el("tr"), td = el("td", "empty", "No staff or supervisors yet.");
      td.colSpan = 7; tr.appendChild(td); rows.appendChild(tr);
    }
    data.people.forEach(function (p) {
      var tr = el("tr");
      var name = el("td"); name.appendChild(personLink(p.id, p.name)); tr.appendChild(name);
      tr.appendChild(el("td", null, p.role));
      tr.appendChild(el("td", null, p.site || "-"));
      var st = el("td"); var badge = el("span", "badge loc s-" + p.status, p.status_label);
      badge.title = p.status_help; st.appendChild(badge);
      if (p.accuracy_m !== null && p.tracking_on && p.status !== "tracking_off") st.appendChild(el("div", "muted small", "GPS ±" + p.accuracy_m + " m"));
      tr.appendChild(st);
      tr.appendChild(el("td", null, p.online ? "Online" : "Offline"));
      tr.appendChild(el("td", "num", p.distance_m !== null && p.tracking_on ? p.distance_m + " m" : "-"));
      tr.appendChild(el("td", null, time(p.last_update)));
      rows.appendChild(tr);
    });

    if (map) {
      siteLayer.clearLayers();
      peopleLayer.clearLayers();
      var bounds = [];
      data.sites.forEach(function (s) {
        var c = [s.latitude, s.longitude];
        L.circle(c, { radius: 50, color: "#f59e0b", weight: 1, fillOpacity: 0.05 }).addTo(siteLayer);
        L.circle(c, { radius: s.radius_m, color: "#15803d", weight: 2, fillOpacity: 0.15 })
          .bindTooltip(s.name, { permanent: true, direction: "top" }).addTo(siteLayer);
        bounds.push(c);
      });
      data.people.forEach(function (p) {
        if (p.latitude === null || p.status === "lost") return;
        var c = [p.latitude, p.longitude];
        var pop = el("div");
        pop.appendChild(el("strong", null, p.name));
        pop.appendChild(el("div", null, p.status_label + (p.distance_m !== null ? ", " + p.distance_m + " m from " + (p.site || "site") : "")));
        pop.appendChild(el("div", null, "Updated " + time(p.last_update)));
        L.circleMarker(c, { radius: 9, color: "#fff", weight: 2, fillColor: COLORS[p.status] || "#64748b", fillOpacity: 1 })
          .bindPopup(pop).addTo(peopleLayer);
        bounds.push(c);
      });
      if (!fitted && bounds.length) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
        fitted = true;
      }
    }
    document.getElementById("trk-updated").textContent = "Updated " + time(data.now);
  }

  function refresh() {
    if (document.hidden) return;
    fetch(root.dataset.url, { credentials: "same-origin" })
      .then(function (r) {
        if (r.status === 401) { window.location.reload(); return null; }
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (data) render(data);
        else document.getElementById("trk-updated").textContent = "Could not refresh. Retrying...";
      })
      .catch(function () {
        document.getElementById("trk-updated").textContent = "No connection. Retrying...";
      });
  }

  render(JSON.parse(document.getElementById("tracker-data").textContent));
  setInterval(refresh, REFRESH_MS);
})();
