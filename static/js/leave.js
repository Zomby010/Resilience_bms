// The Manager's "Days given": a quiet note when the number is below the legal minimum (it never blocks).
(function () {
  var input = document.querySelector("[data-minimum]");
  var note = document.querySelector("[data-minimum-note]");
  if (!input || !note) return;
  function check() {
    var v = parseFloat(input.value);
    note.hidden = !(v > 0 && v < parseFloat(input.dataset.minimum));
  }
  input.addEventListener("input", check);
  check();
})();
