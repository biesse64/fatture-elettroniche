"""
Fatture dello Studio Legale: applicazione locale nel browser (http://127.0.0.1:5077).

Si avvia con avvia.command (doppio clic) oppure con:  python3 app_studio.py
I dati restano nel Mac, nella cartella dati/ accanto a questo file.
"""
import os
import re
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request, send_file,
                   url_for)

import config_studio as C
import db_studio as db
import pec_studio as pec
from controlli_fiscali import controlla_cf, controlla_piva, pulisci_piva
import calcoli_studio as K
from calcoli_studio import euro, importo, in_valuta, modello_fattura, numero_testo, q2
from fatturapa_core import Errore, costruisci_xml, nome_file
from fatturapa_core import riepilogo
from pdf_consept import crea_pdf
import testo_ricco

app = Flask(__name__)
app.secret_key = "studio-legale-locale"          # solo per i messaggi a video; l'app gira solo sul Mac
ANTEPRIME = C.USCITA / "anteprime"


# ---------------------------------------------------------------- filtri per le pagine
@app.template_filter("data_it")
def data_it(iso):
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return iso or ""


@app.template_filter("valuta")
def f_valuta(x, v="EUR"):
    return in_valuta(Decimal(x), v) if x is not None and str(x).strip() else ""


@app.template_filter("ricco")
def f_ricco(x):
    return testo_ricco.html(x)


@app.template_filter("euro")
def f_euro(x):
    return euro(Decimal(x)) if x is not None and str(x).strip() else ""


@app.template_filter("quantita")
def f_quantita(x):
    """20.00 -> '20', 7.50 -> '7,5'."""
    s = f"{Decimal(x):f}".rstrip("0").rstrip(".") if str(x or "").strip() else ""
    return s.replace(".", ",")


@app.template_filter("importo_campo")
def importo_campo(x):
    """Importo salvato ('1007.62') -> come si scrive nel campo ('1007,62')."""
    return str(x).replace(".", ",") if str(x or "").strip() else ""


def opzioni():
    """Cosa mostrare nelle pagine, secondo la posizione fiscale (config_studio)."""
    iva = getattr(C, "IVA_PERC", "0")
    rit = getattr(C, "RITENUTA", None)
    return {"iva": iva if iva not in ("", "0") else "", "ritenuta": rit["aliquota_perc"] if rit else "",
            "bollo": bool(C.BOLLO), "qta": getattr(C, "MOSTRA_QUANTITA", False),
            "anticipazioni": getattr(C, "MOSTRA_ANTICIPAZIONI", True),
            "terzo": False}


@app.context_processor
def globali():
    return {"C": C, "STATI": C.STATI, "oggi": date.today().isoformat(), "O": opzioni(), "logo": C.LOGO.exists(),
            "PEC": pec.configurata(), "codici_iva": db.codici_iva, "lista_pagamenti": db.pagamenti}


def numero_breve(d):
    """66, oppure 66/A per i numeri con suffisso importati da Easyfatt (gli avvisi hanno numeri loro)."""
    suff = d["suffisso"] if "suffisso" in d.keys() and d["suffisso"] and d["tipo"] != "AVV" else ""
    return f"{d['numero']}/{suff}" if suff else str(d["numero"])


def numero_completo(d):
    return f"{numero_breve(d)}/{d['anno']}"


def nome_documento(d):
    tipo = {"TD04": "Nota di credito", "AVV": "Avviso di fattura"}.get(d["tipo"], "Fattura")
    return f"{tipo} n. {numero_completo(d)}"


def prossimo(tipo, anno):
    """Numero proposto: gli avvisi hanno la loro numerazione, fatture e note di credito una sola."""
    return db.prossimo_avviso(anno) if tipo == "AVV" else db.prossimo_numero(anno)


def prefisso_file(tipo):
    return {"TD04": "NotaCredito", "AVV": "Avviso"}.get(tipo, "Fattura")


# codici destinatario proposti nel modulo cliente (come la tendina di Easyfatt)
CODICI_SDI_NOTI = ["M5UXCR1", "USAL8PV", "W7YVJK9", "KRRH6B9", "A4707H7", "T04ZHR3", "X2PH38J", "5RUO82D",
                   "T9K4ZHO", "P62QHVQ", "SUBM70N", "5W4A8J1", "UE2LXTM", "BA6ET11", "JHBM40P", "2R4GTO8"]


def codici_destinatario():
    """(codice, spiegazione): i due codici speciali, poi quelli gia' usati in archivio, poi quelli comuni."""
    with db.conn() as c:
        usati = c.execute("SELECT UPPER(codice_destinatario) AS k, COUNT(*) AS n FROM clienti "
                          "WHERE LENGTH(codice_destinatario) = 7 AND UPPER(codice_destinatario) NOT IN ('0000000', 'XXXXXXX') "
                          "GROUP BY 1 ORDER BY n DESC, k").fetchall()
    out = [("0000000", "Privato o cliente senza codice: la fattura va nel suo cassetto fiscale"),
           ("XXXXXXX", "Cliente estero")]
    out += [(r["k"], f"già usato da {r['n']} {'cliente' if r['n'] == 1 else 'clienti'}") for r in usati]
    out += [(k, "codice comune") for k in CODICI_SDI_NOTI if k not in {r["k"] for r in usati}]
    return out


app.jinja_env.globals.update(nome_documento=nome_documento, numero_breve=numero_breve,
                             codici_destinatario=codici_destinatario)


# ---------------------------------------------------------------- utilita'
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre")


def cartella_mese(doc):
    """uscita/<anno>/<mm-mese>/ secondo la data del documento (es. uscita/2026/10-ottobre)."""
    m = int((doc["data"] or "")[5:7] or 0)
    sotto = f"{m:02d}-{MESI[m - 1]}" if 1 <= m <= 12 else ""
    return C.USCITA / str(doc["anno"]) / sotto


def percorso_dati(rel):
    """Percorso di un file dell'archivio. Se e' stato spostato a mano (es. nelle cartelle dei mesi)
    lo ritrova per nome dentro uscita/<anno>/."""
    if not rel:
        return None
    p = C.DATI / rel
    if p.exists():
        return p
    parti = Path(rel).parts
    radice = C.USCITA / parti[1] if len(parti) > 2 and parti[0] == "uscita" else C.USCITA
    for trovato in (radice.rglob(p.name) if radice.is_dir() else []):
        return trovato
    return p


def relativo(p):
    return str(p.relative_to(C.DATI))


def slug(testo):
    s = re.sub(r"[^A-Za-z0-9]+", "_", testo or "").strip("_")
    return s[:40] or "cliente"


def privato(cli):
    return (cli["nazione"] or "IT").upper() == "IT" and not (cli["piva"] or "").strip()


def estero(cli):
    return (cli["nazione"] or "IT").upper() != "IT"


def leggi_numero(testo):
    """'24' -> (24, ''); '24/A', '24 a', '24-B' -> (24, 'A'/'B'); '24 bis' -> (24, 'BIS'); vuoto -> ('', '').
    Il suffisso serve per un numero aggiunto tra due gia' usati (es. fattura dimenticata). Non valido -> (None, '')."""
    t = (testo or "").strip()
    if not t:
        return "", ""
    m = re.fullmatch(r"(\d+)\s*(?:[/\-\s]\s*([A-Za-z]{1,3}))?", t)
    if not m or (m.group(2) or "").upper() == db.SUFFISSO_AVVISO:
        return None, ""
    return m.group(1), (m.group(2) or "").upper()


def numero_file(d):
    """Numero nei nomi dei file: 24, 24A (gli avvisi senza il loro suffisso interno)."""
    suff = d["suffisso"] if "suffisso" in d.keys() and d["suffisso"] and d["tipo"] != "AVV" else ""
    return f"{d['numero']}{suff}"


