"""
Import dagli export di Easyfatt (Consept).

    python3 importa_easyfatt.py codici_iva.xlsx              codici IVA di vendita
    python3 importa_easyfatt.py storico_fatture_tutte.xlsx   elenco fatture (solo totali) dal 2018

Il tipo di file si riconosce dalle intestazioni. --prova per controllare senza scrivere.
Si puo' rilanciare: codici e documenti gia' presenti non vengono toccati.

Dallo storico: i documenti entrano come "programma precedente", con totale, imponibile e IVA ma senza
le voci (restano in Easyfatt); "Ancora da saldare" > 0 -> da incassare, altrimenti saldata.
"""
import re
import sys
from datetime import date, datetime
from decimal import Decimal

import openpyxl

import db_studio as db

# codici IVA di Easyfatt che riguardano gli acquisti o casi che il programma non gestisce ancora
GRUPPI_ESCLUSI = ("Acq. reverse charge", "Split payment")
CODICI_ESCLUSI = {"22d", "22d40", "22i",        # detraibilita': solo acquisti
                  "N3", "N8",                   # natura generica non piu' ammessa / sostituito da N8a-b-c
                  "RF",                         # regime forfettario
                  "NS7u"}                       # = NS7UE gia' presente (inversione contabile UE)
ALIAS_CODICI = {"NS7u": "NS7UE"}


