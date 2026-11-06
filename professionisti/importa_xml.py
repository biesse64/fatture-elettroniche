"""
Import di fatture gia' emesse da file FatturaPA (XML), con le ricevute dello SDI se presenti.

Uso (a programma chiuso), dalla cartella del programma:
    python3 importa_xml.py CARTELLA_CON_GLI_XML
    python3 importa_xml.py CARTELLA_CON_GLI_XML --prova          (controlla senza scrivere)

- Legge tutte le fatture (TD01) e note di credito (TD04) della posizione (P.IVA del config).
- I clienti mancanti vengono creati dai dati della fattura (riconosciuti per P.IVA o codice fiscale).
- Se nella cartella ci sono le ricevute di consegna (..._RC_...xml) ed e' presente l'elenco export.xls
  del vecchio programma, ne prende identificativo SDI e data; altrimenti le fatture entrano come consegnate.
- Il file originale viene archiviato in dati/uscita/<anno>/originali/: scheda e copia PDF riportano gli
  importi del file cosi' come e' stato inviato, anche dove le regole di allora erano diverse da quelle attuali.
- Le fatture degli anni passati entrano come saldate, quelle dell'anno in corso come da incassare.
- Si puo' rilanciare: le fatture gia' presenti (stesso anno e numero) vengono saltate; a quelle importate
  prima senza il file originale il file viene aggiunto.

Fattura generata e inviata con QUESTO programma ma persa dall'archivio (es. ripristino da una copia):
    python3 importa_xml.py dati/uscita/2026/10-ottobre/ITPLLMGH67P55G337Y_00001.xml --inviata
rientra come "Inviata, in attesa di esito" con lo stesso file e lo stesso contatore dei file XML; poi
"Aggiorna esiti SDI" ritrova la ricevuta nella PEC e completa esito, identificativo e indirizzo SDI.
"""
import re
import shutil
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from lxml import etree

import config_studio as C
import db_studio as db
from calcoli_studio import q2, totali

NOTA_STORICO = "Inviata con il programma precedente"


def _testo(x, percorso):
    r = x.xpath(percorso)
    return (r[0].text or "").strip() if r else ""


def _locale(tag):
    return f"*[local-name()='{tag}']"