def leggi_form(form):
    """Campi del documento e righe dal modulo. Restituisce (dati, righe, errori)."""
    errori = []
    data = form.get("data") or date.today().isoformat()
    try:
        date.fromisoformat(data)
    except ValueError:
        errori.append("La data non è valida.")
        data = date.today().isoformat()
    anno = int(data[:4])
    tipo = form.get("tipo") if form.get("tipo") in ("TD04", "AVV") else "TD01"
    numero, suffisso = leggi_numero(form.get("numero"))
    if numero is None:
        errori.append("Il numero si scrive come 24, oppure 24/A, 24/B, 24 bis per un numero aggiunto tra due già usati.")
        numero, suffisso = "", ""
    if tipo == "AVV":
        suffisso = ""                            # gli avvisi hanno una numerazione loro, senza lettere
    cid = form.get("cliente_id") or ""
    bid = form.get("banca_id") or ""
    valuta = "USD" if form.get("valuta") == "USD" else ""
    cambio = None
    if valuta:
        try:
            cambio = numero_testo(form.get("cambio"))
            if cambio is None or cambio <= 0:
                raise ValueError
        except ValueError:
            errori.append("Scrivi il cambio del giorno: quanti euro vale 1 dollaro (es. 0,8925).")
            cambio = None
    dati = {
        "tipo": tipo, "anno": anno, "numero": int(numero) if numero else prossimo(tipo, anno),
        "suffisso": db.SUFFISSO_AVVISO if tipo == "AVV" else suffisso,
        "data": data, "cliente_id": int(cid) if cid.isdigit() else None, "terzo_pagatore": "",
        "note": (form.get("note") or "").strip(), "bollo": 0,
        "rif_numero": (form.get("rif_numero") or "").strip() if tipo == "TD04" else "",
        "rif_data": (form.get("rif_data") or "").strip() if tipo == "TD04" else "",
        "pagamento": (form.get("pagamento") or "").strip(),
        "banca_id": int(bid) if bid.isdigit() else None,
        "valuta": valuta, "cambio": str(cambio) if cambio is not None else (form.get("cambio") or "").strip(),
    }
    righe = []
    n = len(form.getlist("r_descr"))
    col = lambda k: (form.getlist(k) + [""] * n)[:n]
    for d, q, um, prv, pr, imp, cod in zip(col("r_descr"), col("r_qta"), col("r_um"), col("r_prezzo_v"),
                                            col("r_prezzo"), col("r_importo"), col("r_codice")):
        d, q, um, prv, pr, imp, cod = (x.strip() for x in (d, q, um, prv, pr, imp, cod))
        if not any((d, q, prv, pr, imp)):
            continue
        try:
            qv, pv, prvv = numero_testo(q), numero_testo(pr), numero_testo(prv)
            if valuta and prvv is not None:
                qv = qv if qv is not None else Decimal(1)
                if pv is None and cambio is not None:
                    pv = q2(prvv * cambio)          # prezzo in euro dal cambio, se non scritto a mano
            if qv is not None and pv is not None:
                v = q2(qv * pv)
            else:
                v = importo(imp)
                qv = pv = None
        except ValueError:
            errori.append(f"Quantità, prezzo o importo non valido nella voce «{(d or imp)[:40]}»: scrivi ad esempio 850,00.")
            v = qv = pv = prvv = None
        con_qta = v is not None and qv is not None and pv is not None
        righe.append({"tipo": "onorario", "descrizione": d, "importo": str(v) if v is not None else "",
                      "quantita": f"{qv.normalize():f}" if con_qta else "", "um": um if con_qta else "",
                      "prezzo": str(pv) if con_qta else "", "codice_iva": cod if v is not None else "",
                      "prezzo_valuta": str(prvv) if valuta and prvv is not None and v is not None else "",
                      "importo_valuta": str(q2((qv or 1) * prvv)) if valuta and prvv is not None and v is not None else ""})
    imponibili = [Decimal(r["importo"]) for r in righe if r["importo"]]
    dati["totale"] = dati["netto"] = str(sum(imponibili, Decimal(0)))   # senza cliente: solo gli imponibili
    cli = db.cliente(dati["cliente_id"]) if dati["cliente_id"] else None
    if cli and imponibili:
        try:
            ls = K.linee(K.leggi_righe_db(righe), cli, K.codici())
            dati["totale"] = dati["netto"] = str(K.totali(ls, K.codici())["totale"])
        except ValueError:
            pass
    return dati, righe, errori


def controlla_per_generare(dati, righe, cli):
    errori = []
    if not cli:
        errori.append("Scegli il cliente.")
    elif (cli["nazione"] or "IT") == "IT":
        if not ((cli["cf"] or "").strip() or (cli["piva"] or "").strip()):
            errori.append("Il cliente non ha né codice fiscale né partita IVA: completalo nella scheda cliente.")
        sbagliati = [e for e in (cli["piva"] and controlla_piva(cli["piva"]), cli["cf"] and controlla_cf(cli["cf"])) if e]
        errori += [f"{e} Correggi la scheda del cliente prima di creare la fattura." for e in sbagliati]
    if not any(r["importo"] for r in righe):
        errori.append("Serve almeno una voce con l'importo.")
    if cli:
        tabella = K.codici()
        for r in righe:
            if r["importo"]:
                cod = K.codice_riga(r["codice_iva"], cli)
                k = tabella.get(cod)
                if not k:
                    errori.append(f"Il codice IVA {cod} non esiste: sceglilo dall'elenco.")
                elif k["natura"] == "N3.5" and not cli["intento_protocollo"]:
                    errori.append("Le voci con codice IVA N8c (esportatore abituale) richiedono la dichiarazione "
                                  "d'intento: inserisci protocollo e data nella scheda del cliente.")
    if dati["tipo"] == "TD04" and not dati["rif_numero"]:
        errori.append("Indica la fattura che la nota di credito storna (es. 22/2026).")
    if dati["valuta"]:
        if not dati["cambio"]:
            errori.append("Manca il cambio USD → EUR.")
        for r in righe:
            if r["importo"] and not r["prezzo_valuta"]:
                errori.append(f"Voce «{(r['descrizione'] or '')[:40]}»: manca il prezzo nella colonna Prezzo USD "
                              "(il prezzo in euro va nella colonna Prezzo EUR).")
        if not db.banca_predefinita("USD"):
            errori.append("Manca una banca in USD in Pagamenti e banche.")
    return list(dict.fromkeys(errori))


def salva_da_form(did=None):
    dati, righe, errori = leggi_form(request.form)
    esistente = db.documento_per_numero(dati["anno"], dati["numero"], dati.get("suffisso", ""))
    if esistente and esistente["id"] != did:
        errori.append(f"Il numero {numero_completo(dati)} è già usato da un altro "
                      + ("avviso." if dati["tipo"] == "AVV" else "documento."))
    if errori:
        return None, dati, righe, errori
    return db.salva_documento(dati, righe, did), dati, righe, []


def apri_nel_finder(percorso):
    """Sul Mac apre il Finder con il file selezionato."""
    if sys.platform == "darwin" and percorso and percorso.exists():
        subprocess.run(["open", "-R", str(percorso)], check=False)
        return True
    return False


# ---------------------------------------------------------------- documenti
@app.route("/")
def home():
    return redirect(url_for("documenti"))


GIORNI_INVIO = 12        # fattura immediata: trasmissione entro 12 giorni dalla data
GIORNI_RIINVIO = 5       # dopo uno scarto: nuovo invio entro 5 giorni dalla notifica
EMESSE = ("inviata", "consegnata", "mancata")


def scadenza_invio(d):
    """(data di scadenza, giorni che mancano) per i documenti non ancora inviati o scartati."""
    if d["stato"] == "scartata" and d["esito_il"]:
        limite = date.fromisoformat(d["esito_il"][:10]) + timedelta(days=GIORNI_RIINVIO)
    else:
        limite = date.fromisoformat(d["data"]) + timedelta(days=GIORNI_INVIO)
    return limite, (limite - date.today()).days


def da_pagare(d):
    """Quanto il cliente paga: il netto (totale meno ritenuta) se c'e', altrimenti il totale."""
    return Decimal(d["netto"] or d["totale"] or 0)


def stornato_per_fattura(elenco):
    """numero/anno della fattura -> importo delle note di credito emesse che la stornano."""
    out = {}
    for d in elenco:
        if d["tipo"] == "TD04" and d["stato"] != "bozza" and d["rif_numero"]:
            out[d["rif_numero"]] = out.get(d["rif_numero"], Decimal(0)) + da_pagare(d)
    return out


def da_incassare(elenco):
    """Fatture emesse non saldate, con il residuo al netto delle note di credito e degli acconti."""
    stornato = stornato_per_fattura(elenco)
    incassato = db.incassato()
    out = []
    for d in elenco:
        if d["tipo"] != "TD01" or d["stato"] not in EMESSE or d["saldato"]:
            continue
        incassi = incassato.get(d["id"], Decimal(0))
        residuo = da_pagare(d) - stornato.get(numero_completo(d), Decimal(0)) - incassi
        if residuo > 0:
            out.append({"d": d, "residuo": residuo, "parziale": residuo != da_pagare(d), "incassato": incassi,
                        "giorni": (date.today() - date.fromisoformat(d["data"])).days})
    return sorted(out, key=lambda x: x["d"]["data"])


def situazione_pagamento(doc):
    """Dovuto (al netto delle note di credito), incassi registrati e residuo di una fattura."""
    with db.conn() as c:
        nc = c.execute("SELECT * FROM documenti WHERE tipo = 'TD04' AND stato != 'bozza' AND rif_numero = ?",
                       (numero_completo(doc),)).fetchall()
    dovuto = da_pagare(doc) - sum((da_pagare(n) for n in nc), Decimal(0))
    incassi = db.incassi(doc["id"])
    incassato = sum((Decimal(i["importo"]) for i in incassi), Decimal(0))
    residuo = Decimal(0) if (doc["saldato"] and not incassi) else max(dovuto - incassato, Decimal(0))
    return {"dovuto": dovuto, "incassi": incassi, "incassato": incassato, "residuo": residuo}


def aggiorna_saldo(did):
    """Dopo un incasso: saldata (con la data dell'ultimo incasso) se non resta nulla da incassare."""
    doc, _ = db.documento(did)
    s = situazione_pagamento(doc)
    if s["incassi"] and s["incassato"] >= s["dovuto"]:
        db.aggiorna_documento(did, saldato=1, saldato_il=max(i["data"] for i in s["incassi"]))
        return True
    db.aggiorna_documento(did, saldato=0, saldato_il="")
    return False


GIORNI_SENZA_ESITO = 3   # oltre: l'invio va controllato (PEC persa? file non elaborato?)


