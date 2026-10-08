// Phone menu: the "Menu" button shows or hides the links on small screens.
(function () {
  var btn = document.querySelector(".menu-toggle");
  var nav = document.getElementById("main-nav");
  if (!btn || !nav) return;
  btn.addEventListener("click", function () {
    var open = nav.classList.toggle("open");
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.textContent = open ? "Close menu" : "Menu";
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
