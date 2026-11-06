// Controllo di codice fiscale e partita IVA mentre si scrive (stesse regole di controlli_fiscali.py).
// Vale solo per i clienti italiani (Nazione IT); il programma ricontrolla comunque al salvataggio.
(function () {
  "use strict";
  const DISPARI = [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23];
  const N = "[0-9LMNPQRSTUV]";
  const FORMA_CF = new RegExp("^[A-Z]{6}" + N + "{2}[ABCDEHLMPRST]" + N + "{2}[A-Z]" + N + "{3}[A-Z]$");

  function pulisciPiva(v) {
    let p = (v || "").replace(/[\s.\-]/g, "").toUpperCase();
    if (/^IT\d+$/.test(p)) p = p.slice(2);
    return p;
  }

  function erroreP(v) {
    const p = pulisciPiva(v);
    if (!/^\d{11}$/.test(p)) return "La partita IVA italiana ha 11 cifre.";
    if (p === "00000000000") return "La partita IVA non è valida.";
    let somma = 0;
    for (let i = 0; i < 10; i++) {
      let n = +p[i];
      if (i % 2) { n *= 2; if (n > 9) n -= 9; }
      somma += n;
    }
    return (10 - somma % 10) % 10 === +p[10] ? "" : "La partita IVA non è valida: c'è una cifra sbagliata o invertita.";
  }

  function valore(ch) {        // cifra o lettera -> 0..25 (posizioni pari)
    return /\d/.test(ch) ? +ch : ch.charCodeAt(0) - 65;
  }

  function erroreCF(v) {
    const c = (v || "").replace(/\s/g, "").toUpperCase();
    if (/^\d{11}$/.test(c))
      return erroreP(c) ? "Il codice fiscale numerico non è valido: c'è una cifra sbagliata o invertita." : "";
    if (c.length !== 16) return "Il codice fiscale ha 16 caratteri (o 11 cifre per società ed enti).";
    if (!FORMA_CF.test(c)) return "Il codice fiscale non ha la forma giusta: controlla lettere e numeri.";
    let somma = 0;
    for (let i = 0; i < 15; i++) somma += i % 2 === 0 ? DISPARI[valore(c[i])] : valore(c[i]);
    return String.fromCharCode(65 + somma % 26) === c[15] ? "" : "Il codice fiscale non è valido: c'è un carattere sbagliato.";
  }

  function nota(input) {
    let n = input.parentElement.querySelector(".nota-campo");
    if (!n) {
      n = document.createElement("span");
      n.className = "nota-campo";
      n.setAttribute("aria-live", "polite");
      input.insertAdjacentElement("afterend", n);
    }
    return n;
  }

  function controlla(input, completo) {
    const contenitore = input.closest(".griglia") || input.form;
    const naz = contenitore && contenitore.querySelector('[name="nazione"]');
    const italiano = !naz || !naz.value.trim() || naz.value.trim().toUpperCase() === "IT";
    const v = input.value.trim();
    let msg = "", ok = false;
    if (italiano && v) {
      const lungo = input.name === "cf" ? v.replace(/\s/g, "").length >= 16 || /^\d{11}$/.test(v)
                                        : pulisciPiva(v).length >= 11;
      if (completo || lungo) {
        msg = input.name === "cf" ? erroreCF(v) : erroreP(v);
        ok = !msg;
      }
    }
    input.setCustomValidity(msg);
    input.classList.toggle("campo-errato", !!msg);
    const n = nota(input);
    n.textContent = msg || (ok ? "Corretto" : "");
    n.classList.toggle("ok", ok);
  }

  function campi(radice) {
    return radice.querySelectorAll('input[name="cf"], input[name="piva"]');
  }

  // Ritenuta d'acconto (solo dove c'e'): proposta dai dati, finche' non la si sceglie a mano.
  // Privato = codice fiscale di persona (16 caratteri) e niente partita IVA.
  function proponiRitenuta(t) {
    const g = t.closest(".griglia") || t.form;
    const box = g && g.querySelector("[data-ritenuta]");
    if (!box || box.dataset.scelta) return;
    const cf = g.querySelector('[name="cf"]'), piva = g.querySelector('[name="piva"]');
    const privato = !(piva && piva.value.trim()) && cf && cf.value.replace(/\s/g, "").length === 16;
    box.checked = !privato;
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches("[data-ritenuta]")) e.target.dataset.scelta = "1";
  });
  document.addEventListener("reset", function (e) {
    e.target.querySelectorAll("[data-ritenuta]").forEach(b => { delete b.dataset.scelta; });
  });

  document.addEventListener("input", function (e) {
    const t = e.target;
    if (t.name === "cf" || t.name === "piva") controlla(t, false);
    if (t.name === "cf" || t.name === "piva") proponiRitenuta(t);
    if (t.name === "nazione") campi(t.closest(".griglia") || document).forEach(i => controlla(i, true));
  });
  document.addEventListener("focusout", function (e) {
    if (e.target.name === "cf" || e.target.name === "piva") controlla(e.target, true);
  });
  document.addEventListener("reset", function (e) {
    setTimeout(() => campi(e.target).forEach(i => controlla(i, false)));
  });
  document.addEventListener("DOMContentLoaded", function () {
    campi(document).forEach(i => { if (i.value) controlla(i, true); });
  });
})();