def da_inviare(elenco):
    out = []
    for d in elenco:
        if d["stato"] in ("bozza", "generata", "scartata") and not d["storico"]:
            limite, giorni = scadenza_invio(d)
            out.append({"d": d, "limite": limite, "giorni": giorni, "attesa": None})
        elif d["stato"] == "inviata" and not d["storico"] and d["inviato_il"]:
            attesa = (date.today() - date.fromisoformat(d["inviato_il"][:10])).days
            if attesa >= GIORNI_SENZA_ESITO:
                out.append({"d": d, "limite": date.fromisoformat(d["inviato_il"][:10]), "giorni": -1,
                            "attesa": attesa})
    return sorted(out, key=lambda x: x["limite"])


VISTE = {"tutti": "Tutti", "invio": "Da inviare", "sdi": "Inviati allo SDI", "incassare": "Da incassare",
         "avvisi": "Avvisi di fattura"}


def totali_anno(docs):
    """Somme dell'anno sulle fatture inviate allo SDI, al netto delle note di credito (bozze e avvisi esclusi).
    Imponibile e IVA sono quelli registrati alla generazione (o nello storico); se mancano si ricalcolano."""
    s = {"imponibile": Decimal(0), "iva": Decimal(0), "totale": Decimal(0), "fatture": 0, "note": 0}
    studio = db.studio()
    for d in docs:
        if d["tipo"] not in ("TD01", "TD04") or d["stato"] not in EMESSE:
            continue
        segno = -1 if d["tipo"] == "TD04" else 1
        s["note" if segno < 0 else "fatture"] += 1
        imp, iva = (d["imponibile"] or "").strip(), (d["iva"] or "").strip()
        if not (imp and iva):
            doc, righe = db.documento(d["id"])
            try:
                _, tot = modello_fattura(doc, righe, db.cliente(doc["cliente_id"]), studio, "00000")
                imp, iva = tot["imponibile"], tot["iva"]
            except (Errore, ValueError):
                imp, iva = 0, 0
        s["imponibile"] += segno * Decimal(imp)
        s["iva"] += segno * Decimal(iva)
        s["totale"] += segno * Decimal(d["totale"] or 0)
    return s


@app.route("/documenti")
def documenti():
    anni = db.anni()
    anno = request.args.get("anno", type=int) or (anni[0] if anni else date.today().year)
    cerca = request.args.get("q", "").strip()
    stato = request.args.get("stato", "")
    vista = request.args.get("vista", "tutti")
    vista = vista if vista in VISTE else "tutti"
    tutti = db.documenti(None, cerca)            # tutti gli anni: servono a "da inviare" e "da incassare"
    avvisi = [d for d in tutti if d["tipo"] == "AVV"]     # fuori dalla numerazione e dallo SDI
    tutti = [d for d in tutti if d["tipo"] != "AVV"]
    invio, incasso = da_inviare(tutti), da_incassare(tutti)
    dell_anno = [d for d in tutti if d["anno"] == anno]
    conteggi = {}
    for d in dell_anno:
        conteggi[d["stato"]] = conteggi.get(d["stato"], 0) + 1
    elenco = [d for d in dell_anno if d["stato"] == stato] if stato else dell_anno
    sdi = [d for d in dell_anno if d["stato"] in EMESSE + ("scartata",)]
    stornato = stornato_per_fattura(tutti)
    stornate = {d["id"] for d in dell_anno if d["tipo"] == "TD01"
                and stornato.get(numero_completo(d), Decimal(0)) >= da_pagare(d)}
    if anno not in anni:
        anni = sorted(set(anni) | {anno}, reverse=True)
    return render_template("documenti.html", elenco=elenco, anni=anni, anno=anno, cerca=cerca, stato=stato,
                           conteggi=conteggi, vista=vista, viste=VISTE, invio=invio, incasso=incasso, sdi=sdi,
                           totale_incasso=sum((x["residuo"] for x in incasso), Decimal(0)),
                           urgenti=sum(1 for x in invio if x["giorni"] <= 3), stornate=stornate, EMESSE=EMESSE,
                           ultimo_controllo=db.impostazione("pec.ultimo_controllo"), acconti=db.incassato(),
                           avvisi=avvisi, avvisi_aperti=sum(1 for a in avvisi if a["stato"] == "bozza"),
                           fatture_da_avviso={a["collegato_id"]: db.documento(a["collegato_id"])[0]
                                              for a in avvisi if a["collegato_id"]},
                           in_attesa=sum(1 for d in tutti if d["stato"] == "inviata" and not d["storico"]),
                           con_pdf={d["id"] for d in dell_anno if d["file_pdf"]} | db.con_voci(),
                           somme=totali_anno(dell_anno) if vista == "tutti" and not cerca else None)


def ritorno():
    r = request.form.get("ritorno", "")
    return r if r.startswith("/") and not r.startswith("//") else ""


@app.route("/documento/<int:did>/saldo", methods=["POST"])
def saldo(did):
    doc, _ = db.documento(did)
    if not doc or doc["tipo"] != "TD01" or doc["stato"] == "bozza":
        abort(400)
    azione = request.form.get("azione")
    if azione == "annulla":
        db.elimina_incassi(did)
        db.aggiorna_documento(did, saldato=0, saldato_il="")
        flash(f"{nome_documento(doc)}: di nuovo da incassare, incassi cancellati.", "ok")
        return redirect(ritorno() or url_for("documento", did=did))
    if azione == "togli":
        db.elimina_incasso(did, request.form.get("incasso", type=int))
        aggiorna_saldo(did)
        flash("Incasso tolto.", "ok")
        return redirect(ritorno() or url_for("documento", did=did))
    data = request.form.get("saldato_il") or date.today().isoformat()
    try:
        date.fromisoformat(data)
    except ValueError:
        flash("La data non è valida.", "errore")
        return redirect(ritorno() or url_for("documento", did=did))
    if azione == "data":                         # saldo registrato senza incassi (es. storico): cambia la data
        db.aggiorna_documento(did, saldato=1, saldato_il=data)
        flash(f"{nome_documento(doc)} saldata il {data_it(data)}.", "ok")
        return redirect(ritorno() or url_for("documento", did=did))
    s = situazione_pagamento(doc)
    try:
        imp = importo(request.form.get("importo")) if (request.form.get("importo") or "").strip() else s["residuo"]
    except ValueError:
        imp = None
    if imp is None or imp <= 0:
        flash("Scrivi l'importo incassato, ad esempio 500,00.", "errore")
        return redirect(ritorno() or url_for("documento", did=did))
    if imp > s["residuo"]:
        flash(f"L'importo supera quanto resta da incassare ({euro(s['residuo'])}).", "errore")
        return redirect(ritorno() or url_for("documento", did=did))
    db.aggiungi_incasso(did, data, imp, (request.form.get("note") or "").strip())
    if aggiorna_saldo(did):
        flash(f"{nome_documento(doc)} saldata il {data_it(data)}.", "ok")
    else:
        resta = situazione_pagamento(db.documento(did)[0])["residuo"]
        flash(f"{nome_documento(doc)}: incassati {euro(imp)} il {data_it(data)}, restano {euro(resta)}.", "ok")
    return redirect(ritorno() or url_for("documento", did=did))


def pagina_editor(doc, righe, errori=None, dati=None):
    clienti = db.clienti()
    mappa = {c["id"]: {"nome": c["denominazione"], "dettagli": dettagli_cliente(c)} for c in clienti}
    mappa = {c["id"]: {"nome": c["denominazione"], "dettagli": dettagli_cliente(c),
                       "codice": K.codice_riga("", c), "pagamento": K.nome_pagamento({"pagamento": ""}, c),
                       "estero": estero(c)} for c in clienti}
    return render_template("documento.html", doc=dati or doc, righe=righe, clienti=clienti,
                           mappa_clienti=mappa, errori=errori or [], esistente=doc,
                           codici=db.codici_iva(), pagamenti=db.pagamenti(), banche=db.banche())


def dettagli_cliente(c):
    parti = []
    if estero(c):
        parti.append(f"{c['nazione']}, " + (f"ID fiscale {c['id_estero'] or c['piva']}" if (c["id_estero"] or c["piva"])
                                            else "senza identificativo fiscale"))
    else:
        if c["piva"]:
            parti.append(f"P.IVA {c['piva']}")
        if c["cf"] and c["cf"] != c["piva"]:
            parti.append(f"C.F. {c['cf']}")
        if c["codice_destinatario"]:
            parti.append(f"Codice destinatario {c['codice_destinatario']}")
        elif c["pec"]:
            parti.append(f"PEC {c['pec']}")
    parti.append(f"IVA {c['codice_iva'] or C.CODICE_IVA_PREDEFINITO}")
    if c["pagamento"]:
        parti.append(c["pagamento"])
    if c["intento_protocollo"]:
        parti.append(f"dichiarazione d'intento del {data_it(c['intento_data'])}")
    if privato(c):
        parti.append("Privato")
    return ", ".join(parti)


