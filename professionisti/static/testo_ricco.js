// Barra G / elenco sulle caselle con data-ricco (descrizioni delle voci e note).
// Il testo resta semplice: **grassetto** e "- " a inizio riga; il PDF li mostra formattati.
(function () {
  "use strict";

  function sostituisci(t, inizio, fine, nuovo, selDa, selA) {
    t.setRangeText(nuovo, inizio, fine, "end");
    t.setSelectionRange(selDa, selA);
    t.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function grassetto(t) {
    let a = t.selectionStart, b = t.selectionEnd;
    const v = t.value;
    while (a < b && /\s/.test(v[a])) a++;                     // gli spazi restano fuori dai **
    while (b > a && /\s/.test(v[b - 1])) b--;
    const sel = v.slice(a, b);
    if (v.slice(a - 2, a) === "**" && v.slice(b, b + 2) === "**") {          // gia' in grassetto: lo toglie
      sostituisci(t, a - 2, b + 2, sel, a - 2, b - 2);
    } else if (sel.startsWith("**") && sel.endsWith("**") && sel.length >= 4) {
      sostituisci(t, a, b, sel.slice(2, -2), a, b - 4);
    } else {
      sostituisci(t, a, b, "**" + sel + "**", a + 2, b + 2);
    }
  }

  function elenco(t) {
    const v = t.value;
    const a = v.lastIndexOf("\n", t.selectionStart - 1) + 1;
    let b = v.indexOf("\n", Math.max(t.selectionEnd - (t.selectionEnd > t.selectionStart ? 1 : 0), t.selectionStart));
    if (b < 0) b = v.length;
    const righe = v.slice(a, b).split("\n");
    const tutte = righe.every(r => /^\s*[-*•]\s/.test(r) || !r.trim());
    const nuove = righe.map(r => tutte ? r.replace(/^\s*[-*•]\s+/, "") : (r.trim() && !/^\s*[-*•]\s/.test(r) ? "- " + r : r));
    const testo = nuove.join("\n") || "- ";
    sostituisci(t, a, b, testo, a + testo.length, a + testo.length);
  }

  function barra(t) {
    if (t.parentElement.classList.contains("ricco")) return;
    const da = t.selectionStart, a = t.selectionEnd;
    const box = document.createElement("span");
    box.className = "ricco";
    t.parentNode.insertBefore(box, t);
    box.appendChild(t);                                            // spostarla le toglie il cursore: lo rimetto
    t.focus();
    t.setSelectionRange(da, a);
    const b = document.createElement("span");
    b.className = "ricco-barra";
    b.innerHTML = '<button type="button" data-f="g" title="Grassetto (⌘B): **testo**" aria-label="Grassetto"><b>G</b></button>' +
                  '<button type="button" data-f="e" title="Elenco puntato: righe che iniziano con - " aria-label="Elenco puntato">•≡</button>';
    box.appendChild(b);
    b.addEventListener("mousedown", e => e.preventDefault());       // non togliere il cursore dalla casella
    b.addEventListener("click", e => {
      const k = e.target.closest("button");
      if (!k) return;
      t.focus();
      (k.dataset.f === "g" ? grassetto : elenco)(t);
    });
  }

  document.addEventListener("focusin", e => {
    const t = e.target;
    if (t.matches && t.matches("textarea[data-ricco]")) barra(t);
  });

  document.addEventListener("keydown", e => {
    const t = e.target;
    if (!t.matches || !t.matches("textarea[data-ricco]")) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
      e.preventDefault();
      grassetto(t);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && t.selectionStart === t.selectionEnd) {
      const v = t.value, p = t.selectionStart;
      const inizio = v.lastIndexOf("\n", p - 1) + 1;
      const riga = v.slice(inizio, p);
      const m = riga.match(/^(\s*[-*•]\s+)(.*)$/);
      if (!m) return;
      e.preventDefault();
      if (!m[2].trim()) {                                        // punto vuoto: chiude l'elenco
        sostituisci(t, inizio, p, "", inizio, inizio);
      } else {
        sostituisci(t, p, p, "\n- ", p + 3, p + 3);
      }
    }
  });
})();
