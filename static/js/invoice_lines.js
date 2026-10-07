// Invoice form: add lines and show a live preview of the totals. The server always recalculates.
(function () {
  var form = document.getElementById("invoice-form");
  if (!form) return;
  var body = document.querySelector("#lines tbody");
  var tpl = document.getElementById("empty-line");
  var total = form.querySelector("[name=lines-TOTAL_FORMS]");
  var rate = parseFloat(form.getAttribute("data-vat-rate")) || 0;
  var vatBox = form.querySelector("[name=vat_enabled]");
  function num(el) { var v = parseFloat(el && el.value); return isNaN(v) ? 0 : v; }
  function fmt(v) { return v.toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function recalc() {
    var sub = 0;
    body.querySelectorAll("tr.line").forEach(function (row) {
      var del = row.querySelector("[name$=-DELETE]");
      var amt = Math.round(num(row.querySelector("[name$=-quantity]")) * num(row.querySelector("[name$=-unit_price]")) * 100) / 100;
      row.querySelector(".amount").textContent = fmt(amt);
      row.style.opacity = del && del.checked ? 0.4 : 1;
      if (!(del && del.checked)) sub += amt;
    });
    var vat = vatBox && vatBox.checked ? Math.round(sub * rate) / 100 : 0;
    document.getElementById("subtotal").textContent = fmt(sub);
    var v = document.getElementById("vat"); if (v) v.textContent = fmt(vat);
    document.getElementById("total").textContent = fmt(sub + vat);
  }
  document.getElementById("add-line").addEventListener("click", function () {
    var i = parseInt(total.value, 10);
    var html = tpl.innerHTML.replace(/__prefix__/g, i);
    body.insertAdjacentHTML("beforeend", html);
    total.value = i + 1;
    body.lastElementChild.querySelector("[name$=-description]").focus();
  });
  form.addEventListener("input", recalc);
  form.addEventListener("change", recalc);
  recalc();
})();
