// Modulo fattura: voci, cliente, riepilogo in tempo reale e calcolo dal totale.
(function () {
  const form = document.getElementById("form-doc");
  if (!form) return;
  const conto = document.getElementById("conto");
  const bollo = document.getElementById("bollo");
  const ritenuta = document.getElementById("ritenuta");     // solo con la ritenuta d'acconto (Ing)

  // ------------------------------------------------ voci
  function adatta(t) {                      // le descrizioni lunghe allargano la riga
    if (t.tagName !== "TEXTAREA") return;
    t.style.height = "auto";
    t.style.height = t.scrollHeight + 2 + "px";
  }
  form.querySelectorAll("textarea[name=r_descr]").forEach(adatta);

  form.addEventListener("click", function (e) {
    const agg = e.target.closest(".aggiungi");
    if (agg) {
      const tipo = agg.dataset.tipo;
      const corpo = document.querySelector("#voci-" + tipo + " tbody");
      corpo.appendChild(document.getElementById("modello-" + tipo).content.cloneNode(true));
      corpo.lastElementChild.querySelector("[name=r_descr]").focus();
      return;
    }
    const togli = e.target.closest(".togli");
    if (togli) {
      const riga = togli.closest("tr");
      const corpo = riga.parentElement;
      riga.remove();
      if (corpo.closest("#voci-onorario") && !corpo.children.length) {
        corpo.appendChild(document.getElementById("modello-onorario").content.cloneNode(true));
      }
      ricalcola();
    }
  });
  // ore x tariffa: se quantita' e prezzo sono scritti, l'importo si calcola da solo
  function numero(v) {
    v = (v || "").trim().replace(/\s|€/g, "");
    if (!v) return null;
    v = v.includes(",") ? v.replace(/\./g, "").replace(",", ".") : v;
    const n = Number(v);
    return isNaN(n) ? null : n;
  }
  function calcolaRiga(tr) {
    const q = tr.querySelector("[name=r_qta]"), p = tr.querySelector("[name=r_prezzo]");
    if (!q || !p) return;
    const imp = tr.querySelector("[name=r_importo]");
    const nq = numero(q.value), np = numero(p.value);
    const auto = nq !== null && np !== null;
    if (auto) imp.value = (Math.round(nq * np * 100) / 100).toFixed(2).replace(".", ",");
    imp.readOnly = auto;
    imp.classList.toggle("calcolato", auto);
  }
  form.querySelectorAll("tr.voce").forEach(calcolaRiga);
  form.addEventListener("input", function (e) {
    if (e.target.name === "r_descr") adatta(e.target);
    if (e.target.name === "r_qta" || e.target.name === "r_prezzo") calcolaRiga(e.target.closest("tr"));
    if (["r_importo", "r_qta", "r_prezzo"].includes(e.target.name)) ricalcolaPresto();
  });
  if (bollo) bollo.addEventListener("change", ricalcola);
  if (ritenuta) ritenuta.addEventListener("change", ricalcola);

  // ------------------------------------------------ riepilogo
  function voci() {
    return Array.from(form.querySelectorAll("tr.voce")).map(function (tr) {
      return {tipo: tr.querySelector("[name=r_tipo]").value,
              importo: tr.querySelector("[name=r_importo]").value, campo: tr.querySelector("[name=r_importo]")};
    });
  }
  async function chiedi(extra) {
    const v = voci();
    const corpo = Object.assign({righe: v.map(x => ({tipo: x.tipo, importo: x.importo})),
                                 bollo: bollo ? bollo.checked : false,
                                 ritenuta: ritenuta ? ritenuta.checked : true}, extra);
    const r = await fetch("/api/calcola", {method: "POST", headers: {"Content-Type": "application/json"},
                                           body: JSON.stringify(corpo)});
    return [await r.json(), v];
  }
  function mostra(d, v) {
    conto.querySelectorAll("[data-k]").forEach(function (el) { el.textContent = d[el.dataset.k]; });
    const rb = conto.querySelector("[data-riga=bollo]"), ra = conto.querySelector("[data-riga=anticipazioni]");
    if (rb) rb.hidden = d.bollo_valore === "0" || d.bollo_valore === "0.00";
    if (ra) ra.hidden = d.anticipazioni === "€ 0,00";
    const rv = conto.querySelector("[data-riga=vendite]"), rr = conto.querySelector("[data-riga=ritenuta]");
    if (rv) rv.hidden = d.vendite === "€ 0,00";
    if (rr) rr.hidden = !ritenuta.checked;
    document.getElementById("nota-bollo").hidden = !(bollo && d.bollo_dovuto && !bollo.checked);
    v.forEach(function (x, i) { x.campo.classList.toggle("errato", d.errati.includes(i)); });
  }
  async function ricalcola() {
    const [d, v] = await chiedi({});
    mostra(d, v);
  }
  let timer;
  function ricalcolaPresto() { clearTimeout(timer); timer = setTimeout(ricalcola, 180); }
  ricalcola();

  // ------------------------------------------------ calcolo dal totale
  const voluto = document.getElementById("totale-voluto");
  const esito = document.getElementById("esito-totale");
  async function applica() {
    if (!voluto.value.trim()) { voluto.focus(); return; }
    const sel = document.getElementById("campo-voluto");
    const [d, v] = await chiedi({totale: voluto.value, campo: sel ? sel.value : "totale"});
    if (d.errore_totale) { esito.textContent = "Scrivi il totale in euro, ad esempio 1050,00."; return; }
    let campo = (v.find(x => x.tipo === "onorario") || {}).campo;
    const tr = campo.closest("tr");
    ["r_qta", "r_prezzo"].forEach(n => { const el = tr.querySelector("[name=" + n + "]"); if (el) el.value = ""; });
    campo.readOnly = false;
    campo.classList.remove("calcolato");
    campo.value = d.scorporo.importo;
    campo.closest("tr").classList.add("appena-calcolata");
    setTimeout(() => campo.closest("tr").classList.remove("appena-calcolata"), 1600);
    esito.textContent = d.scorporo.esatto
      ? "Prima voce: € " + d.scorporo.importo + "."
      : "Il totale esatto non è raggiungibile al centesimo: il più vicino è " + d.scorporo.ottenuto + ".";
    ricalcola();
  }
  document.getElementById("applica-totale").addEventListener("click", applica);
  voluto.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); applica(); } });

  // ------------------------------------------------ cliente
  const clienti = JSON.parse(document.getElementById("dati-clienti").textContent);
  const testo = document.getElementById("cliente-testo");
  const hid = document.getElementById("cliente-id");
  const dettagli = document.getElementById("cliente-dettagli");
  const lista = document.getElementById("lista-clienti");
  // la ritenuta segue il cliente: i privati non sono sostituti d'imposta
  function ritenutaDalCliente(id) {
    if (!ritenuta || !clienti[id]) return;
    const prima = ritenuta.checked;
    ritenuta.checked = !!clienti[id].ritenuta;
    if (prima !== ritenuta.checked) ricalcola();
  }
  function scegli() {
    const opt = Array.from(lista.options).find(o => o.value === testo.value);
    if (opt) {
      if (hid.value !== opt.dataset.id) ritenutaDalCliente(opt.dataset.id);
      hid.value = opt.dataset.id;
      testo.value = clienti[opt.dataset.id].nome;
      dettagli.textContent = clienti[opt.dataset.id].dettagli;
      dettagli.classList.remove("avviso");
    } else if (!testo.value.trim()) {
      hid.value = ""; dettagli.textContent = "";
    } else if (!hid.value || clienti[hid.value].nome !== testo.value) {
      hid.value = "";
      dettagli.textContent = "Cliente non in archivio: sceglilo dall'elenco oppure crealo con Nuovo cliente.";
      dettagli.classList.add("avviso");
    }
  }
  testo.addEventListener("input", scegli);
  testo.addEventListener("change", scegli);

  const dlg = document.getElementById("dlg-cliente");
  const formCli = document.getElementById("form-cliente");
  document.getElementById("apri-nuovo-cliente").addEventListener("click", function () {
    formCli.reset();
    document.getElementById("errori-cliente").innerHTML = "";
    if (testo.value && !hid.value) formCli.denominazione.value = testo.value;
    dlg.showModal();
  });
  document.getElementById("chiudi-cliente").addEventListener("click", () => dlg.close());
  formCli.addEventListener("submit", async function (e) {
    e.preventDefault();
    const r = await fetch("/api/cliente", {method: "POST", body: new FormData(formCli)});
    const d = await r.json();
    if (!r.ok) {
      document.getElementById("errori-cliente").innerHTML =
        d.errori.map(x => '<p class="msg errore"></p>').join("");
      document.querySelectorAll("#errori-cliente p").forEach((p, i) => { p.textContent = d.errori[i]; });
      return;
    }
    clienti[d.id] = {nome: d.nome, dettagli: d.dettagli, ritenuta: d.ritenuta};
    ritenutaDalCliente(d.id);
    const o = document.createElement("option");
    o.value = d.nome; o.dataset.id = d.id;
    lista.appendChild(o);
    hid.value = d.id; testo.value = d.nome; dettagli.textContent = d.dettagli;
    dettagli.classList.remove("avviso");
    dlg.close();
  });

  // ------------------------------------------------ frase del terzo pagatore
  const terzo = document.getElementById("terzo");
  const frase = document.getElementById("terzo-frase");
  function aggiornaTerzo() {
    frase.hidden = !terzo.value.trim();
    frase.querySelector("span").textContent = terzo.value.trim();
  }
  if (terzo) { terzo.addEventListener("input", aggiornaTerzo); aggiornaTerzo(); }

  // ------------------------------------------------ avviso se si esce senza salvare
  let modificato = false;
  form.addEventListener("input", () => { modificato = true; });
  form.addEventListener("submit", function (e) {
    if (!e.submitter || e.submitter.formTarget !== "_blank") modificato = false;
  });
  window.addEventListener("beforeunload", function (e) { if (modificato) e.preventDefault(); });
})();
