// Modulo fattura Consept: voci con codice IVA, prezzi in dollari col cambio, riepilogo in tempo reale.
(function () {
  "use strict";
  const form = document.getElementById("form-doc");
  if (!form) return;
  const conto = document.getElementById("conto");
  const tabella = document.getElementById("voci");
  const corpo = tabella.querySelector("tbody");
  const valuta = document.getElementById("valuta");
  const cambio = document.getElementById("cambio");
  const banca = document.getElementById("banca");
  const pagamento = document.getElementById("pagamento");

  function numero(v) {
    v = (v || "").trim().replace(/\s|€|\$/g, "");
    if (!v) return null;
    v = v.includes(",") ? v.replace(/\./g, "").replace(",", ".") : v;
    const n = Number(v);
    return isNaN(n) ? null : n;
  }
  const testo = n => (Math.round(n * 100) / 100).toFixed(2).replace(".", ",");
  const usd = () => valuta && valuta.checked;

  // ------------------------------------------------ voci
  function adatta(t) {
    t.style.height = "auto";
    t.style.height = t.scrollHeight + 2 + "px";
  }
  form.querySelectorAll("textarea[name=r_descr]").forEach(adatta);

  form.addEventListener("click", function (e) {
    if (e.target.closest(".aggiungi")) {
      corpo.appendChild(document.getElementById("modello-voce").content.cloneNode(true));
      aggiornaEtichetteCodice();
      corpo.lastElementChild.querySelector("[name=r_descr]").focus();
      return;
    }
    const togli = e.target.closest(".togli");
    if (togli) {
      togli.closest("tr").remove();
      if (!corpo.children.length) corpo.appendChild(document.getElementById("modello-voce").content.cloneNode(true));
      aggiornaEtichetteCodice();
      ricalcola();
    }
  });

  // quantita' x prezzo; in dollari: prezzo € = prezzo $ x cambio, finche' non lo si scrive a mano
  function calcolaRiga(tr, daDollari) {
    const q = tr.querySelector("[name=r_qta]"), p = tr.querySelector("[name=r_prezzo]");
    const pv = tr.querySelector("[name=r_prezzo_v]"), imp = tr.querySelector("[name=r_importo]");
    const nc = numero(cambio && cambio.value), npv = numero(pv.value);
    if (usd() && npv !== null && nc && !p.dataset.manuale) {   // un prezzo in euro scritto a mano resta
      p.value = testo(npv * nc);
      p.classList.add("calcolato");
    }
    let nq = numero(q.value);
    const np = numero(p.value);
    if (nq === null && np !== null && (usd() ? npv !== null : true) && q.value.trim() === "" && usd()) nq = 1;
    const auto = nq !== null && np !== null;
    if (auto) imp.value = testo(nq * np);
    imp.readOnly = auto;
    imp.classList.toggle("calcolato", auto);
  }
  corpo.querySelectorAll("tr.voce").forEach(function (tr) {   // i prezzi in euro gia' salvati restano come sono
    const p = tr.querySelector("[name=r_prezzo]");
    if (p.value.trim()) p.dataset.manuale = "1";
    calcolaRiga(tr, false);
  });

  form.addEventListener("input", function (e) {
    const n = e.target.name;
    if (n === "r_descr") adatta(e.target);
    if (n === "r_prezzo") { e.target.dataset.manuale = e.target.value.trim() ? "1" : ""; e.target.classList.remove("calcolato"); }
    if (["r_qta", "r_prezzo", "r_prezzo_v"].includes(n)) calcolaRiga(e.target.closest("tr"), n === "r_prezzo_v");
    if (e.target === cambio) corpo.querySelectorAll("tr.voce").forEach(tr => calcolaRiga(tr, true));
    if (["r_importo", "r_qta", "r_prezzo", "r_prezzo_v"].includes(n) || e.target === cambio) ricalcolaPresto();
  });
  form.addEventListener("change", function (e) {
    if (e.target.name === "r_codice" || e.target === pagamento || e.target.name === "data") ricalcola();
  });

  // ------------------------------------------------ copia in dollari
  function aggiornaValuta(cambiata) {
    const on = usd();
    tabella.classList.toggle("con-usd", on);
    document.getElementById("riga-cambio").hidden = !on;
    document.getElementById("aiuto-dollari").hidden = !on;
    document.getElementById("totale-usd").hidden = !on;
    form.querySelectorAll(".solo-usd-btn").forEach(b => { b.hidden = !on; });
    if (cambiata && banca) {                // propone la banca della valuta giusta
      const vuole = on ? "USD" : "EUR";
      const sel = banca.options[banca.selectedIndex];
      if (!sel || sel.dataset.valuta !== vuole) {
        const o = Array.from(banca.options).find(x => x.dataset.valuta === vuole);
        if (o) banca.value = o.value;
      }
    }
    if (cambiata) corpo.querySelectorAll("tr.voce").forEach(tr => calcolaRiga(tr, true));
  }
  if (valuta) valuta.addEventListener("change", () => { aggiornaValuta(true); ricalcola(); });
  aggiornaValuta(false);

  // ------------------------------------------------ cliente
  const clienti = JSON.parse(document.getElementById("dati-clienti").textContent);
  const testoCli = document.getElementById("cliente-testo");
  const hid = document.getElementById("cliente-id");
  const dettagli = document.getElementById("cliente-dettagli");
  const lista = document.getElementById("lista-clienti");

  function aggiornaEtichetteCodice() {
    const c = clienti[hid.value];
    const cod = c ? c.codice : "";
    form.querySelectorAll("select[name=r_codice]").forEach(function (s) {
      s.options[0].textContent = cod ? "(" + cod + ")" : "cliente";
    });
    if (pagamento) pagamento.options[0].textContent = c ? "come da cliente: " + c.pagamento : "come da cliente";
  }
  function scegli() {
    const opt = Array.from(lista.options).find(o => o.value === testoCli.value);
    if (opt) {
      hid.value = opt.dataset.id;
      testoCli.value = clienti[opt.dataset.id].nome;
      dettagli.textContent = clienti[opt.dataset.id].dettagli;
      dettagli.classList.remove("avviso");
    } else if (!testoCli.value.trim()) {
      hid.value = ""; dettagli.textContent = "";
    } else if (!hid.value || clienti[hid.value].nome !== testoCli.value) {
      hid.value = "";
      dettagli.textContent = "Cliente non in archivio: sceglilo dall'elenco oppure crealo con Nuovo cliente.";
      dettagli.classList.add("avviso");
    }
    aggiornaEtichetteCodice();
    ricalcola();
  }
  testoCli.addEventListener("input", scegli);
  testoCli.addEventListener("change", scegli);
  aggiornaEtichetteCodice();

  const dlg = document.getElementById("dlg-cliente");
  const formCli = document.getElementById("form-cliente");
  document.getElementById("apri-nuovo-cliente").addEventListener("click", function () {
    formCli.reset();
    document.getElementById("errori-cliente").innerHTML = "";
    if (testoCli.value && !hid.value) formCli.denominazione.value = testoCli.value;
    dlg.showModal();
  });
  document.getElementById("chiudi-cliente").addEventListener("click", () => dlg.close());
  formCli.addEventListener("submit", async function (e) {
    e.preventDefault();
    const r = await fetch("/api/cliente", {method: "POST", body: new FormData(formCli)});
    const d = await r.json();
    if (!r.ok) {
      const box = document.getElementById("errori-cliente");
      box.innerHTML = "";
      d.errori.forEach(function (x) { const p = document.createElement("p"); p.className = "msg errore"; p.textContent = x; box.appendChild(p); });
      return;
    }
    clienti[d.id] = {nome: d.nome, dettagli: d.dettagli, codice: d.codice, pagamento: d.pagamento, estero: d.estero};
    const o = document.createElement("option");
    o.value = d.nome; o.dataset.id = d.id;
    lista.appendChild(o);
    hid.value = d.id; testoCli.value = d.nome; dettagli.textContent = d.dettagli;
    dettagli.classList.remove("avviso");
    aggiornaEtichetteCodice();
    dlg.close();
    ricalcola();
  });

  // ------------------------------------------------ riepilogo
  function voci() {
    return Array.from(corpo.querySelectorAll("tr.voce")).map(function (tr) {
      const q = numero(tr.querySelector("[name=r_qta]").value);
      const pv = numero(tr.querySelector("[name=r_prezzo_v]").value);
      return {importo: tr.querySelector("[name=r_importo]").value,
              codice: tr.querySelector("[name=r_codice]").value,
              importo_valuta: usd() && pv !== null ? testo((q === null ? 1 : q) * pv) : "",
              campo: tr.querySelector("[name=r_importo]")};
    });
  }
  async function ricalcola() {
    const v = voci();
    const dati = {righe: v.map(x => ({importo: x.importo, codice: x.codice, importo_valuta: x.importo_valuta})),
                  cliente_id: hid.value, data: form.data.value, tipo: form.tipo.value,
                  pagamento: pagamento ? pagamento.value : "", valuta: usd() ? "USD" : ""};
    const r = await fetch("/api/calcola", {method: "POST", headers: {"Content-Type": "application/json"},
                                           body: JSON.stringify(dati)});
    const d = await r.json();
    conto.querySelectorAll("[data-k]").forEach(function (el) { if (d[el.dataset.k] !== undefined) el.textContent = d[el.dataset.k]; });
    const g = document.getElementById("gruppi");
    g.innerHTML = "";
    d.gruppi.forEach(function (x) {
      const tr = document.createElement("tr");
      [x.testo, x.imponibile, x.imposta].forEach(function (t, i) {
        const td = document.createElement("td"); td.textContent = t; if (i) td.className = "num"; tr.appendChild(td);
      });
      g.appendChild(tr);
    });
    const sc = document.getElementById("scadenze");
    sc.innerHTML = "";
    d.scadenze.forEach(function (x) {
      const li = document.createElement("li"); li.textContent = x.data + ": " + x.importo; sc.appendChild(li);
    });
    document.getElementById("scadenze-box").hidden = !d.scadenze.length;
    document.getElementById("nota-bollo").hidden = !d.bollo;
    // fattura con copia in dollari: ogni voce con importo deve avere il prezzo in USD
    const manca = usd() ? Array.from(corpo.querySelectorAll("tr.voce")).filter(function (tr) {
      return tr.querySelector("[name=r_importo]").value.trim() && !tr.querySelector("[name=r_prezzo_v]").value.trim();
    }) : [];
    corpo.querySelectorAll("[name=r_prezzo_v]").forEach(i => i.classList.remove("errato"));
    manca.forEach(tr => tr.querySelector("[name=r_prezzo_v]").classList.add("errato"));
    const avv = document.getElementById("manca-usd");
    avv.hidden = !manca.length;
    avv.textContent = manca.length ? "Manca il prezzo nella colonna Prezzo USD (evidenziata in rosso)." : "";
    const err = document.getElementById("errore-calcolo");
    err.hidden = !d.errore; err.textContent = d.errore || "";
    v.forEach(function (x, i) { x.campo.classList.toggle("errato", d.errati.includes(i)); });
  }
  let timer;
  function ricalcolaPresto() { clearTimeout(timer); timer = setTimeout(ricalcola, 200); }
  ricalcola();

  // ------------------------------------------------ avviso se si esce senza salvare
  let modificato = false;
  form.addEventListener("input", () => { modificato = true; });
  form.addEventListener("submit", function (e) {
    if (!e.submitter || e.submitter.formTarget !== "_blank") modificato = false;
  });
  window.addEventListener("beforeunload", function (e) { if (modificato) e.preventDefault(); });
})();