def s(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def dec(v):
    return abs(Decimal(str(v or 0))).quantize(Decimal("0.01"))


# ---------------------------------------------------------------- codici IVA
def importa_codici(ws, prova):
    nuovi, gia, saltati = [], [], []
    gruppo = ""
    for r in ws.iter_rows(min_row=2, values_only=True):
        if s(r[0]) == "-":                       # riga di gruppo: "-", "N2:  Non soggetto ..."
            gruppo = s(r[1])
            continue
        cod, natura_txt, rif, nota = s(r[1]), s(r[2]), s(r[3]), s(r[4])
        if not cod:
            continue
        if gruppo.startswith(GRUPPI_ESCLUSI) or cod in CODICI_ESCLUSI:
            saltati.append(cod)
            continue
        if natura_txt == "Imponibile":
            aliquota, natura, rif_norm, descr = re.match(r"\d+", cod).group(0), "", "", rif
        else:
            m = re.match(r"(N\d(?:\.\d)?)", natura_txt)
            if not m:
                saltati.append(cod)
                continue
            aliquota, natura, rif_norm, descr = "0", m.group(1), rif, nota or rif
        if db.codice_iva(cod):
            gia.append(cod)
            continue
        if not prova:
            db.salva_codice_iva({"codice": cod, "aliquota": aliquota, "natura": natura, "rif_norm": rif_norm[:100],
                                 "bollo": 1 if natura else 0, "descrizione": descr})
        nuovi.append(cod)
    print(f"Codici IVA nuovi: {len(nuovi)} ({', '.join(nuovi)})")
    print(f"Già presenti: {', '.join(gia) or 'nessuno'}")
    print(f"Non importati (acquisti, split payment, superati): {', '.join(saltati)}")


# ---------------------------------------------------------------- storico fatture
def stato_sdi(testo):
    t = (testo or "").lower()
    if t.startswith("scartata"):
        return "scartata"
    return "consegnata"                          # anche "cassetto fiscale": e' comunque recapitata


def importa_storico(ws, prova):
    righe = ws.iter_rows(values_only=True)
    col = {s(h): i for i, h in enumerate(next(righe))}
    v = lambda r, h: r[col[h]] if h in col and col[h] < len(r) else None
    nuovi, presenti, da_incassare, avvisi = 0, 0, [], []
    per_anno = {}
    for r in righe:
        if not v(r, "Tipo doc.") or not v(r, "N."):
            continue
        tipo = "TD04" if "credito" in s(v(r, "Tipo doc.")).lower() else "TD01"
        data = v(r, "Data").date() if hasattr(v(r, "Data"), "date") else date.fromisoformat(s(v(r, "Data"))[:10])
        m = re.match(r"^(\d+)(?:/([A-Za-z]+))?/(\d{4})$", s(v(r, "N.")))
        if not m:
            avvisi.append(f"numero non riconosciuto: {s(v(r, 'N.'))}")
            continue
        numero, suffisso, anno = int(m.group(1)), (m.group(2) or "").upper(), int(m.group(3))
        totale, imponibile, iva = dec(v(r, "Tot. documento")), dec(v(r, "Tot. netto Iva")), dec(v(r, "Iva"))
        residuo = dec(v(r, "Ancora da saldare"))
        codice = s(v(r, "Cod. cliente"))
        nome = s(v(r, "Cliente"))
        per_anno[anno] = per_anno.get(anno, 0) + 1
        if tipo == "TD01" and residuo > 0:
            da_incassare.append(f"{numero}/{anno} {nome}: {residuo} €")
        esistente = db.documento_per_numero(anno, numero, suffisso)
        if esistente and esistente["data"] != data.isoformat() and not suffisso:
            # stesso numero usato due volte in Easyfatt (es. 5/2019 del 22/01/2020): il secondo diventa 5/B
            suffisso = "B"
            avvisi.append(f"{numero}/{anno} del {data:%d/%m/%Y}: numero già usato, registrato come {numero}/B/{anno}")
            esistente = db.documento_per_numero(anno, numero, suffisso)
        if esistente:
            presenti += 1
            continue
        if prova:
            nuovi += 1
            continue
        cli = db.cliente_per_codice(codice) if codice else None
        if not cli:
            piva = s(v(r, "PI cliente"))
            cid = db.salva_cliente({"denominazione": nome, "piva": piva, "cf": s(v(r, "CF cliente")),
                                    "nazione": "IT" if s(v(r, "Nazione cliente")) in ("", "Italia") else "",
                                    "note": "Creato dallo storico Easyfatt: completare i dati"})
            with db.conn() as c:
                c.execute("UPDATE clienti SET codice = ? WHERE id = ?", (codice, cid))
            cli = db.cliente(cid)
            avvisi.append(f"{numero}/{anno}: cliente {codice} «{nome}» non in archivio, creato con i dati dell'elenco")
        stato_fe = s(v(r, "Stato fatt. elettronica"))
        did = db.salva_documento(
            {"tipo": tipo, "anno": anno, "numero": numero, "suffisso": suffisso, "data": data.isoformat(),
             "cliente_id": cli["id"], "terzo_pagatore": "", "note": s(v(r, "Commento")), "bollo": 0,
             "rif_numero": "", "rif_data": "", "totale": str(totale), "netto": str(totale)},
            [{"tipo": "onorario", "descrizione": "Documento importato dall'elenco Easyfatt (voci in Easyfatt)",
              "importo": ""}])
        db.aggiorna_documento(did, stato=stato_sdi(stato_fe), storico=1, inviato_il=data.isoformat(),
                              esito_note=(stato_fe or "Easyfatt: stato non indicato")[:300],
                              imponibile=str(imponibile), iva=str(iva),
                              saldato=0 if (tipo == "TD01" and residuo > 0) else 1)
        nuovi += 1
    print(f"Documenti per anno: {', '.join(f'{a}: {n}' for a, n in sorted(per_anno.items()))}")
    print(f"Importati ora: {nuovi}; già presenti: {presenti}")
    print("Da incassare:", "; ".join(da_incassare) or "nessuna")
    for a in avvisi:
        print("  ", a)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prova = "--prova" in sys.argv
    if len(args) != 1:
        print(__doc__)
        sys.exit(1)
    db.inizializza()
    ws = openpyxl.load_workbook(args[0], read_only=True, data_only=True).active
    intest = [s(c) for c in next(ws.iter_rows(max_row=1, values_only=True))]
    if "Codice Iva" in intest:
        importa_codici(ws, prova)
    elif "Tipo doc." in intest:
        importa_storico(ws, prova)
    else:
        sys.exit("File non riconosciuto: servono l'export dei codici IVA o l'elenco fatture di Easyfatt.")
    if prova:
        print("Prova: non ho scritto nulla.")


if __name__ == "__main__":
    main()