@app.route("/documento/nuovo", methods=["GET", "POST"])
def documento_nuovo():
    if request.method == "POST":
        did, dati, righe, errori = salva_da_form()
        if errori:
            return pagina_editor(None, righe, errori, dati)
        return dopo_salvataggio(did)
    copia = request.args.get("copia", type=int)
    if copia:
        return nuovo_da_copia(copia)
    tipo = request.args.get("tipo") if request.args.get("tipo") in ("TD04", "AVV") else "TD01"
    origine = request.args.get("da", type=int)
    if tipo == "TD04" and not origine and not request.args.get("libera"):
        return redirect(url_for("scegli_fattura"))   # prima si sceglie la fattura da stornare
    oggi = date.today()
    dati = {"tipo": tipo, "anno": oggi.year, "numero": prossimo(tipo, oggi.year),
            "data": oggi.isoformat(), "cliente_id": None, "terzo_pagatore": "", "note": "", "bollo": 0,
            "rif_numero": "", "rif_data": "", "stato": "bozza", "pagamento": "", "banca_id": None,
            "valuta": "", "cambio": ""}
    righe = [{"tipo": "onorario", "descrizione": "", "importo": ""}]
    if origine:                                   # nota di credito a partire da una fattura
        o, r = db.documento(origine)
        if o:
            dati.update(cliente_id=o["cliente_id"], rif_numero=numero_completo(o), rif_data=o["data"],
                        valuta=o["valuta"] or "", cambio=o["cambio"] or "", banca_id=o["banca_id"])
            righe = [dict(x) for x in r] or righe
    cid = request.args.get("cliente", type=int)
    if cid:
        dati["cliente_id"] = cid
    return pagina_editor(None, righe, dati=dati)


@app.route("/nota-di-credito")
def scegli_fattura():
    """Primo passo della nota di credito: la fattura da stornare, da cui si copiano cliente e voci."""
    cerca = request.args.get("q", "").strip()
    tutti = db.documenti(None, cerca)
    stornato = stornato_per_fattura(db.documenti(None, ""))
    fatture = []
    for d in tutti:
        if d["tipo"] == "TD01" and d["stato"] in EMESSE:
            gia = stornato.get(numero_completo(d), Decimal(0))
            fatture.append({"d": d, "stornato": gia, "tutta": gia >= da_pagare(d)})
    return render_template("scegli_fattura.html", fatture=fatture[:200], cerca=cerca)


def nuovo_da_copia(did):
    """Duplica fattura: stessa intestazione e stesse voci, numero nuovo e data di oggi."""
    o, r = db.documento(did)
    if not o:
        abort(404)
    oggi = date.today()
    dati = {"tipo": o["tipo"], "anno": oggi.year, "numero": prossimo(o["tipo"], oggi.year), "data": oggi.isoformat(),
            "cliente_id": o["cliente_id"], "terzo_pagatore": o["terzo_pagatore"], "note": o["note"],
            "bollo": 0, "rif_numero": o["rif_numero"], "rif_data": o["rif_data"], "stato": "bozza",
            "pagamento": o["pagamento"] or "", "banca_id": o["banca_id"], "valuta": o["valuta"] or "",
            "cambio": "", "copia_di": nome_documento(o)}
    return pagina_editor(None, [dict(x) for x in r], dati=dati)


def avviso_lettera(doc):
    """Numero con lettera (24/A): ricorda dove deve stare la data rispetto ai numeri vicini."""
    if doc["tipo"] == "AVV" or not doc["suffisso"]:
        return
    with db.conn() as c:
        prima = c.execute("SELECT * FROM documenti WHERE anno = ? AND tipo != 'AVV' AND id != ? AND "
                          "(numero < ? OR (numero = ? AND suffisso < ?)) ORDER BY numero DESC, suffisso DESC LIMIT 1",
                          (doc["anno"], doc["id"], doc["numero"], doc["numero"], doc["suffisso"])).fetchone()
        dopo = c.execute("SELECT * FROM documenti WHERE anno = ? AND tipo != 'AVV' AND id != ? AND "
                         "(numero > ? OR (numero = ? AND suffisso > ?)) ORDER BY numero, suffisso LIMIT 1",
                         (doc["anno"], doc["id"], doc["numero"], doc["numero"], doc["suffisso"])).fetchone()
    testo = f"Numero {numero_completo(doc)} aggiunto fuori sequenza."
    if prima and prima["data"] > doc["data"]:
        testo += f" La data è precedente a quella della n. {numero_completo(prima)} ({data_it(prima['data'])})."
    if dopo and dopo["data"] < doc["data"]:
        testo += f" La data è successiva a quella della n. {numero_completo(dopo)} ({data_it(dopo['data'])})."
    giorni = (date.today() - date.fromisoformat(doc["data"])).days
    if giorni > GIORNI_INVIO:
        testo += f" La data è di {giorni} giorni fa: l'invio oltre i {GIORNI_INVIO} giorni è tardivo."
    flash(testo, "avviso")


def dopo_salvataggio(did):
    avviso_lettera(db.documento(did)[0])
    if request.form.get("azione") == "genera" and request.form.get("tipo") != "AVV":
        return genera(did)
    flash("Avviso salvato." if request.form.get("tipo") == "AVV" else "Bozza salvata.", "ok")
    return redirect(url_for("documento", did=did))


@app.route("/documento/<int:did>", methods=["GET", "POST"])
def documento(did):
    doc, righe = db.documento(did)
    if not doc:
        abort(404)
    if request.method == "POST":
        if doc["stato"] != "bozza":
            flash("Il documento è già stato generato: per modificarlo riportalo in bozza.", "errore")
            return redirect(url_for("documento", did=did))
        _, dati, nuove, errori = salva_da_form(did)
        if errori:
            dati.update(id=did, stato="bozza")
            return pagina_editor(doc, nuove, errori, dati)
        return dopo_salvataggio(did)
    if doc["stato"] == "bozza":
        return pagina_editor(doc, [dict(r) for r in righe])
    if doc["tipo"] == "AVV":
        fattura = db.documento(doc["collegato_id"])[0] if doc["collegato_id"] else None
        return render_template("avviso.html", doc=doc, righe=righe, fattura=fattura,
                               cli=db.cliente(doc["cliente_id"]) if doc["cliente_id"] else None)
    cli = db.cliente(doc["cliente_id"]) if doc["cliente_id"] else None
    if doc["storico"]:
        f = tot = None                           # programma precedente: totali registrati, voci solo da leggere
    else:
        f, tot = modello_fattura(doc, righe, cli, db.studio(), doc["progressivo"] or "00000")
    collegate = []
    if doc["tipo"] == "TD01":
        with db.conn() as c:
            collegate = c.execute("SELECT * FROM documenti WHERE tipo = 'TD04' AND rif_numero = ?",
                                  (numero_completo(doc),)).fetchall()
    pdf_valuta = percorso_dati(doc["file_pdf_valuta"]) if doc["file_pdf_valuta"] else None
    pagamento = situazione_pagamento(doc) if doc["tipo"] == "TD01" and doc["stato"] != "bozza" else None
    pdf = percorso_dati(doc["file_pdf"])
    pdf = pdf if pdf and pdf.exists() else None
    pdf_ricostruito = not pdf and any((r["importo"] or "").strip() for r in righe)
    return render_template("scheda.html", doc=doc, righe=righe, cli=cli, tot=tot, f=f, pag=pagamento,
                           xml=percorso_dati(doc["file_xml"]), pdf=pdf, pdf_ricostruito=pdf_ricostruito,
                           pdf_valuta=pdf_valuta, collegate=collegate, mac=sys.platform == "darwin",
                           totale_valuta=sum((Decimal(r["importo_valuta"]) for r in righe if r["importo_valuta"]),
                                             Decimal(0)))


MODO_PDF = {"MP05": "Bonifico bancario", "MP01": "Contanti", "MP12": "Ricevuta bancaria (RiBa)"}


def opzioni_pdf(doc, f, tot, studio, valuta="EUR", bozza=False):
    pag = tot["pagamento"]
    modo = MODO_PDF.get(pag["modalita"], db.MODALITA.get(pag["modalita"], "")) if pag else "Bonifico bancario"
    extra = {"tel": studio["telefono"], "email": studio["email"], "pec": studio["pec"], "web": studio["web"],
             "note_pie": "", "bollo": tot["bollo_dovuto"] and valuta == "EUR",
             "descr_codici": {k: v["descrizione"] for k, v in tot["codici"].items()},
             "logo": C.LOGO if C.LOGO.exists() else None, "bozza": bozza,
             "modalita": modo, "banca": tot["banca"], "valuta": valuta}
    if valuta != "EUR":
        cambio = Decimal(doc["cambio"])
        extra["nota_valuta"] = (f"Importi in dollari statunitensi ({valuta}). Fattura elettronica trasmessa al "
                                f"Sistema di Interscambio in euro al cambio 1 {valuta} = "
                                f"{str(cambio.normalize()).replace('.', ',')} EUR.")
    return extra


def crea_pdf_documento(percorso, doc, righe, cli, studio, valuta="EUR", bozza=False, progressivo="00000"):
    f, tot = modello_fattura(doc, righe, cli, studio, progressivo, valuta if valuta != "EUR" else None)
    crea_pdf(percorso, f, riepilogo(f), opzioni_pdf(doc, f, tot, studio, valuta, bozza))
    return f, tot


