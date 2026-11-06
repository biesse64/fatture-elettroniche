"""
Import di fatture gia' emesse da file FatturaPA (XML), con le ricevute dello SDI se presenti.

Uso (a programma chiuso), dalla cartella del programma:
    python3 importa_xml.py CARTELLA_CON_GLI_XML
    python3 importa_xml.py CARTELLA_CON_GLI_XML --prova          (controlla senza scrivere)

- Legge tutte le fatture (TD01) e note di credito (TD04) della posizione (P.IVA del config).
- I clienti mancanti vengono creati dai dati della fattura (riconosciuti per P.IVA o codice fiscale).
- Se nella cartella ci sono le ricevute di consegna (..._RC_...xml) ed e' presente l'elenco export.xls
  del vecchio programma, ne prende identificativo SDI e data; altrimenti le fatture entrano come consegnate.
- Le fatture importate risultano "da incassare": segnale saldate dalla pagina "Da incassare".
- Si puo' rilanciare: le fatture gia' presenti (stesso anno e numero) vengono saltate.
"""
import re
import sys
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
    righe = []
    for dl in x.xpath(L("FatturaElettronicaBody", "DatiBeniServizi", "DettaglioLinee")):
        g = lambda tag: _testo(dl, _locale(tag))
        tot, qta, prezzo = g("PrezzoTotale"), g("Quantita"), g("PrezzoUnitario")
        if not tot or (Decimal(tot) == 0 and not qta):
            righe.append({"tipo": "onorario", "descrizione": g("Descrizione"), "importo": ""})
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
            "bollo": 0, "terzo_pagatore": "", "cliente": cli, "righe": righe,
            "totale_xml": Decimal(t(*dgd, "ImportoTotaleDocumento") or "0"),
            "file": path.name}


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
    if len(args) != 1:
        print(__doc__)
        sys.exit(1)
    cartella = Path(args[0])
    db.inizializza()
    ricevute, abbinamenti = leggi_ricevute(cartella)
    fatture = []
    for p in sorted(cartella.rglob("*.xml")):
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
        fatture.append(f)
    fatture.sort(key=lambda f: (f["anno"], f["numero"]))

    nuove, diverse = 0, []
    for f in fatture:
        calc = [{"tipo": r["tipo"], "importo": Decimal(r["importo"]) if r["importo"] else None} for r in f["righe"]]
        tot = totali(calc, False)
        if tot["totale"] != f["totale_xml"]:
            diverse.append(f"n. {f['numero']}: nel file {f['totale_xml']}, ricalcolato {tot['totale']}")
        ric = ricevute.get(abbinamenti.get(f["file"], ""), {})
        print(f"  {f['numero']:>4}/{f['anno']}  {f['data']}  {f['cliente']['denominazione'][:40]:<40} "
              f"{tot['totale']:>10}  netto {tot['netto']:>10}  {ric.get('stato', 'consegnata (senza ricevuta)')}"
              + (f" id SDI {ric['id_sdi']}" if ric.get("id_sdi") else ""))
        if prova or db.documento_per_numero(f["anno"], f["numero"], f["suffisso"]):
            continue
        cli = cliente_per_fiscale(f["cliente"])
        cid = cli["id"] if cli else db.salva_cliente(f["cliente"])
        dati = {k: f[k] for k in ("tipo", "anno", "numero", "suffisso", "data", "note", "bollo", "terzo_pagatore",
                                  "rif_numero", "rif_data")}
        if f["tipo"] == "TD04" and f["rif_numero"] and not re.search(r"/\d{4}$", f["rif_numero"]):
            dati["rif_numero"] = f"{f['rif_numero']}/{(f['rif_data'] or f['data'])[:4]}"
        dati.update(cliente_id=cid, totale=str(tot["totale"]), netto=str(tot["netto"]))
        did = db.salva_documento(dati, f["righe"])
        db.aggiorna_documento(did, stato=ric.get("stato", "consegnata"), storico=1, esito_note=NOTA_STORICO,
                              id_sdi=ric.get("id_sdi", ""), inviato_il=ric.get("data") or f["data"],
                              esito_il=ric.get("data", ""))
        nuove += 1
    print(f"Fatture nella cartella: {len(fatture)}; importate ora: {nuove}")
    print(f"Totali uguali al file: {len(fatture) - len(diverse)} su {len(fatture)}")
    for d in diverse:
        print("  totale diverso:", d)
    if prova:
        print("Prova: non ho scritto nulla.")


if __name__ == "__main__":
    main()
