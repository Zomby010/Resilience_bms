// Collapsible sections (<details class="fold" data-fold="key">) remember whether they were open, per page.
(function () {
  var page = location.pathname;
  document.querySelectorAll("details.fold[data-fold]").forEach(function (d) {
    var key = "fold:" + page + ":" + d.getAttribute("data-fold");
    try {
      var saved = sessionStorage.getItem(key);
      if (saved === "1") d.open = true;
      if (saved === "0") d.open = false;
    } catch (e) { /* storage blocked */ }
    d.addEventListener("toggle", function () {
      try { sessionStorage.setItem(key, d.open ? "1" : "0"); } catch (e) { /* storage blocked */ }
    });
  });
})();
