// Da incassare: spunta le fatture che pensi di incassare a breve e ne vedi il totale.
// La scelta resta ricordata su questo Mac (anche dopo aver registrato un saldo).
(function () {
  "use strict";
  const CHIAVE = "incasso-scelte:" + location.port;
  const righe = Array.from(document.querySelectorAll(".elenco.incasso tbody tr[data-id]"));
  const tutte = document.getElementById("scegli-tutte");
  const riepilogo = document.getElementById("scelte");
  if (!righe.length || !riepilogo) return;
  const testoIniziale = riepilogo.textContent;

  function centesimi(v) {                       // "1830.00" -> 183000, senza errori di arrotondamento
    const m = String(v).trim().match(/^(-?)(\d+)(?:\.(\d{1,2}))?/);
    if (!m) return 0;
    return (m[1] ? -1 : 1) * (parseInt(m[2], 10) * 100 + parseInt((m[3] || "0").padEnd(2, "0"), 10));
  }
  function euro(c) {                            // come nel resto del programma: € 9.671,09
    const neg = c < 0, a = Math.abs(c);
    const intero = String(Math.floor(a / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return (neg ? "-€ " : "€ ") + intero + "," + String(a % 100).padStart(2, "0");
  }
  function leggi() {
    try { return new Set(JSON.parse(localStorage.getItem(CHIAVE) || "[]")); } catch (e) { return new Set(); }
  }
  function salva(ids) {
    try { localStorage.setItem(CHIAVE, JSON.stringify(Array.from(ids))); } catch (e) { /* va bene anche senza */ }
  }

  function aggiorna() {
    let n = 0, tot = 0;
    const scelte = new Set();
    righe.forEach(r => {
      const on = r.querySelector("input.scegli").checked;
      r.classList.toggle("scelta", on);
      if (on) { n++; tot += centesimi(r.dataset.residuo); scelte.add(r.dataset.id); }
    });
    salva(scelte);
    if (tutte) {
      tutte.checked = n === righe.length;
      tutte.indeterminate = n > 0 && n < righe.length;
    }
    if (!n) {
      riepilogo.textContent = testoIniziale;
      return;
    }
    riepilogo.innerHTML = "Selezionate: <strong>" + euro(tot) + "</strong> su " + n + (n === 1 ? " fattura" : " fatture") +
      ' <button type="button" id="togli-scelte">Togli la selezione</button>';
    document.getElementById("togli-scelte").addEventListener("click", () => {
      righe.forEach(r => { r.querySelector("input.scegli").checked = false; });
      aggiorna();
    });
  }

  const ricordate = leggi();                     // solo fatture ancora da incassare: le saldate spariscono da sole
  righe.forEach(r => {
    const c = r.querySelector("input.scegli");
    c.checked = ricordate.has(r.dataset.id);
    c.addEventListener("change", aggiorna);
  });
  if (tutte) {
    tutte.addEventListener("change", () => {
      righe.forEach(r => { r.querySelector("input.scegli").checked = tutte.checked; });
      aggiorna();
    });
  }
  aggiorna();
})();
