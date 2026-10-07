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
