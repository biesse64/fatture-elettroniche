"""
Import dal file Excel Consept (fatture_consept_2026.xlsx): codici IVA, clienti e fatture con le loro voci.
Facoltativi, se si indica la cartella del programma Excel: indirizzo SDI dedicato (pec_config.json)
e progressivo dei file XML gia' usati (progressivo_04089410288.txt), per non riusarli.

Uso (a programma chiuso), dalla cartella del programma:
    python3 importa_excel.py ../fatture_consept/fatture_consept_2026.xlsx            (--prova per controllare)

- Si puo' rilanciare: i clienti gia' presenti (stesso codice) vengono aggiornati con i dati dell'Excel,
  i codici IVA pure. Nessun cliente o codice viene cancellato.
- Fatture: quelle gia' importate dallo storico Easyfatt (solo totali) ricevono le voci dell'Excel; quelle
  mancanti (es. la 23 inviata dal programma Excel) entrano come "programma precedente", da incassare.
"""
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import openpyxl

import db_studio as db
from controlli_fiscali import controlla_cf, controlla_piva

COLONNE_CLIENTI = {
    "codice": "Codice", "denominazione": "Ragione sociale", "piva": "Partita IVA", "cf": "Codice fiscale",
    "indirizzo": "Indirizzo", "cap": "CAP", "comune": "Comune", "provincia": "Prov.", "nazione": "Nazione (ISO)",
    "codice_destinatario": "Codice destinatario", "pec": "PEC", "email": "Email",
    "codice_iva": "Codice IVA predefinito", "giorni_pagamento": "Giorni pagamento",
    "id_estero": "Identificativo fiscale estero", "intento_protocollo": "Dich. intento: protocollo",
    "intento_data": "Dich. intento: data", "riferimento": "Riferimento / contatto",
}