def genera(did):
    doc, righe = db.documento(did)
    cli = db.cliente(doc["cliente_id"]) if doc["cliente_id"] else None
    errori = controlla_per_generare(doc, [dict(r) for r in righe], cli)
    if errori:
        for e in errori:
            flash(e, "errore")
        return redirect(url_for("documento", did=did))
    studio = db.studio()
    try:
        f, tot = modello_fattura(doc, righe, cli, studio, db.prossimo_progressivo(consuma=False))
        costruisci_xml(f)                                  # controlli prima di consumare il progressivo
    except (Errore, ValueError) as e:
        flash(f"Il documento non può essere generato: {e}", "errore")
        return redirect(url_for("documento", did=did))
    progressivo = db.prossimo_progressivo()
    cartella = cartella_mese(doc)
    cartella.mkdir(parents=True, exist_ok=True)
    prefisso = prefisso_file(doc["tipo"])
    base = f"{prefisso}_{numero_file(doc)}-{doc['anno']}_{slug(cli['denominazione'])}"
    pdf = cartella / f"{base}.pdf"
    f, tot = crea_pdf_documento(pdf, doc, righe, cli, studio, progressivo=progressivo)
    if getattr(C, "ALLEGA_PDF", False):
        f["allegati"] = [{"nome": pdf.name, "formato": "PDF", "descrizione": "Copia di cortesia",
                          "dati": pdf.read_bytes()}]
    tree, _, avvisi = costruisci_xml(f)
    xml = cartella / nome_file(f)
    tree.write(str(xml), xml_declaration=True, encoding="UTF-8", pretty_print=True)
    pdf_valuta = ""
    if doc["valuta"]:
        pv = cartella / f"{base}_{doc['valuta']}.pdf"
        crea_pdf_documento(pv, doc, righe, cli, studio, valuta=doc["valuta"], progressivo=progressivo)
        pdf_valuta = relativo(pv)
    db.aggiorna_documento(did, stato="generata", progressivo=progressivo, file_xml=relativo(xml),
                          file_pdf=relativo(pdf), file_pdf_valuta=pdf_valuta, generato_il=db.adesso(),
                          totale=str(tot["totale"]), netto=str(tot["totale"]),
                          imponibile=str(tot["imponibile"]), iva=str(tot["iva"]))
    for a in avvisi:
        flash(a, "avviso")
    flash(f"{nome_documento(doc)} generata: ora inviala allo SDI.", "ok")
    return redirect(url_for("documento", did=did))


@app.route("/documento/anteprima", methods=["POST"])
def anteprima():
    """PDF di controllo dai dati del modulo, senza salvare e senza toccare la numerazione."""
    dati, righe, errori = leggi_form(request.form)
    cli = db.cliente(dati["cliente_id"]) if dati["cliente_id"] else None
    errori += controlla_per_generare(dati, righe, cli)
    if errori:
        return render_template("errore.html", errori=list(dict.fromkeys(errori))), 400
    valuta = "USD" if request.form.get("copia") == "USD" and dati["valuta"] else "EUR"
    studio = db.studio()
    ANTEPRIME.mkdir(parents=True, exist_ok=True)
    prefisso = prefisso_file(dati["tipo"])
    nome = f"{prefisso}_{numero_file(dati)}-{dati['anno']}_{slug(cli['denominazione'])}{'_' + valuta if valuta != 'EUR' else ''}.pdf"
    pdf = ANTEPRIME / nome
    try:
        # senza la scritta BOZZA: il PDF si manda al cliente anche prima dell'invio allo SDI
        f, _ = crea_pdf_documento(pdf, dati, righe, cli, studio, valuta=valuta, bozza=False)
        if dati["tipo"] != "AVV":                 # l'avviso non va allo SDI: niente XML
            f_eur, _ = modello_fattura(dati, righe, cli, studio, "00000")
            costruisci_xml(f_eur)                 # stessi controlli della generazione
    except (Errore, ValueError) as e:
        return render_template("errore.html", errori=[str(e)]), 400
    return send_file(pdf, mimetype="application/pdf", download_name=nome)


@app.route("/documento/<int:did>/pdf")
def apri_pdf(did):
    """La copia PDF salvata alla generazione; per le fatture importate dal programma precedente, che non
    ne hanno una, la ricostruisce dai dati in archivio (voci, codici IVA, cliente) con l'impaginazione attuale."""
    doc, righe = db.documento(did)
    if not doc:
        abort(404)
    in_valuta = request.args.get("copia") == "valuta"
    p = percorso_dati(doc["file_pdf_valuta" if in_valuta else "file_pdf"])
    if p and p.exists():
        return send_file(p, mimetype="application/pdf", download_name=p.name)
    if doc["stato"] == "bozza" or not any((r["importo"] or "").strip() for r in righe):
        flash("Per questo documento non c'è una copia PDF: è stato importato con i soli totali, senza le voci.",
              "avviso")
        return redirect(url_for("documento", did=did))
    cli = db.cliente(doc["cliente_id"])
    valuta = (doc["valuta"] or "USD") if in_valuta else "EUR"
    ANTEPRIME.mkdir(parents=True, exist_ok=True)
    nome = (f"{prefisso_file(doc['tipo'])}_{numero_file(doc)}-{doc['anno']}_{slug(cli['denominazione'])}"
            f"{'_' + valuta if in_valuta else ''}.pdf")
    try:
        crea_pdf_documento(ANTEPRIME / nome, doc, righe, cli, db.studio(), valuta,
                           progressivo=doc["progressivo"] or "00000")
    except (Errore, ValueError) as e:
        flash(f"La copia PDF non si può ricostruire: {e}", "errore")
        return redirect(url_for("documento", did=did))
    return send_file(ANTEPRIME / nome, mimetype="application/pdf", download_name=nome)


@app.route("/documento/<int:did>/xml")
def scarica_xml(did):
    doc, _ = db.documento(did)
    p = percorso_dati(doc["file_xml"]) if doc else None
    if not p or not p.exists():
        abort(404)
    return send_file(p, mimetype="application/xml", as_attachment=True, download_name=p.name)


def invia_documento(doc):
    """Invia un documento generato allo SDI via PEC. Restituisce (inviato, messaggio)."""
    if not doc or doc["stato"] != "generata":
        return False, "Si può inviare solo un documento generato e non ancora inviato."
    attesa = pec.primo_invio_in_attesa()
    if attesa:
        return False, (f"Primo invio allo SDI da questa PEC: prima di inviare altro aspetta la ricevuta della "
                       f"{nome_documento(attesa).lower()} (di solito arriva in poche ore). Con la ricevuta lo SDI "
                       "assegna l'indirizzo dedicato e il programma lo usa da solo per gli invii successivi. "
                       "Per controllare subito premi «Aggiorna esiti SDI».")
    xml = percorso_dati(doc["file_xml"])
    if not xml or not xml.exists():
        return False, f"{nome_documento(doc)}: il file XML non si trova più nella cartella dei documenti, rigeneralo."
    try:
        dest = pec.invia(doc, xml)
    except pec.ErrorePec as e:
        return False, f"{nome_documento(doc)}: {e}"
    db.aggiorna_documento(doc["id"], stato="inviata", inviato_il=db.adesso(), esito_note=f"PEC a {dest}")
    return True, dest


@app.route("/documento/<int:did>/invia", methods=["POST"])
def invia_pec(did):
    doc, _ = db.documento(did)
    ok, msg = invia_documento(doc)
    if ok:
        flash(f"{nome_documento(doc)} inviata allo SDI via PEC. L'esito arriva di solito in poche ore: "
              "il programma controlla la PEC da solo ogni 30 minuti.", "ok")
    else:
        flash(msg, "errore")
    return redirect(url_for("documento", did=did))


@app.route("/invia-tutte", methods=["POST"])
def invia_tutte():
    """Invio multiplo: tutte le fatture e note di credito pronte (generate e non inviate), in ordine di numero."""
    with db.conn() as c:
        pronte = c.execute("SELECT * FROM documenti WHERE stato = 'generata' AND tipo != 'AVV' "
                           "ORDER BY anno, numero, suffisso").fetchall()
    inviate, fermo = [], None
    for doc in pronte:
        ok, msg = invia_documento(doc)
        if not ok:
            fermo = msg
            break
        inviate.append(numero_completo(doc))
    if inviate:
        flash(f"Inviati allo SDI: {', '.join(inviate)}. Gli esiti arrivano di solito in poche ore.", "ok")
    if fermo:
        flash(fermo, "avviso" if pec.primo_invio_in_attesa() else "errore")
    elif not pronte:
        flash("Non ci sono documenti pronti da inviare.", "avviso")
    return redirect(url_for("documenti", vista="invio"))


@app.route("/esiti", methods=["POST"])
def aggiorna_esiti():
    try:
        cambiamenti, avvisi = pec.aggiorna_esiti()
    except pec.ErrorePec as e:
        flash(str(e), "errore")
        return redirect(ritorno() or url_for("documenti"))
    db.salva_impostazione("pec.ultimo_controllo", db.adesso())
    for d, stato, dettaglio in cambiamenti:
        flash(f"{nome_documento(d)}: {C.STATI[stato].lower()}" + (f" ({dettaglio})" if dettaglio else ""),
              "errore" if stato == "scartata" else "ok")
    for a in avvisi:
        flash(a, "avviso")
    if not cambiamenti and not avvisi:
        with db.conn() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM documenti WHERE stato = 'inviata'").fetchone()["n"]
        flash("Nessun esito nuovo." + (f" In attesa: {n}." if n else ""), "ok")
    return redirect(ritorno() or url_for("documenti"))


@app.route("/documento/<int:did>/mostra", methods=["POST"])
def mostra_file(did):
    doc, _ = db.documento(did)
    if not apri_nel_finder(percorso_dati(doc["file_xml"])):
        flash("Il file è nella cartella indicata qui sotto.", "avviso")
    return redirect(url_for("documento", did=did))


