"""
Voci delle fatture Consept dagli export Easyfatt-Xml (.DefXml), uno o piu' file (anche uno per anno).

    python3 importa_voci_easyfatt.py file_to_claude/2018.defxml file_to_claude/2019.defxml ... --prova
    python3 importa_voci_easyfatt.py file_to_claude/*.defxml

Completa i documenti dello storico che hanno i soli totali (importati dall'elenco Easyfatt): aggiunge le voci
con quantita', prezzo e codice IVA di ogni riga. Numero, data, stato, saldo e incassi restano come sono.
Prima di scrivere ricalcola il totale dalle voci con le regole del programma e lo confronta con quello
registrato: se non torna, il documento resta com'era e viene segnalato.
I documenti che hanno gia' le voci (es. 20-23/2026 dall'Excel) non vengono toccati. Si puo' rilanciare.
"""
import re
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal

import calcoli_studio as K
import db_studio as db

# codici di Easyfatt che nel programma hanno un altro nome
ALIAS = {"NS7u": "NS7UE",            # servizi a impresa UE (inversione contabile)
         "N8": "N8c"}                # art. 8 c.1 lett. c (dichiarazione d'intento), codice usato fino al 2020
RIF = re.compile(r"(?:fatt\w*\.?|fattura)\s*(?:nr?\.?\s*)?(\d+)(?:/\d{4})?\s+del\s+(\d{1,2})/(\d{1,2})/(\d{4})", re.I)


def t(el, k):
    return re.sub(r"\s+", " ", el.findtext(k) or "").strip()


def numero_testo(v):
    v = (v or "").strip()
    return Decimal(v) if v else None


def leggi(percorso):
    out = []
    for d in ET.parse(percorso).getroot().find("Documents"):
        tipo = {"I": "TD01", "N": "TD04"}.get(t(d, "DocumentType"))
        if not tipo:
            continue
        data = t(d, "Date")
        m = re.search(r"(\d{4})", t(d, "Numbering"))
        anno = int(m.group(1)) if m else int(data[:4])        # 5/2019 emessa il 22/01/2020 resta del 2019
        righe = []
        for r in d.find("Rows") if d.find("Rows") is not None else []:
            descr = (r.findtext("Description") or "").strip()
            tot, cod = numero_testo(t(r, "Total")), t(r, "VatCode")
            if tot is None or not cod:
                righe.append({"tipo": "onorario", "descrizione": descr, "importo": ""})
                continue
            q, p = numero_testo(t(r, "Qty")), numero_testo(t(r, "Price"))
            con_qta = q is not None and p is not None and K.q2(q * p) == K.q2(tot)
            righe.append({"tipo": "onorario", "descrizione": descr, "importo": str(abs(K.q2(tot))),
                          "quantita": str(q) if con_qta else "", "prezzo": str(abs(p)) if con_qta else "",
                          "um": t(r, "Um") if con_qta else "", "codice_iva": ALIAS.get(cod, cod)})
        costo = numero_testo(t(d, "CostAmount"))
        if costo:
            cod = t(d, "CostVatCode")
            righe.append({"tipo": "onorario", "descrizione": t(d, "CostDescription") or "Altre spese",
                          "importo": str(abs(K.q2(costo))), "codice_iva": ALIAS.get(cod, cod)})
        rif = ("", "")
        if tipo == "TD04":
            for r in righe:
                m = RIF.search(r["descrizione"])
                if m:
                    rif = (f"{m.group(1)}/{m.group(4)}", f"{m.group(4)}-{int(m.group(3)):02d}-{int(m.group(2)):02d}")
                    break
        out.append({"tipo": tipo, "anno": anno, "numero": int(t(d, "Number")), "data": data,
                    "cliente": t(d, "CustomerName"), "totale": abs(K.q2(Decimal(t(d, "Total") or "0"))),
                    "pagamento": t(d, "PaymentName"), "righe": righe, "rif": rif})
    return out


def trova(doc):
    """Documento in archivio con lo stesso numero; un numero usato due volte in Easyfatt e' stato
    registrato come 5/B: si distingue dalla data."""
    for suff in ("", "B"):
        e = db.documento_per_numero(doc["anno"], doc["numero"], suff)
        if e and e["data"] == doc["data"]:
            return e
    return db.documento_per_numero(doc["anno"], doc["numero"], "")


def totale_voci(doc, cli, tabella):
    righe = [{"descrizione": r["descrizione"], "importo": Decimal(r["importo"]) if r["importo"] else None,
              "quantita": None, "prezzo": None, "um": "", "codice_iva": r.get("codice_iva", ""),
              "prezzo_valuta": None, "importo_valuta": None} for r in doc["righe"]]
    ls = K.linee(righe, cli, tabella)
    return K.totali(ls, tabella)["totale"]


def main():
    file = [a for a in sys.argv[1:] if not a.startswith("--")]
    prova = "--prova" in sys.argv
    if not file:
        print(__doc__)
        sys.exit(1)
    db.inizializza()
    tabella = K.codici()
    pagamenti = {p["nome"] for p in db.pagamenti()}
    per_anno, problemi = {}, []
    for f in file:
        for doc in leggi(f):
            a = per_anno.setdefault(doc["anno"], {"file": 0, "completati": 0, "gia": 0, "problemi": 0})
            a["file"] += 1
            nome = f"{doc['numero']}/{doc['anno']} {doc['cliente'][:30]}"
            e = trova(doc)
            if not e:
                problemi.append(f"{nome}: non è in archivio")
                a["problemi"] += 1
                continue
            _, righe_db = db.documento(e["id"])
            if any((r["importo"] or "").strip() for r in righe_db):
                a["gia"] += 1
                continue
            mancanti = sorted({r["codice_iva"] for r in doc["righe"] if r["importo"] and r["codice_iva"] not in tabella})
            if mancanti:
                problemi.append(f"{nome}: codici IVA non in tabella {', '.join(mancanti)}")
                a["problemi"] += 1
                continue
            cli = db.cliente(e["cliente_id"])
            calc = totale_voci(doc, cli, tabella)
            registrato = Decimal(e["totale"] or "0")
            if calc != registrato or calc != doc["totale"]:
                problemi.append(f"{nome}: in archivio {registrato}, nel file {doc['totale']}, dalle voci {calc}")
                a["problemi"] += 1
                continue
            a["completati"] += 1
            if prova:
                continue
            db.sostituisci_righe(e["id"], doc["righe"])
            campi = {}
            if doc["pagamento"] in pagamenti and not (e["pagamento"] or "").strip():
                campi["pagamento"] = doc["pagamento"]
            if doc["tipo"] == "TD04" and doc["rif"][0] and not (e["rif_numero"] or "").strip():
                campi["rif_numero"], campi["rif_data"] = doc["rif"]
            if campi:
                db.aggiorna_documento(e["id"], **campi)
    for anno, a in sorted(per_anno.items()):
        print(f"{anno}: nel file {a['file']}, {'da completare' if prova else 'completati'} {a['completati']}, "
              f"già con le voci {a['gia']}, da controllare {a['problemi']}")
    for p in problemi:
        print("  da controllare:", p)
    if prova:
        print("Prova: non ho scritto nulla.")


if __name__ == "__main__":
    main()