def s(v):
    """Valore di cella -> testo pulito (i codici numerici tornano senza '.0')."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def righe_foglio(ws):
    it = ws.iter_rows(values_only=True)
    intest = [s(h) for h in next(it)]
    for r in it:
        if r and any(v not in (None, "") for v in r):
            yield {h: (r[i] if i < len(r) else None) for i, h in enumerate(intest) if h}


def importa_codici(wb, prova):
    n = 0
    for r in righe_foglio(wb["CodiciIVA"]):
        cod = s(r.get("Codice"))
        if not cod:
            continue
        d = {"codice": cod, "aliquota": s(r.get("Aliquota %")) or "0", "natura": s(r.get("Natura")),
             "rif_norm": s(r.get("Riferimento normativo (per natura)")),
             "bollo": 1 if s(r.get("Soggetto a bollo")).upper() == "SI" else 0,
             "descrizione": s(r.get("Descrizione"))}
        if not prova:
            db.salva_codice_iva(d, cod if db.codice_iva(cod) else None)
        n += 1
    return n


def pulisci_cliente(r):
    d = {k: s(r.get(col)) for k, col in COLONNE_CLIENTI.items()}
    d["nazione"] = (d["nazione"] or "IT").upper()
    d["provincia"] = d["provincia"].upper()
    d["codice_destinatario"] = d["codice_destinatario"].upper()
    d["cf"] = re.sub(r"\s", "", d["cf"]).upper()
    d["piva"] = re.sub(r"\s", "", d["piva"]).upper()
    if d["nazione"] == "IT":
        if d["piva"].isdigit() and len(d["piva"]) < 11:          # zeri iniziali persi da Excel
            d["piva"] = d["piva"].zfill(11)
        if d["cf"].isdigit() and len(d["cf"]) < 11:
            d["cf"] = d["cf"].zfill(11)
        if d["cap"].isdigit() and len(d["cap"]) < 5:
            d["cap"] = d["cap"].zfill(5)
    d["note"] = ""
    return d


def importa_clienti(wb, prova):
    nuovi, aggiornati, avvisi = 0, 0, []
    for r in righe_foglio(wb["Clienti"]):
        d = pulisci_cliente(r)
        if not d["codice"] or not d["denominazione"]:
            continue
        if d["nazione"] == "IT":
            errori = [e for e in (d["piva"] and controlla_piva(d["piva"]), d["cf"] and controlla_cf(d["cf"])) if e]
            if not (d["piva"] or d["cf"]):
                errori.append("senza partita IVA e codice fiscale")
            for e in errori:
                avvisi.append(f"[{d['codice']}] {d['denominazione']}: {e}")
        elif not (d["id_estero"] or d["piva"]):
            avvisi.append(f"[{d['codice']}] {d['denominazione']} ({d['nazione']}): estero senza identificativo fiscale")
        if d["codice_iva"] and not db.codice_iva(d["codice_iva"]):
            avvisi.append(f"[{d['codice']}] {d['denominazione']}: codice IVA {d['codice_iva']} non presente")
        esistente = db.cliente_per_codice(d["codice"])
        d["pagamento"] = esistente["pagamento"] if esistente else ""
        if not d["pagamento"] and d["giorni_pagamento"] not in ("", "0"):
            # giorni di pagamento dell'Excel -> condizione di pagamento equivalente (bonifico a N giorni)
            with db.conn() as c:
                p = c.execute("SELECT nome FROM pagamenti WHERE modalita = 'MP05' AND giorni = ? AND fine_mese = 0 "
                              "ORDER BY length(nome) LIMIT 1", (d["giorni_pagamento"],)).fetchone()
            if p:
                d["pagamento"] = p["nome"]
            else:
                avvisi.append(f"[{d['codice']}] {d['denominazione']}: nessun pagamento a {d['giorni_pagamento']} "
                              "giorni, crealo in Pagamenti e banche")
        if not prova:
            if esistente:
                d["note"] = esistente["note"] or ""
            cid = db.salva_cliente(d, esistente["id"] if esistente else None)
            with db.conn() as c:
                c.execute("UPDATE clienti SET codice = ? WHERE id = ?", (d["codice"], cid))
        if esistente:
            aggiornati += 1
        else:
            nuovi += 1
    return nuovi, aggiornati, avvisi


def dec(v):
    from decimal import Decimal
    return Decimal(str(v)).quantize(Decimal("0.01")) if v not in (None, "") else None


def importa_fatture(wb, prova):
    voci = {}
    for r in righe_foglio(wb["Righe"]):
        n = s(r.get("N. fattura"))
        if not n:
            continue
        importo = dec(r.get("Importo"))
        qta, prezzo = dec(r.get("Quantita'")), dec(r.get("Prezzo unitario"))
        voci.setdefault(n, []).append({
            "tipo": "onorario", "descrizione": s(r.get("Descrizione")),
            "importo": str(importo) if importo is not None else "",
            "quantita": s(r.get("Quantita'")) if importo is not None and qta is not None else "",
            "um": s(r.get("U.M.")) if importo is not None else "",
            "prezzo": str(prezzo) if importo is not None and prezzo is not None else "",
            "codice_iva": (s(r.get("Codice IVA (vuoto = da cliente)")) or s(r.get("Cod. IVA usato")))
                          if importo is not None else ""})
    msg = []
    for f in righe_foglio(wb["Fatture"]):
        n = s(f.get("Numero"))
        if not n.isdigit() or not f.get("Data"):
            continue
        data = s(f.get("Data"))[:10]
        anno, numero = int(data[:4]), int(n)
        righe = voci.get(n, [])
        d = db.documento_per_numero(anno, numero)
        if d:
            _, attuali = db.documento(d["id"])
            segnaposto = len(attuali) <= 1 and not any(r["importo"] for r in attuali)
            if d["storico"] and segnaposto and righe:
                if not prova:
                    db.sostituisci_righe(d["id"], righe)
                    db.aggiorna_documento(d["id"], imponibile=d["imponibile"] or s(f.get("Imponibile")),
                                          iva=d["iva"] or s(f.get("IVA")))
                msg.append(f"{numero}/{anno}: aggiunte {len(righe)} voci dall'Excel")
            continue
        cli = db.cliente_per_codice(s(f.get("Cod. cliente")))
        if not cli:
            msg.append(f"{numero}/{anno}: cliente {s(f.get('Cod. cliente'))} non trovato, fattura non importata")
            continue
        esito = s(f.get("Esito SDI")).lower()
        stato_x = s(f.get("Stato (lo scrive lo script)")).upper()
        stato = "consegnata" if ("duplicat" in esito or "consegn" in esito or "GIA'" in stato_x) else \
                "scartata" if "scart" in esito else "inviata"
        tipo = "TD04" if "credito" in s(f.get("Tipo documento")).lower() else "TD01"
        totale = s(f.get("Totale"))
        if not prova:
            did = db.salva_documento(
                {"tipo": tipo, "anno": anno, "numero": numero, "suffisso": "", "data": data, "cliente_id": cli["id"],
                 "terzo_pagatore": "", "note": s(f.get("Causale / note in fattura")), "bollo": 0,
                 "rif_numero": s(f.get("Rif. fattura (numero)")), "rif_data": s(f.get("Rif. fattura (data)"))[:10],
                 "totale": totale, "netto": totale}, righe or [{"tipo": "onorario", "descrizione": "", "importo": ""}])
            db.aggiorna_documento(did, stato=stato, storico=1, inviato_il=data,
                                  esito_note=f"Programma Excel: {s(f.get('Stato (lo scrive lo script)'))}"
                                             + (f" - {s(f.get('Esito SDI'))}" if s(f.get("Esito SDI")) else ""),
                                  imponibile=s(f.get("Imponibile")), iva=s(f.get("IVA")), saldato=0)
        msg.append(f"{numero}/{anno}: importata dal programma Excel ({stato}, da incassare)")
    return msg


def importa_pec(cartella, prova):
    """Indirizzo SDI dedicato e progressivo dei file XML dal programma Excel."""
    msg = []
    p = cartella / "pec_config.json"
    if p.exists():
        sdi = json.loads(p.read_text(encoding="utf-8")).get("indirizzo_sdi", "")
        if re.fullmatch(r"sdi\d+@pec\.fatturapa\.it", sdi or "") and sdi != "sdi01@pec.fatturapa.it":
            if not prova:
                db.salva_impostazione("pec.indirizzo_sdi", sdi)
            msg.append(f"indirizzo SDI dedicato: {sdi}")
    for f in cartella.glob("progressivo_*.txt"):
        ultimo = f.read_text().strip()
        if ultimo.isdigit():
            attuale = int(db.impostazione("progressivo", "0") or 0)
            if int(ultimo) > attuale:
                if not prova:
                    db.salva_impostazione("progressivo", ultimo)
                msg.append(f"progressivo XML: l'ultimo usato è {int(ultimo):05d}, il prossimo sarà {int(ultimo) + 1:05d}")
    return msg


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prova = "--prova" in sys.argv
    if len(args) != 1:
        print(__doc__)
        sys.exit(1)
    excel = Path(args[0])
    db.inizializza()
    wb = openpyxl.load_workbook(excel, read_only=True, data_only=True)
    print(f"Codici IVA: {importa_codici(wb, prova)}")
    nuovi, aggiornati, avvisi = importa_clienti(wb, prova)
    print(f"Clienti: {nuovi} nuovi, {aggiornati} aggiornati")
    for m in importa_fatture(wb, prova):
        print(m)
    for m in importa_pec(excel.parent, prova):
        print(m)
    if avvisi:
        print("\nDa controllare:")
        for a in avvisi:
            print("  ", a)
    if prova:
        print("\nProva: non ho scritto nulla.")


if __name__ == "__main__":
    main()