@app.route("/documento/<int:did>/stato", methods=["POST"])
def cambia_stato(did):
    doc, _ = db.documento(did)
    azione = request.form.get("azione")
    if azione == "inviata" and doc["stato"] == "generata":
        db.aggiorna_documento(did, stato="inviata", inviato_il=db.adesso())
        flash("Segnata come inviata. Quando lo SDI risponde, registra l'esito.", "ok")
    elif azione == "esito" and doc["stato"] in ("generata", "inviata", "consegnata", "mancata", "scartata"):
        esito = request.form.get("esito")
        if esito not in ("consegnata", "mancata", "scartata"):
            flash("Scegli l'esito.", "errore")
        else:
            db.aggiorna_documento(did, stato=esito, esito_il=db.adesso(),
                                  inviato_il=doc["inviato_il"] or db.adesso(),
                                  id_sdi=request.form.get("id_sdi", "").strip(),
                                  esito_note=request.form.get("esito_note", "").strip())
            flash(f"Esito registrato: {C.STATI[esito]}.", "ok")
    elif azione == "bozza" and doc["stato"] in ("generata", "scartata"):
        db.aggiorna_documento(did, stato="bozza")
        flash("Riportato in bozza: correggi e genera di nuovo (verrà creato un file XML nuovo).", "ok")
    else:
        flash("Operazione non consentita in questo stato.", "errore")
    return redirect(url_for("documento", did=did))


@app.route("/documento/<int:did>/converti", methods=["POST"])
def converti_avviso(did):
    """Avviso pagato: diventa una fattura (primo numero libero, data di oggi), gia' saldata."""
    av, righe = db.documento(did)
    if not av or av["tipo"] != "AVV" or av["stato"] != "bozza":
        flash("Si può trasformare in fattura solo un avviso ancora aperto.", "errore")
        return redirect(url_for("documento", did=did))
    data_pag = request.form.get("data_pagamento") or date.today().isoformat()
    try:
        date.fromisoformat(data_pag)
    except ValueError:
        flash("La data del pagamento non è valida.", "errore")
        return redirect(url_for("documento", did=did))
    oggi = date.today()
    dati = {k: av[k] for k in db.CAMPI_DOC if k in av.keys()}
    dati.update(tipo="TD01", anno=oggi.year, numero=db.prossimo_numero(oggi.year), suffisso="",
                data=oggi.isoformat(), rif_numero="", rif_data="", totale=av["totale"], netto=av["netto"])
    nuovo = db.salva_documento(dati, [dict(r) for r in righe])
    pagato = av["netto"] or av["totale"]
    if pagato:
        db.aggiungi_incasso(nuovo, data_pag, Decimal(pagato), f"Avviso n. {numero_completo(av)}")
    db.aggiorna_documento(nuovo, saldato=1, saldato_il=data_pag)
    db.aggiorna_documento(did, stato="convertito", collegato_id=nuovo, saldato=1, saldato_il=data_pag)
    flash(f"Dall'avviso n. {numero_completo(av)} è nata la fattura n. {dati['numero']}/{oggi.year}, già saldata il "
          f"{data_it(data_pag)}. Controlla data e voci, poi generala e inviala allo SDI.", "ok")
    return redirect(url_for("documento", did=nuovo))


@app.route("/documento/<int:did>/avviso.pdf")
def pdf_avviso(did):
    doc, righe = db.documento(did)
    if not doc or doc["tipo"] != "AVV":
        abort(404)
    cli = db.cliente(doc["cliente_id"])
    ANTEPRIME.mkdir(parents=True, exist_ok=True)
    nome = f"Avviso_{doc['numero']}-{doc['anno']}_{slug(cli['denominazione'])}.pdf"
    pdf = ANTEPRIME / nome
    crea_pdf_documento(pdf, doc, righe, cli, db.studio())
    return send_file(pdf, mimetype="application/pdf", download_name=nome)


@app.route("/documento/<int:did>/elimina", methods=["POST"])
def elimina(did):
    doc, _ = db.documento(did)
    if doc and doc["stato"] == "bozza":
        con_lettera = doc["tipo"] != "AVV" and doc["suffisso"]
        with db.conn() as c:
            dopo = None if con_lettera else c.execute("SELECT MIN(numero) AS n FROM documenti WHERE anno = ? AND numero > ? AND id != ? "
                             "AND (tipo = 'AVV') = ?", (doc["anno"], doc["numero"], did,
                                                        int(doc["tipo"] == "AVV"))).fetchone()["n"]
            riaperto = c.execute("SELECT * FROM documenti WHERE tipo = 'AVV' AND collegato_id = ?", (did,)).fetchone()
            c.execute("UPDATE documenti SET stato = 'bozza', collegato_id = NULL, saldato = 0, saldato_il = '' "
                      "WHERE tipo = 'AVV' AND collegato_id = ?", (did,))
        db.elimina_documento(did)
        if riaperto:
            flash(f"L'avviso n. {numero_completo(riaperto)} torna aperto.", "ok")
        if con_lettera:
            flash(f"Bozza {numero_completo(doc)} eliminata.", "ok")
        elif dopo:
            # numerazione senza buchi: il numero liberato va riusato, con una data coerente
            flash(f"{'Avviso' if doc['tipo'] == 'AVV' else 'Bozza'} {doc['numero']}/{doc['anno']} {'eliminato' if doc['tipo'] == 'AVV' else 'eliminata'}. Attenzione: esiste già il n. {dopo}, quindi il "
                  f"{doc['numero']} resta libero. Usalo per la prossima fattura (scrivilo nel campo Numero) con una "
                  f"data non successiva a quella del n. {dopo}.", "avviso")
        else:
            flash(f"{'Avviso' if doc['tipo'] == 'AVV' else 'Bozza'} {doc['numero']}/{doc['anno']} {'eliminato' if doc['tipo'] == 'AVV' else 'eliminata'}: "
                  f"il numero {doc['numero']} verrà riproposto.", "ok")
    return redirect(url_for("documenti", anno=doc["anno"] if doc else None))


@app.route("/api/calcola", methods=["POST"])
def api_calcola():
    """Riepilogo in tempo reale per il modulo: gruppi IVA, totale, scadenze, totale in dollari."""
    js = request.get_json(force=True)
    cli = db.cliente(int(js["cliente_id"])) if str(js.get("cliente_id") or "").isdigit() else None
    tabella = K.codici()
    righe, errati = [], []
    for i, r in enumerate(js.get("righe", [])):
        try:
            v, vv = importo(r.get("importo")), importo(r.get("importo_valuta"))
        except ValueError:
            v = vv = None
            errati.append(i)
        if v is None:
            continue
        righe.append({"descrizione": "", "importo": v, "quantita": None, "prezzo": None, "um": "",
                      "codice_iva": r.get("codice") or "", "prezzo_valuta": None, "importo_valuta": vv})
    out = {"errati": errati, "gruppi": [], "scadenze": [], "codice_cliente": K.codice_riga("", cli)}
    try:
        ls = K.linee(righe, cli, tabella)
    except ValueError as e:
        out["errore"] = str(e)
        ls = []
    t = K.totali(ls, tabella) if ls else {"imponibile": 0, "iva": 0, "totale": 0, "gruppi": [], "bollo_dovuto": False}
    out.update(imponibile=euro(t["imponibile"]), iva=euro(t["iva"]), totale=euro(t["totale"]),
               bollo=t["bollo_dovuto"])
    codice_di = {}
    for l in ls:
        codice_di.setdefault((l["aliquota"], l["natura"], l["rif_norm"]), l["codice"])
    for g in t["gruppi"]:
        cod = codice_di.get((g["aliquota"], g["natura"], g["rif_norm"]), "")
        out["gruppi"].append({"testo": (f"{cod}: " if cod else "") + (g["rif_norm"] if g["natura"] else f"IVA {g['aliquota']:g}%"),
                              "imponibile": euro(g["imponibile"]), "imposta": euro(g["imposta"])})
    if js.get("tipo") != "TD04" and ls and js.get("data"):
        try:
            pag = db.pagamento(nome=js.get("pagamento") or K.nome_pagamento({"pagamento": ""}, cli))
            out["scadenze"] = [{"data": data_it(d), "importo": euro(imp)}
                               for d, imp in K.scadenze(js["data"], pag, t["totale"])]
        except ValueError:
            pass
    if js.get("valuta"):
        tot_v = sum((r["importo_valuta"] for r in righe if r["importo_valuta"] is not None), Decimal(0))
        out["totale_valuta"] = in_valuta(tot_v, js["valuta"])
    return jsonify(out)


