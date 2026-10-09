// Phone menu: the bottom bar's "More" button opens the full menu as a sheet that slides over the page.
(function () {
  var sheet = document.getElementById("sidebar");
  var more = document.querySelector(".tabbar .more-btn");
  var close = sheet && sheet.querySelector(".sheet-close");
  if (!sheet || !more) return;
  function set(open) {
    sheet.classList.toggle("open", open);
    document.body.classList.toggle("sheet-open", open);
    more.setAttribute("aria-expanded", open ? "true" : "false");
    if (close) close.hidden = !open;
    if (open) { var first = sheet.querySelector("a, summary, button"); if (first) first.focus(); }
    else more.focus();
  }
  more.addEventListener("click", function () { set(!sheet.classList.contains("open")); });
  if (close) close.addEventListener("click", function () { set(false); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && sheet.classList.contains("open")) set(false);
  });
})();

// Menu groups: opening one closes the others, so only one group is open at a time.
(function () {
  var groups = document.querySelectorAll(".nav details.navgroup");
  groups.forEach(function (g) {
    g.addEventListener("toggle", function () {
      if (!g.open) return;
      groups.forEach(function (o) { if (o !== g) o.open = false; });
    });
  });
})();

// Keep the sidebar menu where it was after clicking a link (it scrolls on its own on short screens),
// instead of jumping back to the top on every page. Only the menu; the page itself is not touched.
(function () {
  var sidebar = document.querySelector(".sidebar");
  if (!sidebar) return;
  var KEY = "sidebarScroll";
  function save() {
    try { sessionStorage.setItem(KEY, String(sidebar.scrollTop)); } catch (e) { /* storage blocked */ }
  }
  var saved = null;
  try { saved = sessionStorage.getItem(KEY); } catch (e) { /* storage blocked */ }
  if (saved !== null && !isNaN(parseInt(saved, 10))) sidebar.scrollTop = parseInt(saved, 10);
  // If the current page's link is still out of view, bring it just into view.
  var active = sidebar.querySelector(".nav a.active");
  if (active && sidebar.scrollHeight > sidebar.clientHeight) {
    var box = sidebar.getBoundingClientRect(), link = active.getBoundingClientRect();
    if (link.top < box.top || link.bottom > box.bottom) active.scrollIntoView({ block: "nearest" });
  }
  sidebar.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest(".nav a")) save();
  });
  window.addEventListener("pagehide", save);
})();

// Buttons marked data-confirm ask "Are you sure?" before the form is sent.
document.addEventListener("submit", function (e) {
  var btn = e.submitter;
  var msg = (btn && btn.getAttribute("data-confirm")) || e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) e.preventDefault();
});

// Stop double clicks sending the same form twice (the server also ignores repeats).
document.addEventListener("submit", function (e) {
  if (e.defaultPrevented || e.target.method.toLowerCase() !== "post") return;
  var btn = e.submitter;
  if (btn) setTimeout(function () { btn.disabled = true; }, 0);
});
