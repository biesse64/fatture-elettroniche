#!/usr/bin/env python3
"""
Bozze di fattura dal foglio presenze, direttamente nel programma Fatture Consept (web).

Per ogni cliente con giornate nel mese crea una fattura in stato BOZZA (data = primo del mese
successivo) con una voce: "Descrizione – mese" e l'elenco delle giornate, quantita' in giornate
(g = 1, m/p = 0,5) x tariffa. Poi le controlli e le generi dal programma come sempre.

Uso (il programma puo' restare aperto):
    python3 bozze_presenze.py                      mese precedente
    python3 bozze_presenze.py --mese 2026-10       mese indicato (anche 10/2026)
    python3 bozze_presenze.py --mese 2026-10 --prova   mostra cosa farebbe, senza scrivere nulla

Tariffe, cliente e descrizione per ogni cliente del foglio presenze: bozze_presenze.json in questa
cartella (creato al primo avvio con valori iniziali, poi lo modifichi tu).
Numerazione: primo numero libero dopo l'ultima fattura emessa (le bozze cancellate liberano il numero).
Una bozza gia' creata per lo stesso cliente e mese non viene rifatta finche' esiste nel programma.
"""
import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
import calcoli_studio as K   # noqa: E402
import config_studio as C   # noqa: E402
import db_studio as db      # noqa: E402

PRESENZE_DIR = Path("/System/Volumes/Data/clienti/calendario_new")
CONFIG = QUI / "bozze_presenze.json"
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre"]
QTA = {"g": Decimal("1"), "m": Decimal("0.5"), "p": Decimal("0.5")}
# valori iniziali: codice cliente del programma (quello della scheda cliente), tariffa, descrizione
INIZIALI = {
    "angeloni": ("187", "850", "Consulenza implementazione ERP", True),
    "belvest": ("1", "850", "Consulenza analisi di processo", True),
    "wisycom": ("206", "850", "Consulenza", True),
    "agraticpim": ("212", "850", "Consulenza", True),
    "forema": ("25", "850", "Consulenza", True),
    "enerblue": ("150", "850", "Consulenza", True),
    "santex": ("219", "850", "Consulenza", True),
    "linkmanagement": ("122", "850", "Consulenza", True),
    "niuko": ("58", "850", "Consulenza", True),
    "leoron": ("176", "850", "Consulenza", True),
    "consept": ("", "0", "", False),
    "prospect": ("", "0", "", False),
}


def norm(t):
    return re.sub(r"[^a-z0-9]", "", str(t or "").lower())


def euro(x):
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gg(q):
    return f"{q.normalize():f}".replace(".", ",")


def leggi_presenze(path, anno, mese):
    """({titolo: [(data, codice)]} del mese, avvisi, tutti i clienti del foglio Impostazioni)."""
    sys.path.insert(0, str(path.parent))
    import pandas as pd
    import sincronizza_presenze as SP
    book = pd.read_excel(path, sheet_name=None, header=None, engine="odf" if path.suffix == ".ods" else None)
    conf = SP.leggi_impostazioni(book)
    for c in conf["clienti"]:
        c["sync"] = True          # per fatturare servono tutti i clienti, anche quelli non sincronizzati
    avvisi = []
    out = {}
    for w in SP.leggi_presenze(book, conf, avvisi).values():
        if w["day"].year == anno and w["day"].month == mese:
            out.setdefault(w["cliente"]["titolo"], []).append((w["day"], w["code"]))
    return ({k: sorted(v) for k, v in out.items()}, [a for a in avvisi if "sconosciuto" in a],
            [c["titolo"] for c in conf["clienti"]])