# ---------------------------------------------------------------- clienti
def leggi_cliente(form):
    d = {k: (form.get(k) or "").strip() for k in db.CAMPI_CLIENTE}
    d["nazione"] = (d["nazione"] or "IT").upper()
    d["provincia"] = d["provincia"].upper()
    d["cf"] = re.sub(r"\s", "", d["cf"]).upper()
    d["codice_destinatario"] = d["codice_destinatario"].upper()
    d["id_estero"] = re.sub(r"\s", "", d["id_estero"]).upper()
    errori = []
    if not d["denominazione"]:
        errori.append("Scrivi la ragione sociale o il nome.")
    if not re.fullmatch(r"[A-Z]{2}", d["nazione"]):
        errori.append("La nazione è la sigla di due lettere (IT, DE, CH, US…).")
    if d["nazione"] == "IT":
        d["piva"] = pulisci_piva(d["piva"])
        d["id_estero"] = ""
        if not (d["cf"] or d["piva"]):
            errori.append("Serve il codice fiscale (privati) o la partita IVA.")
        errori += [e for e in (d["piva"] and controlla_piva(d["piva"]), d["cf"] and controlla_cf(d["cf"])) if e]
        if d["cap"] and not re.fullmatch(r"\d{5}", d["cap"]):
            errori.append("Il CAP ha 5 cifre.")
        if d["codice_destinatario"] and not re.fullmatch(r"[A-Z0-9]{7}", d["codice_destinatario"]):
            errori.append("Il codice destinatario ha 7 caratteri.")
    else:
        d["piva"] = re.sub(r"\s", "", d["piva"]).upper()
        d["provincia"] = ""
        d["codice_destinatario"] = ""          # all'estero l'XML usa sempre XXXXXXX
        d["pec"] = ""
        d["intento_protocollo"] = d["intento_data"] = ""
    if not (d["indirizzo"] and d["comune"]):
        errori.append("Indirizzo e comune sono obbligatori nella fattura elettronica.")
    if d["pagamento"] and not db.pagamento(nome=d["pagamento"]):
        errori.append(f"Il pagamento «{d['pagamento']}» non esiste.")
    if d["codice_iva"] and not db.codice_iva(d["codice_iva"]):
        errori.append(f"Il codice IVA {d['codice_iva']} non esiste.")
    if d["intento_protocollo"] or d["intento_data"]:
        if not re.fullmatch(r"\d{17}-\d{6}", d["intento_protocollo"]):
            errori.append("Il protocollo della dichiarazione d'intento ha la forma 12345678901234567-123456.")
        if not d["intento_data"]:
            errori.append("Indica la data della dichiarazione d'intento.")
    return d, errori


def nuovo_codice_cliente():
    with db.conn() as c:
        codici = [int(r["codice"]) for r in c.execute("SELECT codice FROM clienti") if (r["codice"] or "").isdigit()]
    return str(max(codici, default=0) + 1)


def salva_nuovo_cliente(d, cid=None):
    cid = db.salva_cliente(d, cid)
    c = db.cliente(cid)
    if not c["codice"]:
        with db.conn() as k:
            k.execute("UPDATE clienti SET codice = ? WHERE id = ?", (nuovo_codice_cliente(), cid))
    return cid


@app.route("/clienti")
def clienti():
    cerca = request.args.get("q", "").strip()
    return render_template("clienti.html", elenco=db.clienti(cerca), cerca=cerca, privato=privato, estero=estero)


@app.route("/clienti/nuovo", methods=["GET", "POST"])
@app.route("/clienti/<int:cid>", methods=["GET", "POST"])
def cliente(cid=None):
    c = db.cliente(cid) if cid else None
    if cid and not c:
        abort(404)
    if request.method == "POST":
        d, errori = leggi_cliente(request.form)
        if errori:
            return render_template("cliente.html", c=d | {"codice": c["codice"] if c else ""}, cid=cid,
                                   errori=errori, n_doc=0, codici=db.codici_iva())
        cid = salva_nuovo_cliente(d, cid)
        flash("Cliente salvato.", "ok")
        return redirect(url_for("clienti"))
    vuoto = {k: "" for k in db.CAMPI_CLIENTE} | {"nazione": "IT", "codice": ""}
    return render_template("cliente.html", c=c or vuoto, cid=cid, errori=[], codici=db.codici_iva(),
                           n_doc=db.documenti_cliente(cid) if cid else 0)


@app.route("/clienti/<int:cid>/elimina", methods=["POST"])
def elimina_cliente(cid):
    if db.documenti_cliente(cid):
        flash("Il cliente ha documenti collegati e non può essere eliminato.", "errore")
    else:
        db.elimina_cliente(cid)
        flash("Cliente eliminato.", "ok")
    return redirect(url_for("clienti"))


@app.route("/api/cliente", methods=["POST"])
def api_cliente():
    """Nuovo cliente dalla finestra del modulo fattura."""
    d, errori = leggi_cliente(request.form)
    if errori:
        return jsonify({"errori": errori}), 400
    cid = salva_nuovo_cliente(d)
    c = db.cliente(cid)
    return jsonify({"id": cid, "nome": c["denominazione"], "dettagli": dettagli_cliente(c),
                    "codice": K.codice_riga("", c), "pagamento": K.nome_pagamento({"pagamento": ""}, c),
                    "estero": estero(c)})


# ---------------------------------------------------------------- codici IVA
NATURE = {
    "": "Con IVA (nessuna natura)",
    "N1": "N1 - escluse ex art. 15",
    "N2.1": "N2.1 - non soggette art. 7-7septies",
    "N2.2": "N2.2 - non soggette, altri casi",
    "N3.1": "N3.1 - non imponibili, esportazioni",
    "N3.2": "N3.2 - non imponibili, cessioni intracomunitarie",
    "N3.3": "N3.3 - non imponibili, verso San Marino",
    "N3.4": "N3.4 - non imponibili, assimilate alle esportazioni",
    "N3.5": "N3.5 - non imponibili, dichiarazione d'intento",
    "N3.6": "N3.6 - non imponibili, altre",
    "N4": "N4 - esenti",
    "N5": "N5 - regime del margine",
    "N6.9": "N6.9 - inversione contabile, altri casi",
    "N7": "N7 - IVA assolta in altro Stato UE",
}


def leggi_codice_iva(form):
    d = {k: (form.get(k) or "").strip() for k in db.CAMPI_CODICE_IVA}
    d["bollo"] = 1 if form.get("bollo") else 0
    d["aliquota"] = d["aliquota"].replace(",", ".") or "0"
    errori = []
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,10}", d["codice"]):
        errori.append("Il codice è breve, senza spazi (es. 22, N8c, NS7UE).")
    try:
        al = Decimal(d["aliquota"])
        if al < 0 or al >= 100:
            raise ValueError
        d["aliquota"] = str(al.normalize()) if al != al.to_integral() else str(int(al))
    except Exception:
        errori.append("L'aliquota è una percentuale, es. 22 oppure 0.")
        al = None
    if d["natura"] not in NATURE:
        errori.append("Scegli la natura dall'elenco.")
    if al == 0 and not d["natura"]:
        errori.append("Con aliquota 0 serve la natura (perché la riga è senza IVA).")
    if al and d["natura"]:
        errori.append("Con l'IVA la natura va lasciata vuota.")
    if d["natura"] and not d["rif_norm"]:
        errori.append("Per le righe senza IVA serve il riferimento normativo (stampato in fattura).")
    return d, errori


@app.route("/codici-iva")
def codici_iva():
    elenco = db.codici_iva()
    return render_template("codici_iva.html", elenco=elenco, nature=NATURE,
                           uso={k["codice"]: db.uso_codice_iva(k["codice"]) for k in elenco})


@app.route("/codici-iva/nuovo", methods=["GET", "POST"])
@app.route("/codici-iva/<codice>", methods=["GET", "POST"])
def codice_iva(codice=None):
    k = db.codice_iva(codice) if codice else None
    if codice and not k:
        abort(404)
    if request.method == "POST":
        if request.form.get("azione") == "elimina" and k:
            if db.uso_codice_iva(codice):
                flash("Il codice è usato da clienti o fatture: non si può eliminare.", "errore")
                return redirect(url_for("codice_iva", codice=codice))
            db.elimina_codice_iva(codice)
            flash(f"Codice IVA {codice} eliminato.", "ok")
            return redirect(url_for("codici_iva"))
        d, errori = leggi_codice_iva(request.form)
        if d["codice"] != codice and db.codice_iva(d["codice"]):
            errori.append(f"Il codice {d['codice']} esiste già.")
        if errori:
            return render_template("codice_iva.html", k=d, codice=codice, errori=errori, nature=NATURE,
                                   uso=db.uso_codice_iva(codice) if codice else 0)
        db.salva_codice_iva(d, codice)
        flash(f"Codice IVA {d['codice']} salvato.", "ok")
        return redirect(url_for("codici_iva"))
    vuoto = {"codice": "", "aliquota": "0", "natura": "", "rif_norm": "", "bollo": 1, "descrizione": ""}
    return render_template("codice_iva.html", k=k or vuoto, codice=codice, errori=[], nature=NATURE,
                           uso=db.uso_codice_iva(codice) if codice else 0)


# ---------------------------------------------------------------- pagamenti e banche
def leggi_pagamento(form):
    d = {k: (form.get(k) or "").strip() for k in db.CAMPI_PAGAMENTO}
    d["fine_mese"] = 1 if form.get("fine_mese") else 0
    d["giorni"] = re.sub(r"[\s;\-]+", ",", d["giorni"]).strip(",") or "0"
    errori = []
    if not d["nome"]:
        errori.append("Scrivi il nome, come comparirà in fattura (es. Bonifico 30 gg.).")
    if d["modalita"] not in db.MODALITA:
        errori.append("Scegli la modalità di pagamento.")
    if not re.fullmatch(r"\d{1,3}(,\d{1,3})*", d["giorni"]):
        errori.append("Giorni: un numero (30) oppure più rate separate da virgola (30,60,90).")
    return d, errori


def leggi_banca(form):
    d = {k: (form.get(k) or "").strip() for k in db.CAMPI_BANCA}
    d["predefinita"] = 1 if form.get("predefinita") else 0
    d["iban"] = d["iban"].replace(" ", "").upper()
    d["bic"] = d["bic"].replace(" ", "").upper()
    d["valuta"] = (d["valuta"] or "EUR").upper()
    errori = []
    if not d["nome"]:
        errori.append("Scrivi il nome della banca.")
    if d["iban"] and not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", d["iban"]):
        errori.append("L'IBAN non ha la forma giusta (es. IT46Y03069...).")
    if d["bic"] and not re.fullmatch(r"[A-Z0-9]{8}([A-Z0-9]{3})?", d["bic"]):
        errori.append("Il BIC/SWIFT ha 8 o 11 caratteri.")
    if not re.fullmatch(r"[A-Z]{3}", d["valuta"]):
        errori.append("La valuta è il codice di tre lettere (EUR, USD).")
    if not (d["iban"] or d["dettagli"]):
        errori.append("Serve l'IBAN oppure le coordinate nel campo Dettagli.")
    return d, errori