def leggi_fattura(path):
    x = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True))
    L = lambda *tags: "/".join(["/"] + [_locale(t) for t in tags])
    t = lambda *tags: _testo(x, L(*tags))
    if not x.xpath(L("FatturaElettronicaHeader")):
        return None
    ced = t("CedentePrestatore", "DatiAnagrafici", "IdFiscaleIVA", "IdCodice")
    cc = ["CessionarioCommittente"]
    cli = {"denominazione": t(*cc, "DatiAnagrafici", "Anagrafica", "Denominazione")
                            or f"{t(*cc, 'DatiAnagrafici', 'Anagrafica', 'Nome')} "
                               f"{t(*cc, 'DatiAnagrafici', 'Anagrafica', 'Cognome')}".strip(),
           "piva": t(*cc, "DatiAnagrafici", "IdFiscaleIVA", "IdCodice"),
           "cf": t(*cc, "DatiAnagrafici", "CodiceFiscale").upper(),
           "indirizzo": t(*cc, "Sede", "Indirizzo"), "cap": t(*cc, "Sede", "CAP"),
           "comune": t(*cc, "Sede", "Comune"), "provincia": t(*cc, "Sede", "Provincia"),
           "nazione": t(*cc, "Sede", "Nazione") or "IT",
           "codice_destinatario": t("DatiTrasmissione", "CodiceDestinatario"),
           "pec": t("DatiTrasmissione", "PECDestinatario"), "email": "", "note": ""}
    if cli["piva"].startswith("OO") or cli["nazione"] != "IT":
        cli["piva"] = "" if cli["piva"].startswith("OO") else cli["piva"]
    dgd = ["FatturaElettronicaBody", "DatiGenerali", "DatiGeneraliDocumento"]
    numero = t(*dgd, "Numero")
    m = re.match(r"^(\d+)(?:/([A-Za-z]+))?(?:/(\d{4}))?$", numero)
    if not m:
        raise ValueError(f"{path.name}: numero {numero!r} non riconosciuto")
    righe, bollo = [], 0
    for dl in x.xpath(L("FatturaElettronicaBody", "DatiBeniServizi", "DettaglioLinee")):
        g = lambda tag: _testo(dl, _locale(tag))
        tot, qta, prezzo = g("PrezzoTotale"), g("Quantita"), g("PrezzoUnitario")
        if not tot or (Decimal(tot) == 0 and not qta):
            righe.append({"tipo": "onorario", "descrizione": g("Descrizione"), "importo": ""})
            continue
        if C.BOLLO and g("Descrizione").strip().lower() == C.BOLLO["descrizione"].lower() \
                and Decimal(tot) == Decimal(C.BOLLO["importo"]):
            bollo = 1                            # riga del bollo aggiunta dal programma: torna l'opzione bollo
            continue
        anticip = g("Natura").startswith("N1") or g("TipoCessionePrestazione") == "AC"
        riga = {"tipo": "anticipazione" if anticip else "onorario", "descrizione": g("Descrizione"),
                "importo": str(q2(Decimal(tot)))}
        if qta and Decimal(qta) != 1:
            riga.update(quantita=str(q2(Decimal(qta))), um=g("UnitaMisura"), prezzo=str(q2(Decimal(prezzo))))
        righe.append(riga)
    rif = x.xpath(L("FatturaElettronicaBody", "DatiGenerali", "DatiFattureCollegate"))
    data = t(*dgd, "Data")
    return {"cedente": ced, "tipo": t(*dgd, "TipoDocumento"), "numero": int(m.group(1)),
            "suffisso": (m.group(2) or "").upper(), "data": data, "anno": int(data[:4]),
            "note": " ".join(c.text or "" for c in x.xpath(L(*dgd, "Causale"))).strip(),
            "rif_numero": _testo(rif[0], _locale("IdDocumento")) if rif else "",
            "rif_data": _testo(rif[0], _locale("Data")) if rif else "",
            "bollo": bollo, "terzo_pagatore": "", "cliente": cli, "righe": righe,
            "totale_xml": Decimal(t(*dgd, "ImportoTotaleDocumento") or "0"),
            "ritenuta_xml": Decimal(t(*dgd, "DatiRitenuta", "ImportoRitenuta") or "0"),
            "con_cassa": bool(x.xpath(L(*dgd, "DatiCassaPrevidenziale"))),
            "file": path.name, "percorso": path,
            "nome_sdi": (f"{t('DatiTrasmissione', 'IdTrasmittente', 'IdPaese')}"
                         f"{t('DatiTrasmissione', 'IdTrasmittente', 'IdCodice')}_"
                         f"{t('DatiTrasmissione', 'ProgressivoInvio')}.xml"),
            "progressivo": t("DatiTrasmissione", "ProgressivoInvio")}


def leggi_ricevute(cartella):
    """Ricevute SDI (RC consegna, MC mancata consegna) e, se c'e', l'abbinamento fattura->ricevuta di export.xls."""
    ricevute = {}
    for p in cartella.rglob("*_*_*.xml"):
        m = re.search(r"_(RC|MC)_\d{3}\.xml$", p.name)
        if not m:
            continue
        x = etree.parse(str(p), etree.XMLParser(resolve_entities=False, no_network=True))
        ricevute[p.name] = {"stato": "consegnata" if m.group(1) == "RC" else "mancata",
                            "id_sdi": _testo(x, "//" + _locale("IdentificativoSdI")),
                            "data": (_testo(x, "//" + _locale("DataOraRicezione")) or "")[:16].replace("T", " ")}
    abbinamenti = {}
    for xls in cartella.rglob("export.xls"):
        try:
            import xlrd
            sh = xlrd.open_workbook(str(xls), ignore_workbook_corruption=True).sheet_by_index(0)
            intest = sh.row_values(0)
            i1, i2 = intest.index("nome_file_ori_1"), intest.index("nome_file_ori_2")
            for r in range(1, sh.nrows):
                abbinamenti[sh.cell_value(r, i1)] = sh.cell_value(r, i2)
        except Exception as e:                       # export assente o illeggibile: si va senza ricevute
            print(f"  (export.xls non letto: {e})")
    return ricevute, abbinamenti