def leggi_config(titoli):
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    except json.JSONDecodeError as e:
        sys.exit(f"ERRORE in {CONFIG.name}, riga {e.lineno}: {e.msg}.\n"
                 "Controlla virgolette e virgole (ogni voce tranne l'ultima finisce con una virgola). Nessuna bozza creata.")
    cfg.setdefault("_istruzioni", "Per ogni cliente del foglio presenze: 'cliente' = codice del cliente nel "
                   "programma fatture (vuoto = non fatturo, te lo segnala), 'tariffa' = importo di una giornata (g; "
                   "m/p = meta'), 'descrizione' = prima parte della voce (lo script aggiunge mese e giornate), "
                   "'fatturare' = false per i clienti interni.")
    clienti = cfg.setdefault("clienti", {})
    cfg.setdefault("create", {})
    nuovi = []
    for t in titoli:
        if not any(norm(k) == norm(t) for k in clienti):
            cod, tar, descr, fatt = INIZIALI.get(norm(t), ("", "850", "Consulenza", True))
            clienti[t] = {"cliente": cod, "tariffa": tar, "descrizione": descr, "fatturare": fatt}
            nuovi.append(t)
    return cfg, nuovi


def scrivi_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def numeri_liberi(anno):
    """Primo numero libero dopo l'ultima fattura/nota di credito emessa: i buchi lasciati dalle bozze
    cancellate vengono riusati (numerazione senza salti)."""
    with db.conn() as c:
        righe = c.execute("SELECT numero, stato FROM documenti WHERE anno = ? AND tipo != 'AVV' AND suffisso = ''",
                          (anno,)).fetchall()
    usati = {r["numero"] for r in righe}
    base = max((r["numero"] for r in righe if r["stato"] != "bozza"), default=0)
    primo = db.impostazione(f"primo_numero.{anno}", "")
    if primo.isdigit():
        base = max(base, int(primo) - 1)
    n = base + 1
    while True:
        if n not in usati:
            yield n
        n += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mese", help="AAAA-MM oppure MM/AAAA (default: mese precedente)")
    ap.add_argument("--cartella-presenze", help="cartella del foglio presenze (default: calendario_new)")
    ap.add_argument("--presenze", help="file presenze (default: presenze_<anno>.ods nella cartella presenze)")
    ap.add_argument("--prova", action="store_true", help="mostra cosa farebbe, senza scrivere nulla")
    a = ap.parse_args()

    oggi = date.today()
    if a.mese:
        s = a.mese.strip()
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", s)
        m2 = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
        if m:
            anno, mese = int(m.group(1)), int(m.group(2))
        elif m2:
            anno, mese = int(m2.group(2)), int(m2.group(1))
        else:
            sys.exit("Mese non valido: scrivi MM/AAAA (es. 10/2026)")
    else:
        anno, mese = (oggi.year, oggi.month - 1) if oggi.month > 1 else (oggi.year - 1, 12)
    if not 1 <= mese <= 12:
        sys.exit("Mese non valido: scrivi MM/AAAA (es. 10/2026)")
    data_fatt = date(anno + (mese == 12), mese % 12 + 1, 1)
    nome_mese = f"{MESI[mese - 1]} {anno}"
    cart = Path(a.cartella_presenze) if a.cartella_presenze else PRESENZE_DIR
    presenze = Path(a.presenze) if a.presenze else cart / f"presenze_{anno}.ods"
    if not presenze.exists():
        sys.exit(f"ERRORE: non trovo il foglio presenze {presenze}")
    if not C.DB_PATH.exists():
        sys.exit(f"ERRORE: non trovo l'archivio del programma fatture {C.DB_PATH}")

    print(f"Bozze fatture {nome_mese} — data fattura {data_fatt:%d/%m/%Y}" + ("\n(anteprima: nessuna bozza ancora creata)" if a.prova else ""))
    print()
    giornate, avvisi, tutti = leggi_presenze(presenze, anno, mese)
    cfg, nuovi = leggi_config(tutti + sorted(set(giornate) - set(tutti)))
    clienti_cfg = {norm(k): v for k, v in cfg["clienti"].items()}
    liberi = numeri_liberi(data_fatt.year)
    tabella = K.codici()

    create, saltate, totale = [], [], Decimal("0")
    for titolo, giorni in sorted(giornate.items()):
        cf = clienti_cfg.get(norm(titolo), {})
        qta = sum((QTA.get(c, Decimal("1")) for _, c in giorni), Decimal("0"))
        riass = f"{titolo}: {gg(qta)} giornate"
        if not cf.get("fatturare", True):
            saltate.append(f"  --  {riass}  (fatturare = no)")
            continue
        cod = str(cf.get("cliente") or "").strip()
        cli = db.cliente_per_codice(cod) if cod else None
        if not cod:
            saltate.append(f"  !!  {riass}  → manca il cliente in bozze_presenze.json")
            continue
        if not cli:
            saltate.append(f"  !!  {riass}  → cliente con codice {cod} non trovato nel programma")
            continue
        chiave = f"{anno}-{mese:02d}|{norm(titolo)}"
        prec = cfg["create"].get(chiave)
        if prec:
            d, _ = db.documento(prec["id"])
            if d:
                saltate.append(f"  ==  {riass}  → bozza già creata (n. {d['numero']}/{d['anno']}, {d['stato']})")
                continue
        try:
            tariffa = Decimal(str(cf.get("tariffa", "850")).replace(",", "."))
        except Exception:
            saltate.append(f"  !!  {riass}  → tariffa non valida in bozze_presenze.json")
            continue
        importo = K.q2(qta * tariffa)
        elenco = ", ".join(f"{d:%d/%m/%Y} ({c.upper()})" for d, c in giorni)
        descr = f"{(cf.get('descrizione') or 'Consulenza').strip()} – {nome_mese}\nGiornate: {elenco}"
        riga = {"tipo": "onorario", "descrizione": descr, "importo": str(importo),
                "quantita": f"{qta.normalize():f}", "um": "giorni", "prezzo": str(K.q2(tariffa)),
                "codice_iva": cli["codice_iva"] or "", "prezzo_valuta": "", "importo_valuta": ""}
        tot = importo
        try:
            tot = K.totali(K.linee(K.leggi_righe_db([riga]), cli, tabella), tabella)["totale"]
        except ValueError:
            pass
        num = next(liberi)
        totale += importo
        create.append({"titolo": titolo, "chiave": chiave, "cli": cli, "riga": riga, "numero": num,
                       "importo": importo, "totale": tot, "qta": qta, "tariffa": tariffa})

    for c in create:
        print(f"  OK  n. {c['numero']}/{data_fatt.year}  {c['cli']['denominazione'][:40]:<40} "
              f"{gg(c['qta']):>4} gg x {euro(c['tariffa'])} = {euro(c['importo']):>9} € (totale {euro(c['totale'])} €)")
        print("        " + c["riga"]["descrizione"].replace("\n", "\n        "))
    if saltate:
        print("\nNon create:")
        print("\n".join(saltate))
    for av in avvisi:
        print(f"  NB  {av}")
    if nuovi:
        print(f"\nAggiunti a bozze_presenze.json (tariffa 850, da controllare): {', '.join(nuovi)}")
    print(f"\nBozze: {len(create)}   imponibile: {euro(totale)} €")
    if a.prova:
        return

    if create:
        copia = C.DATI / "copie_bozze"
        copia.mkdir(exist_ok=True)
        shutil.copy2(C.DB_PATH, copia / f"studio_prima_bozze_{datetime.now():%Y%m%d_%H%M%S}.db")
    for c in create:
        cli = c["cli"]
        dati = {"tipo": "TD01", "anno": data_fatt.year, "numero": c["numero"], "suffisso": "",
                "data": data_fatt.isoformat(), "cliente_id": cli["id"], "terzo_pagatore": "", "note": "",
                "bollo": 0, "rif_numero": "", "rif_data": "", "pagamento": cli["pagamento"] or "",
                "banca_id": None, "valuta": "", "cambio": "",
                "totale": str(c["totale"]), "netto": str(c["totale"])}
        did = db.salva_documento(dati, [c["riga"]])
        cfg["create"][c["chiave"]] = {"id": did, "numero": c["numero"], "creata_il": db.adesso()}
    scrivi_config(cfg)
    if create:
        print("Bozze create nel programma Fatture Consept (copia dell'archivio in dati/copie_bozze/).")


if __name__ == "__main__":
    main()
