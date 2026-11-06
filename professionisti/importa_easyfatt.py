"""
Import da Danea Easyfatt: clienti (export Excel) e documenti (export Easyfatt-Xml).

Uso (a programma chiuso), dalla cartella del programma:
    python3 importa_easyfatt.py Clienti.xlsx Documenti.DefXml
    python3 importa_easyfatt.py Clienti.xlsx Documenti.DefXml --prova     (controlla senza scrivere)
    python3 importa_easyfatt.py Clienti.xlsx Fattura.DefXml --bozza       (fattura preparata in Easyfatt ma NON
                                                                           ancora inviata: entra come bozza, da
                                                                           generare e inviare da questo programma)

Si può rilanciare: clienti (per codice Easyfatt) e documenti (per anno/numero) già presenti
vengono saltati. I documenti entrano come "Consegnata" (inviati con Easyfatt) e con lo stato
di pagamento di Easyfatt; il totale viene ricalcolato con le regole del programma e confrontato.
"""
import re
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal

import openpyxl

import config_studio as C
import db_studio as db
from calcoli_studio import totali
from fatturapa_core import PAESI

NOTA_STORICO = "Inviata con Easyfatt"


def pulisci(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def paese(nome, regione=""):
    nome = pulisci(nome)
    if not nome:
        return "IT" if not pulisci(regione).startswith("(") else ""
    if len(nome) == 2 and nome.isalpha():
        return nome.upper()
    return PAESI.get(nome.lower(), "")


# ---------------------------------------------------------------- clienti
def leggi_clienti(percorso):
    ws = openpyxl.load_workbook(percorso, read_only=True, data_only=True).active
    righe = ws.iter_rows(values_only=True)
    intest = [pulisci(h) for h in next(righe)]
    col = {h: i for i, h in enumerate(intest)}
    out, avvisi = [], []
    for r in righe:
        v = lambda h: pulisci(r[col[h]]) if h in col and col[h] < len(r) else ""
        codice, nome = v("Cod."), v("Denominazione")
        if not codice or not nome:                 # riga dei totali o vuota
            continue
        dest, pec = v("Cod. destinatario").upper(), v("Pec")
        if "@" in dest:                            # PEC finita nel campo codice destinatario
            pec, dest = pec or dest.lower(), ""
        naz = paese(v("Nazione"), v("Regione"))
        if not naz:
            avvisi.append(f"cliente {codice} {nome}: nazione {v('Nazione') or v('Regione')!r} non riconosciuta")
            naz = "IT"
        cli = {"codice": codice, "denominazione": nome, "cf": v("Codice fiscale").upper(),
               "piva": v("Partita Iva"), "indirizzo": v("Indirizzo"), "cap": v("Cap"), "comune": v("Città"),
               "provincia": v("Prov.").upper(), "nazione": naz, "codice_destinatario": dest,
               "pec": pec, "email": v("e-mail"), "note": ""}
        if not (cli["cf"] or cli["piva"]):
            avvisi.append(f"cliente {codice} {nome}: senza codice fiscale e partita IVA")
        elif not (cli["indirizzo"] and cli["comune"]):
            avvisi.append(f"cliente {codice} {nome}: indirizzo incompleto")
        out.append(cli)
    return out, avvisi


def salva_cliente_importato(cli):
    if db.cliente_per_codice(cli["codice"]):
        return None
    cid = db.salva_cliente(cli)
    with db.conn() as c:
        c.execute("UPDATE clienti SET codice = ? WHERE id = ?", (cli["codice"], cid))
    return cid


# ---------------------------------------------------------------- documenti
RIF = re.compile(r"Rif\.\s*Fattura\s+(\S+)\s+del\s+(\d{2})/(\d{2})/(\d{4})", re.I)
TERZO = re.compile(r"(?:si\s+d[aà]\s+atto\s+che\s+)?(?:il\s+)?(?:pagamento\s+verr[aà]'?\s+)?effettuato\s+da\s+(.+?)"
                   r"\s+terza\s+solvente\.?", re.I)


def leggi_documenti(percorso):
    radice = ET.parse(percorso).getroot()
    out = []
    for d in radice.find("Documents"):
        g = lambda k: pulisci(d.findtext(k))
        tipo = {"I": "TD01", "N": "TD04"}.get(g("DocumentType"))
        if not tipo:
            print(f"  salto il documento {g('Number')} di tipo {g('DocumentType')!r} (non fattura)")
            continue
        data = g("Date")
        doc = {"tipo": tipo, "anno": int(data[:4]), "numero": int(g("Number")),
               "suffisso": g("Numbering").strip("/").upper(), "data": data,
               "cliente_codice": g("CustomerCode"), "terzo_pagatore": "", "note": "", "bollo": 0,
               "rif_numero": "", "rif_data": "", "totale_easyfatt": abs(Decimal(g("Total") or "0"))}
        doc["cliente"] = {
            "codice": g("CustomerCode"), "denominazione": g("CustomerName"), "cf": g("CustomerFiscalCode").upper(),
            "piva": g("CustomerVatCode"), "indirizzo": g("CustomerAddress"), "cap": g("CustomerPostcode"),
            "comune": g("CustomerCity"), "provincia": g("CustomerProvince").upper(),
            "nazione": paese(g("CustomerCountry")) or "IT",
            "codice_destinatario": g("CustomerEInvoiceDestCode").upper(), "pec": "", "email": "", "note": ""}
        righe = []
        for r in d.find("Rows") if d.find("Rows") is not None else []:
            descr = (r.findtext("Description") or "").strip()
            tot = pulisci(r.findtext("Total"))
            m = RIF.search(descr)
            if tipo == "TD04" and m:               # riga "** Rif. Fattura 15 del 25/02/2026:"
                doc["rif_numero"] = m.group(1) if "/" in m.group(1) else f"{m.group(1)}/{m.group(4)}"
                doc["rif_data"] = f"{m.group(4)}-{m.group(3)}-{m.group(2)}"
                continue
            importo = "" if not tot or not pulisci(r.findtext("VatCode")) else str(abs(Decimal(tot)))
            if descr.lower() == "bollo" and importo == "2":
                doc["bollo"] = 1                   # bollo automatico del programma
                continue
            # in Easyfatt le righe non soggette a contributo (WithholdingTax=false) sono spese anticipate
            soggetta = pulisci(r.findtext("WithholdingTax")) == "true"
            righe.append({"tipo": "onorario" if soggetta or not importo else "anticipazione",
                          "descrizione": descr, "importo": importo})
        if g("CostAmount") and Decimal(g("CostAmount")):
            righe.append({"tipo": "anticipazione", "descrizione": g("CostDescription") or "Anticipazioni",
                          "importo": str(abs(Decimal(g("CostAmount"))))})
        note = " ".join(x for x in (g("InternalComment"), g("FootNotes")) if x)
        m = TERZO.search(note)
        if m:
            doc["terzo_pagatore"] = pulisci(m.group(1))
            note = pulisci(TERZO.sub("", note).replace("Il pagamento verrà", "").strip(" .,"))
            if len(note) < 40 and re.match(r"(?i)(si\s+d[aà]\s+atto|si\s+dichiara)", note):
                note = ""                          # resto della frase "si da atto che ... terza solvente"
        doc["note"] = note
        pag = d.find("Payments")
        doc["saldato"] = int(pag is not None and len(pag) > 0 and
                             all((p.findtext("Paid") or "").strip() == "true" for p in pag))
        doc["righe"] = righe
        if doc["bollo"] and totale_calcolato(doc) != doc["totale_easyfatt"]:
            # bollo che non torna con la regola attuale: lo riporto come voce, scegliendo il modo che
            # ridà il totale di Easyfatt (sotto soglia -> voce soggetta a cassa; negli anni in cui il
            # bollo non era soggetto a cassa -> voce esclusa dalla cassa, come le anticipazioni)
            doc["bollo"] = 0
            for tipo in ("onorario", "anticipazione"):
                voce = {"tipo": tipo, "descrizione": "bollo", "importo": "2"}
                righe.append(voce)
                if totale_calcolato(doc) == doc["totale_easyfatt"]:
                    break
                righe.remove(voce)
            else:
                righe.append({"tipo": "onorario", "descrizione": "bollo", "importo": "2"})
        out.append(doc)
    return out


def totale_calcolato(doc):
    righe = [{"tipo": r["tipo"], "importo": Decimal(r["importo"]) if r["importo"] else None} for r in doc["righe"]]
    return totali(righe, bool(doc["bollo"]))["totale"]


def solo_totali(esistente):
    """Documento gia' in archivio importato da un elenco: ha i totali ma non le voci."""
    _, righe = db.documento(esistente["id"])
    return esistente["storico"] and not any((r["importo"] or "").strip() for r in righe)


def completa_voci(esistente, doc):
    """Aggiunge le voci a un documento importato con i soli totali. Numero, data, stato, saldo e incassi
    restano come sono; si completano bollo, terzo pagatore, note e riferimento della nota di credito."""
    with db.conn() as c:
        c.execute("DELETE FROM righe WHERE documento_id = ?", (esistente["id"],))
        for i, r in enumerate(doc["righe"]):
            c.execute("INSERT INTO righe (documento_id, ordine, tipo, descrizione, importo) VALUES (?, ?, ?, ?, ?)",
                      (esistente["id"], i, r["tipo"], r["descrizione"], r["importo"]))
        c.execute("UPDATE documenti SET bollo = ?, terzo_pagatore = ?, note = ?, rif_numero = ?, rif_data = ? "
                  "WHERE id = ?", (doc["bollo"], doc["terzo_pagatore"], doc["note"], doc["rif_numero"],
                                   doc["rif_data"], esistente["id"]))


def salva_documento_importato(doc, cid, bozza=False):
    esistente = db.documento_per_numero(doc["anno"], doc["numero"], doc["suffisso"])
    if esistente:
        return None
    dati = {k: doc.get(k, db.PREDEFINITI_DOC.get(k)) for k in db.CAMPI_DOC if k != "cliente_id"} | {"cliente_id": cid,
                                                                    "totale": str(doc["totale_easyfatt"])}
    did = db.salva_documento(dati, doc["righe"])
    if bozza:                                    # non ancora inviata: si genera e si invia da qui
        db.aggiorna_documento(did, suffisso=doc["suffisso"], stato="bozza", storico=0, saldato=0)
        return did
    db.aggiorna_documento(did, suffisso=doc["suffisso"], stato="consegnata", storico=1, esito_note=NOTA_STORICO,
                          inviato_il=doc["data"], saldato=doc["saldato"])
    return did


# ---------------------------------------------------------------- main
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prova = "--prova" in sys.argv
    bozza = "--bozza" in sys.argv
    if len(args) != 2:
        print(__doc__)
        sys.exit(1)
    db.inizializza()

    clienti, avvisi = leggi_clienti(args[0])
    nuovi_cli = 0
    for cli in clienti:
        if not prova and salva_cliente_importato(cli):
            nuovi_cli += 1
    print(f"Clienti nel file: {len(clienti)}; importati ora: {nuovi_cli}")
    for a in avvisi:
        print("  da controllare:", a)

    documenti = leggi_documenti(args[1])
    nuovi_doc, completati, diff = 0, 0, []
    for doc in documenti:
        calc = totale_calcolato(doc)
        if calc != doc["totale_easyfatt"]:
            diff.append(f"n. {doc['numero']}{'/' + doc['suffisso'] if doc['suffisso'] else ''}: "
                        f"Easyfatt {doc['totale_easyfatt']}, ricalcolato {calc}")
        esistente = db.documento_per_numero(doc["anno"], doc["numero"], doc["suffisso"])
        if esistente and solo_totali(esistente):
            if Decimal(esistente["totale"] or "0") != doc["totale_easyfatt"]:
                diff.append(f"n. {doc['numero']}: in archivio {esistente['totale']}, nel file {doc['totale_easyfatt']}")
            elif not prova:
                completa_voci(esistente, doc)
            completati += 1
            continue
        if prova:
            nuovi_doc += 0 if esistente else 1
            continue
        cli = db.cliente_per_codice(doc["cliente_codice"])
        cid = cli["id"] if cli else salva_cliente_importato(doc["cliente"])
        if salva_documento_importato(doc, cid, bozza):
            nuovi_doc += 1
    non_saldati = [f"{d['numero']}{'/' + d['suffisso'] if d['suffisso'] else ''}" for d in documenti
                   if not d["saldato"] and d["tipo"] == "TD01"]
    print(f"Documenti nel file: {len(documenti)}; {'da importare' if prova else 'importati ora'}: {nuovi_doc}; "
          f"{'da completare' if prova else 'completati'} con le voci: {completati}; "
          f"già completi: {len(documenti) - nuovi_doc - completati}")
    print(f"Totali uguali a Easyfatt: {len(documenti) - len(diff)} su {len(documenti)}")
    for x in diff:
        print("  totale diverso:", x)
    print("Non saldate secondo Easyfatt:", ", ".join(non_saldati) or "nessuna")
    if prova:
        print("Prova: non ho scritto nulla.")


if __name__ == "__main__":
    main()