@app.route("/pagamenti")
def pagamenti():
    return render_template("pagamenti.html", pagamenti=db.pagamenti(), banche=db.banche(), modalita=db.MODALITA)


@app.route("/pagamenti/nuovo", methods=["GET", "POST"])
@app.route("/pagamenti/<int:pid>", methods=["GET", "POST"])
def pagamento(pid=None):
    p = db.pagamento(pid) if pid else None
    if pid and not p:
        abort(404)
    uso = db.uso_pagamento(p["nome"]) if p else 0
    if request.method == "POST":
        if request.form.get("azione") == "elimina" and p and not uso:
            db.elimina_record("pagamenti", pid)
            flash(f"Pagamento «{p['nome']}» eliminato.", "ok")
            return redirect(url_for("pagamenti"))
        d, errori = leggi_pagamento(request.form)
        altro = db.pagamento(nome=d["nome"])
        if altro and altro["id"] != pid:
            errori.append("Esiste già un pagamento con questo nome.")
        if p and uso and d["nome"] != p["nome"]:
            errori.append("Il pagamento è in uso: il nome non si può cambiare (puoi crearne uno nuovo).")
        if errori:
            return render_template("pagamento.html", p=d, pid=pid, errori=errori, modalita=db.MODALITA, uso=uso)
        db.salva_record("pagamenti", db.CAMPI_PAGAMENTO, d, pid)
        flash(f"Pagamento «{d['nome']}» salvato.", "ok")
        return redirect(url_for("pagamenti"))
    vuoto = {"nome": "", "modalita": "MP05", "giorni": "30", "fine_mese": 0}
    return render_template("pagamento.html", p=p or vuoto, pid=pid, errori=[], modalita=db.MODALITA, uso=uso)


@app.route("/banche/nuova", methods=["GET", "POST"])
@app.route("/banche/<int:bid>", methods=["GET", "POST"])
def banca(bid=None):
    b = db.banca(bid) if bid else None
    if bid and not b:
        abort(404)
    uso = db.uso_banca(bid) if bid else 0
    if request.method == "POST":
        if request.form.get("azione") == "elimina" and b and not uso:
            db.elimina_record("banche", bid)
            flash(f"Banca «{b['nome']}» eliminata.", "ok")
            return redirect(url_for("pagamenti"))
        d, errori = leggi_banca(request.form)
        if errori:
            return render_template("banca.html", b=d, bid=bid, errori=errori, uso=uso)
        db.salva_banca(d, bid)
        flash(f"Banca «{d['nome']}» salvata.", "ok")
        return redirect(url_for("pagamenti"))
    vuoto = {"nome": "", "iban": "", "bic": "", "valuta": "EUR", "dettagli": "", "predefinita": 0}
    return render_template("banca.html", b=b or vuoto, bid=bid, errori=[], uso=uso)


# ---------------------------------------------------------------- impostazioni
@app.route("/impostazioni", methods=["GET", "POST"])
def impostazioni():
    anno = date.today().year
    if request.method == "POST":
        errori = []
        for k in db.MODIFICABILI:
            if k not in request.form:
                continue
            v = request.form[k].strip()
            if k == "iban":
                v = v.replace(" ", "").upper()
                if v and not re.fullmatch(r"IT\d{2}[A-Z]\d{10}[0-9A-Z]{12}", v):
                    errori.append("L'IBAN italiano ha 27 caratteri e inizia con IT.")
                    continue
            db.salva_impostazione(f"studio.{k}", v)
        if request.form.get("azione") == "pec":
            try:
                if request.form.get("pec_password"):
                    pec.salva_password(request.form["pec_password"])
                sdi = (request.form.get("indirizzo_sdi") or "").strip().lower()
                if sdi:
                    if not re.fullmatch(r"sdi\d+@pec\.fatturapa\.it", sdi):
                        raise pec.ErrorePec("L'indirizzo dello SDI ha la forma sdiNN@pec.fatturapa.it.")
                    db.salva_impostazione("pec.indirizzo_sdi", sdi)
                flash(pec.verifica(), "ok")
            except pec.ErrorePec as e:
                flash(str(e), "errore")
            return redirect(url_for("impostazioni"))
        if "primo_numero" in request.form:
            db.salva_impostazione("bollo_virtuale", "1" if request.form.get("bollo_virtuale") else "0")
        primo = (request.form.get("primo_numero") or "").strip()
        if primo and not primo.isdigit():
            errori.append("Il primo numero deve essere un numero intero.")
        else:
            db.salva_impostazione(f"primo_numero.{anno}", primo)
        for e in errori:
            flash(e, "errore")
        if not errori:
            flash("Impostazioni salvate.", "ok")
        return redirect(url_for("impostazioni"))
    return render_template("impostazioni.html", s=db.studio(), anno=anno,
                           primo=db.impostazione(f"primo_numero.{anno}"), prossimo=db.prossimo_numero(anno),
                           progressivo=db.prossimo_progressivo(consuma=False),
                           pec_attiva=pec.configurata(), indirizzo_sdi=pec.indirizzo_sdi(),
                           bollo_virtuale=db.impostazione("bollo_virtuale", "0") == "1")


@app.route("/chiudi", methods=["POST"])
def chiudi_programma():
    """Spegne il programma (si riapre con l'icona nel Dock)."""
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return render_template("chiuso.html")


# ---------------------------------------------------------------- controllo automatico degli esiti SDI
CONTROLLO_OGNI_MINUTI = 30
avvisi_in_attesa = []            # messaggi del controllo automatico, mostrati alla prossima pagina aperta
_blocco_avvisi = threading.Lock()


def controllo_automatico():
    """All'avvio e ogni 30 minuti: se ci sono documenti in attesa di esito, legge le ricevute dalla PEC."""
    if not pec.configurata():
        return
    with db.conn() as c:
        attesa = c.execute("SELECT COUNT(*) AS n FROM documenti WHERE stato = 'inviata' AND storico = 0").fetchone()["n"]
    if not attesa:
        return
    try:
        cambiamenti, avvisi = pec.aggiorna_esiti()
    except pec.ErrorePec as e:
        nuovi = [(f"Controllo automatico degli esiti non riuscito: {e}", "avviso")]
    else:
        nuovi = [(f"{nome_documento(d)}: {C.STATI[stato].lower()}" + (f" ({det})" if det else ""),
                  "errore" if stato == "scartata" else "ok") for d, stato, det in cambiamenti]
        nuovi += [(a, "avviso") for a in avvisi]
    db.salva_impostazione("pec.ultimo_controllo", db.adesso())
    with _blocco_avvisi:
        avvisi_in_attesa.extend(nuovi)


def ciclo_controlli():
    import time
    time.sleep(5)
    while True:
        try:
            controllo_automatico()
        except Exception as e:                   # il controllo non deve mai fermare il programma
            print("controllo esiti:", e)
        time.sleep(CONTROLLO_OGNI_MINUTI * 60)


IN_PREPARAZIONE = {"documento_nuovo", "documento", "scegli_fattura", "anteprima", "invia_pec", "api_calcola",
                   "cambia_stato", "apri_pdf", "scarica_xml", "mostra_file"}


@app.before_request
def modulo_fattura_in_preparazione():
    """Passo 1: clienti e codici IVA. Il modulo fattura con l'IVA per riga arriva nel passo 2."""
    if getattr(C, "FATTURE_IN_PREPARAZIONE", False) and request.endpoint in IN_PREPARAZIONE:
        if request.endpoint == "documento" and request.method == "GET":
            d, _ = db.documento(request.view_args.get("did"))
            if d and d["storico"]:
                return None                      # i documenti dello storico si possono consultare
        flash("Il modulo fattura è in preparazione: per ora le fatture si fanno ancora con l'Excel. "
              "Qui puoi già consultare lo storico, segnare gli incassi e controllare le anagrafiche.", "avviso")
        return redirect(url_for("documenti"))


@app.before_request
def mostra_avvisi_automatici():
    if avvisi_in_attesa and request.method == "GET" and not request.path.startswith("/static"):
        with _blocco_avvisi:
            for testo, cat in avvisi_in_attesa:
                flash(testo, cat)
            avvisi_in_attesa.clear()


# ---------------------------------------------------------------- avvio
def gia_in_esecuzione():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", C.PORTA)) == 0


def main():
    indirizzo = f"http://127.0.0.1:{C.PORTA}/"
    if gia_in_esecuzione():
        webbrowser.open(indirizzo)
        print("Il programma è già aperto: ho riaperto la pagina nel browser.")
        return
    db.inizializza()
    threading.Thread(target=ciclo_controlli, daemon=True).start()
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(indirizzo)).start()
    print(f"Fatture dello studio: {indirizzo}\nPer chiudere il programma chiudi questa finestra.")
    app.run(host="127.0.0.1", port=C.PORTA, debug=False)


db.inizializza()

if __name__ == "__main__":
    main()