def terzo_dalla_causale(f):
    """'Il pagamento verra' effettuato da X terza solvente. note' -> terzo pagatore X e note."""
    modello = re.escape(C.TESTO_TERZO).replace(re.escape("{terzo}"), "(.+?)")
    m = re.search(modello, f["note"]) if getattr(C, "TESTO_TERZO", "") else None
    if m:
        f["terzo_pagatore"] = m.group(1).strip()
        f["note"] = (f["note"][:m.start()] + f["note"][m.end():]).strip()


def archivia_inviata(f):
    """Fattura di questo programma: il file torna in dati/uscita/<anno>/ con lo stesso nome (cosi' le ricevute
    dello SDI la riconoscono) e il contatore dei file XML non riparte da un numero gia' usato."""
    mesi = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
            "ottobre", "novembre", "dicembre")
    m = int(f["data"][5:7])
    cartella = C.USCITA / str(f["anno"]) / f"{m:02d}-{mesi[m - 1]}"       # come le fatture generate
    cartella.mkdir(parents=True, exist_ok=True)
    nome = f["nome_sdi"] if f["progressivo"] else f["file"]     # il nome con cui lo SDI lo conosce
    if f["percorso"].resolve() != (cartella / nome).resolve():
        shutil.copy2(f["percorso"], cartella / nome)
    if f["progressivo"].isdigit():
        attuale = int(db.impostazione("progressivo", "0") or 0)
        if int(f["progressivo"]) > attuale:
            db.salva_impostazione("progressivo", str(int(f["progressivo"])))
    return str((cartella / nome).relative_to(C.DATI)), f["progressivo"]


def archivia(f):
    """Copia il file originale in dati/uscita/<anno>/originali/ e ne restituisce il percorso relativo."""
    cartella = C.USCITA / str(f["anno"]) / "originali"
    cartella.mkdir(parents=True, exist_ok=True)
    shutil.copy2(f["percorso"], cartella / f["file"])
    return str((cartella / f["file"]).relative_to(C.DATI))


