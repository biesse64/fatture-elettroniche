"""
Import di un ELENCO di fatture esportato da Easyfatt in Excel (es. tutte le fatture 2025), solo con
i totali: serve a tenere sotto controllo gli incassi degli anni passati senza ricopiare le voci.

Colonne attese: Tipo doc., Data, N., Cliente, Stato, Commento, Tot. dovuto, Ancora da saldare,
Stato fatt. elettronica.

Uso (a programma chiuso), dalla cartella del programma:
    python3 importa_elenco.py Fatture_2025.xlsx            (--prova per controllare senza scrivere)

- Il cliente viene cercato per nome tra quelli in archivio (anche con piccole differenze di scrittura);
  se non c'e' viene creato con il solo nome, da completare.
- "Ancora da saldare" > 0  -> da incassare; altrimenti saldata (data non registrata).
- Si puo' rilanciare: i documenti gia' presenti (stesso anno e numero) vengono saltati.
"""
import difflib
import re
import sys
import unicodedata
from decimal import Decimal

import openpyxl

import db_studio as db

TERZO = re.compile(r"effettuato da\s+(.+?)\s+terza solvente", re.I)


def normale(nome):
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def stato_sdi(testo):
    t = (testo or "").lower()
    if t.startswith("scartata"):
        return "scartata"
    if "cassetto" in t:
        return "mancata"               # consegnata nell'area riservata del cliente
    return "consegnata"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prova = "--prova" in sys.argv
    if len(args) != 1:
        print(__doc__)
        sys.exit(1)
    db.inizializza()
    ws = openpyxl.load_workbook(args[0], read_only=True, data_only=True).active
    righe = ws.iter_rows(values_only=True)
    col = {str(h or "").strip(): i for i, h in enumerate(next(righe))}
    clienti = {normale(c["denominazione"]): c for c in db.clienti()}
    nuovi, da_incassare, avvisi = 0, [], []
    for r in righe:
        v = lambda h: r[col[h]] if h in col and col[h] < len(r) else None
        if not v("Tipo doc.") or not v("N."):
            continue                                       # riga dei totali
        tipo = "TD04" if "credito" in str(v("Tipo doc.")).lower() else "TD01"
        data = v("Data").date().isoformat() if hasattr(v("Data"), "date") else str(v("Data"))[:10]
        m = re.match(r"^(\d+)(?:/([A-Za-z]+))?$", str(v("N.")).strip())
        numero, suffisso = int(m.group(1)), (m.group(2) or "").upper()
        anno = int(data[:4])
        totale = abs(Decimal(str(v("Tot. dovuto") or 0))).quantize(Decimal("0.01"))
        residuo = abs(Decimal(str(v("Ancora da saldare") or 0))).quantize(Decimal("0.01"))
        nome = str(v("Cliente") or "").strip()
        cli = clienti.get(normale(nome))
        if not cli:
            simili = difflib.get_close_matches(normale(nome), list(clienti), n=1, cutoff=0.88)
            if simili:
                cli = clienti[simili[0]]
                avvisi.append(f"n. {numero}/{anno}: cliente «{nome}» abbinato a «{cli['denominazione']}»")
        commento = str(v("Commento") or "").strip()
        t = TERZO.search(commento)
        stato = stato_sdi(v("Stato fatt. elettronica"))
        if residuo > 0 and tipo == "TD01":
            da_incassare.append(f"n. {numero}/{anno} {nome}: {residuo} su {totale}")
        if prova or db.documento_per_numero(anno, numero, suffisso):
            continue
        if not cli:
            cid = db.salva_cliente({"denominazione": nome, "nazione": "IT",
                                    "note": "Creato dall'elenco Easyfatt: completare i dati"})
            cli = db.cliente(cid)
            clienti[normale(nome)] = cli
            avvisi.append(f"n. {numero}/{anno}: cliente «{nome}» non in archivio, creato con il solo nome")
        dati = {"tipo": tipo, "anno": anno, "numero": numero, "suffisso": suffisso, "data": data,
                "cliente_id": cli["id"], "terzo_pagatore": re.sub(r"\s+", " ", t.group(1)).strip() if t else "",
                "note": "" if t else commento, "bollo": 0, "rif_numero": "", "rif_data": "",
                "totale": str(totale), "netto": str(totale)}
        righe_doc = [{"tipo": "onorario", "descrizione": "Fattura importata dall'elenco Easyfatt (voci in Easyfatt)",
                      "importo": ""}]
        did = db.salva_documento(dati, righe_doc)
        db.aggiorna_documento(did, stato=stato, storico=1, inviato_il=data,
                              esito_note=str(v("Stato fatt. elettronica") or "Inviata con Easyfatt")[:300],
                              saldato=0 if (residuo > 0 and tipo == "TD01") else 1)
        nuovi += 1
    for a in avvisi:
        print("  ", a)
    print(f"Documenti importati ora: {nuovi}")
    print("Da incassare:", "; ".join(da_incassare) or "nessuna")
    if prova:
        print("Prova: non ho scritto nulla.")


if __name__ == "__main__":
    main()