def cliente_per_fiscale(cli):
    with db.conn() as c:
        for campo in ("piva", "cf"):
            if cli[campo]:
                r = c.execute(f"SELECT * FROM clienti WHERE {campo} = ?", (cli[campo],)).fetchone()
                if r:
                    return r
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prova = "--prova" in sys.argv
    inviata = "--inviata" in sys.argv
    if len(args) != 1:
        print(__doc__)
        sys.exit(1)
    cartella = Path(args[0])
    db.inizializza()
    ricevute, abbinamenti = leggi_ricevute(cartella) if cartella.is_dir() else ({}, {})
    fatture = []
    for p in ([cartella] if cartella.is_file() else sorted(cartella.rglob("*.xml"))):
        if re.search(r"_(RC|NS|MC|NE|DT|AT|EC|SE|MT)_\d{3}\.xml$", p.name):
            continue
        try:
            f = leggi_fattura(p)
        except (etree.XMLSyntaxError, ValueError) as e:
            print(f"  salto {p.name}: {e}")
            continue
        if not f:
            continue
        if f["cedente"] != C.STUDIO["piva"]:
            print(f"  salto {p.name}: emessa da P.IVA {f['cedente']}, non da questa posizione")
            continue
        terzo_dalla_causale(f)
        fatture.append(f)
    fatture.sort(key=lambda f: (f["anno"], f["numero"]))

    nuove, originali, diverse = 0, 0, []
    for f in fatture:
        calc = [{"tipo": r["tipo"], "importo": Decimal(r["importo"]) if r["importo"] else None} for r in f["righe"]]
        tot = totali(calc, bool(f["bollo"]), bool(f["ritenuta_xml"]) or not getattr(C, "RITENUTA", None))
        if tot["totale"] != f["totale_xml"]:
            diverse.append(f"n. {f['numero']}: nel file {f['totale_xml']}, ricalcolato {tot['totale']}")
        ric = ricevute.get(abbinamenti.get(f["file"], ""), {})
        print(f"  {f['numero']:>4}/{f['anno']}  {f['data']}  {f['cliente']['denominazione'][:40]:<40} "
              f"{tot['totale']:>10}  netto {tot['netto']:>10}  {ric.get('stato', 'consegnata (senza ricevuta)')}"
              + (f" id SDI {ric['id_sdi']}" if ric.get("id_sdi") else ""))
        esistente = db.documento_per_numero(f["anno"], f["numero"], f["suffisso"])
        if inviata and esistente and esistente["storico"] and esistente["stato"] != "bozza":
            # importata prima senza --inviata: diventa "inviata, in attesa di esito" come se non fosse mai uscita
            if Decimal(esistente["totale"] or "0") != f["totale_xml"]:
                print(f"  n. {f['numero']}: in archivio c'e' un documento con totale {esistente['totale']}, "
                      f"nel file {f['totale_xml']}: non lo tocco")
                continue
            if not prova:
                rel, progressivo = archivia_inviata(f)
                db.aggiorna_documento(esistente["id"], stato="inviata", storico=0, file_xml=rel,
                                      progressivo=progressivo, id_sdi="", esito_il="",
                                      generato_il=db.adesso(), inviato_il=db.adesso(),
                                      esito_note="PEC a sdi (fattura reimportata dal suo file XML)")
            print(f"  n. {f['numero']}: era nello storico, ora e' inviata in attesa di esito")
            nuove += 1
            continue
        if esistente and esistente["storico"] and not esistente["file_xml"]:
            originali += 1
            if not prova:
                db.aggiorna_documento(esistente["id"], file_xml=archivia(f))
            continue
        if prova or esistente:
            continue
        cli = cliente_per_fiscale(f["cliente"])
        cid = cli["id"] if cli else db.salva_cliente(f["cliente"])
        dati = {k: f[k] for k in ("tipo", "anno", "numero", "suffisso", "data", "note", "bollo", "terzo_pagatore",
                                  "rif_numero", "rif_data")}
        if f["tipo"] == "TD04" and f["rif_numero"] and not re.search(r"/\d{4}$", f["rif_numero"]):
            dati["rif_numero"] = f"{f['rif_numero']}/{(f['rif_data'] or f['data'])[:4]}"
        if getattr(C, "RITENUTA", None) and not f["ritenuta_xml"]:
            dati["ritenuta"] = 0                  # emessa senza ritenuta (es. cliente privato, vendita)
        if C.CASSA and not f["con_cassa"] and getattr(C, "MOSTRA_VENDITE", False):
            for r in f["righe"]:                  # senza contributo: voci di vendita (IVA, niente cassa)
                if r["importo"] and r["tipo"] == "onorario":
                    r["tipo"] = "vendita"
        dati.update(cliente_id=cid, totale=str(f["totale_xml"]), netto=str(f["totale_xml"] - f["ritenuta_xml"]))
        did = db.salva_documento(dati, f["righe"])
        if inviata:                              # inviata da questo programma: l'esito lo legge dalla PEC
            rel, progressivo = archivia_inviata(f)
            db.aggiorna_documento(did, stato="inviata", storico=0, file_xml=rel, progressivo=progressivo,
                                  generato_il=db.adesso(), inviato_il=db.adesso(),
                                  esito_note="PEC a sdi (fattura reimportata dal suo file XML)")
            nuove += 1
            continue
        db.aggiorna_documento(did, stato=ric.get("stato", "consegnata"), storico=1, esito_note=NOTA_STORICO,
                              id_sdi=ric.get("id_sdi", ""), inviato_il=ric.get("data") or f["data"],
                              esito_il=ric.get("data", ""), file_xml=archivia(f),
                              saldato=1 if f["anno"] < date.today().year else 0)
        nuove += 1
    print(f"Fatture nella cartella: {len(fatture)}; importate ora: {nuove}; "
          f"già presenti, aggiunto il file originale: {originali}")
    print(f"Totali ricalcolabili con le regole attuali: {len(fatture) - len(diverse)} su {len(fatture)}")
    for d in diverse:
        print("  regole diverse da quelle attuali (scheda e PDF usano il file originale):", d)
    if prova:
        print("Prova: non ho scritto nulla.")


if __name__ == "__main__":
    main()
