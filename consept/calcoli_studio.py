"""
Calcoli di Consept: IVA di ogni riga dal suo codice IVA (riga -> cliente -> predefinito), riepilogo per
aliquota e natura, bollo virtuale (se attivo nelle Impostazioni), scadenze dalla condizione di pagamento,
copia per il cliente in dollari, e costruzione del modello per il motore FatturaPA.
"""
import calendar
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import config_studio as C
import db_studio as db
from fatturapa_core import riepilogo as riepilogo_core

ZERO = Decimal("0")
CENT = Decimal("0.01")
UNO = Decimal("1")


def q2(x):
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def numero_testo(s):
    """'1.050,00' / '1050,5' / '1050.50' / '1.050' -> Decimal (senza arrotondare); vuoto -> None."""
    s = str(s or "").strip().replace("€", "").replace("$", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        raise ValueError(f"numero non valido: {s!r}")
    return Decimal(s)


def importo(s):
    v = numero_testo(s)
    return None if v is None else q2(v)


def formato(x, simbolo="€"):
    s = f"{Decimal(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{simbolo} {s}"


def euro(x):
    return formato(x, "€")


def in_valuta(x, valuta="EUR"):
    return formato(x, "€" if valuta == "EUR" else valuta)


# ---------------------------------------------------------------- numerazione
def numero_xml(doc):
    """Numero del documento come va nell'XML: '23/2026' (con l'anno, come Easyfatt), '5/B/2019'."""
    suff = doc["suffisso"] if "suffisso" in doc.keys() and doc["suffisso"] and doc["tipo"] != "AVV" else ""
    n = f"{doc['numero']}/{suff}" if suff else str(doc["numero"])
    return f"{n}/{doc['anno']}" if C.NUMERO_XML_CON_ANNO else n


def rif_xml(rif):
    """Riferimento alla fattura stornata ('22/2026') -> IdDocumento."""
    rif = (rif or "").strip()
    if not C.NUMERO_XML_CON_ANNO and re.fullmatch(r".+/\d{4}", rif):
        return rif.rsplit("/", 1)[0]
    return rif


# ---------------------------------------------------------------- codici IVA
def codici():
    return {k["codice"]: k for k in db.codici_iva()}


def codice_riga(codice, cli):
    """Codice IVA di una riga: il suo, altrimenti quello del cliente, altrimenti il predefinito."""
    return (codice or "").strip() or ((cli["codice_iva"] or "") if cli else "") or C.CODICE_IVA_PREDEFINITO


def leggi_righe_db(righe_db):
    out = []
    for r in righe_db:
        k = r.keys()
        val = lambda c: importo(r[c]) if c in k and (r[c] or "").strip() else None
        num = lambda c: numero_testo(r[c]) if c in k and (r[c] or "").strip() else None
        out.append({"descrizione": r["descrizione"] or "", "importo": val("importo"),
                    "quantita": num("quantita"), "prezzo": num("prezzo"), "um": (r["um"] or "") if "um" in k else "",
                    "codice_iva": (r["codice_iva"] or "") if "codice_iva" in k else "",
                    "prezzo_valuta": num("prezzo_valuta"), "importo_valuta": val("importo_valuta")})
    return out


def linee(righe, cli, tabella, valuta=None):
    """Righe del documento -> righe del motore FatturaPA. Con valuta='USD' gli importi sono quelli in dollari."""
    out = []
    for r in righe:
        imp = r["importo_valuta"] if valuta else r["importo"]
        if r["importo"] is None:
            out.append({"descr": r["descrizione"], "descrittiva": True})
            continue
        cod = codice_riga(r["codice_iva"], cli)
        k = tabella.get(cod)
        if not k:
            raise ValueError(f"il codice IVA {cod} non esiste (voce «{r['descrizione'][:40]}»)")
        if valuta and imp is None:
            raise ValueError(f"manca il prezzo in {valuta} nella voce «{r['descrizione'][:40]}»")
        prezzo = r["prezzo_valuta"] if valuta else r["prezzo"]
        con_qta = r["quantita"] is not None and prezzo is not None
        out.append({"descr": r["descrizione"] or "-", "qta": r["quantita"] if con_qta else UNO,
                    "um": r["um"] if con_qta else "", "prezzo": prezzo if con_qta else imp, "totale": imp,
                    "aliquota": Decimal(k["aliquota"]), "natura": k["natura"] or None,
                    "rif_norm": k["rif_norm"] or "", "codice": cod, "descrittiva": False})
    prima = next((l for l in out if not l.get("descrittiva")), None)
    for l in out:
        if l.get("descrittiva"):
            base = prima or {"aliquota": ZERO, "natura": None, "rif_norm": "", "codice": ""}
            l.update(qta=None, um="", prezzo=ZERO, totale=ZERO, aliquota=base["aliquota"], natura=base["natura"],
                     rif_norm=base["rif_norm"], codice=base["codice"])
    return out


def nature_bollo(tabella):
    return sorted({k["natura"] for k in tabella.values() if k["bollo"] and k["natura"]})


def bollo_attivo():
    return db.impostazione("bollo_virtuale", "0") == "1"


def totali(ls, tabella):
    """Riepilogo per aliquota e natura, come nell'XML."""
    riep = riepilogo_core({"righe": [l for l in ls], "cassa": None})
    senza_iva = sum((g["imponibile"] for g in riep["gruppi"] if g["natura"] in nature_bollo(tabella)), ZERO)
    dovuto = bollo_attivo() and senza_iva > Decimal(C.BOLLO["soglia"])
    return {"imponibile": riep["imponibile"], "iva": riep["imposta"], "totale": riep["totale"],
            "netto": riep["totale"], "gruppi": riep["gruppi"], "bollo_dovuto": dovuto}


# ---------------------------------------------------------------- pagamento
def nome_pagamento(doc, cli):
    k = doc.keys() if hasattr(doc, "keys") else doc
    return ((doc["pagamento"] if "pagamento" in k else "") or ((cli["pagamento"] or "") if cli else "")
            or C.PAGAMENTO_PREDEFINITO)


def fine_mese(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def scadenze(data_iso, pag, totale):
    """[(data ISO, importo)]: una per rata, importi uguali (l'ultima prende i centesimi di resto)."""
    d0 = date.fromisoformat(data_iso)
    giorni = [int(g) for g in (pag["giorni"] if pag else "0").split(",") if g.strip().isdigit()] or [0]
    rata = q2(Decimal(totale) / len(giorni))
    out = []
    for i, g in enumerate(giorni):
        d = d0 + timedelta(days=g)
        if pag and pag["fine_mese"]:
            d = fine_mese(d)
        imp = rata if i < len(giorni) - 1 else Decimal(totale) - rata * (len(giorni) - 1)
        out.append((d.isoformat(), imp))
    return out


def banca_documento(doc, valuta="EUR"):
    k = doc.keys() if hasattr(doc, "keys") else doc
    b = db.banca(doc["banca_id"]) if "banca_id" in k and doc["banca_id"] else None
    if not b and valuta_doc(doc):
        valuta = valuta_doc(doc)                # fattura con copia in dollari: si incassa sul conto in dollari
    if valuta != "EUR" or not b:
        b = (b if b and b["valuta"] == valuta else None) or db.banca_predefinita(valuta)
    return b


def valuta_doc(doc):
    k = doc.keys() if hasattr(doc, "keys") else doc
    return (doc["valuta"] if "valuta" in k else "") or ""


# ---------------------------------------------------------------- modello per il motore FatturaPA
def modello_fattura(doc, righe_db, cli, studio, progressivo, valuta=None):
    """Documento -> (dizionario per fatturapa_core.costruisci_xml, totali).
    valuta='USD': la copia per il cliente in dollari (stesso documento, importi in USD, banca in USD)."""
    tabella = codici()
    righe = leggi_righe_db(righe_db)
    ls = linee(righe, cli, tabella, valuta)
    if not any(not l.get("descrittiva") for l in ls):
        raise ValueError("il documento non ha voci con importo")
    tot = totali(ls, tabella)
    nazione = (cli["nazione"] or "IT").upper()
    pag = db.pagamento(nome=nome_pagamento(doc, cli))
    banca = banca_documento(doc, valuta or "EUR")
    rate = scadenze(doc["data"], pag, tot["totale"]) if doc["tipo"] != "TD04" else []
    causale = doc["note"] or ""
    f = {
        "trasmittente": studio["cf"], "progressivo": progressivo,
        "cedente": {"piva": studio["piva"], "cf": studio["cf"], "denominazione": studio["denominazione"],
                    "regime_fiscale": studio["regime_fiscale"], "indirizzo": studio["indirizzo"],
                    "cap": studio["cap"], "comune": studio["comune"], "provincia": studio["provincia"],
                    "rea_ufficio": studio.get("rea_ufficio", ""), "rea_numero": studio.get("rea_numero", ""),
                    "email": studio["email"]},
        "cliente": {"nazione": nazione, "piva": cli["piva"] or "", "cf": cli["cf"] or "",
                    "id_estero": (cli["id_estero"] or cli["piva"] or "") if nazione != "IT" else "",
                    "denominazione": cli["denominazione"], "indirizzo": cli["indirizzo"] or "",
                    "cap": cli["cap"] or "", "comune": cli["comune"] or "", "provincia": cli["provincia"] or "",
                    "codice_destinatario": (cli["codice_destinatario"] or "") if nazione == "IT" else "",
                    "pec": (cli["pec"] or "") if nazione == "IT" else ""},
        "tipo": doc["tipo"], "data": doc["data"], "numero": numero_xml(doc),
        "causale": causale,
        "righe": ls,
        "cassa": None, "ritenuta": None,
        "bollo": {"attivo": bollo_attivo(), "soglia": C.BOLLO["soglia"], "importo": C.BOLLO["importo"],
                  "nature_soggette": nature_bollo(tabella)},
        "intento": ((cli["intento_protocollo"] or ""), (cli["intento_data"] or "")) if cli["intento_protocollo"] else None,
        "fatture_collegate": [(rif_xml(doc["rif_numero"]), doc["rif_data"] or "")] if doc["tipo"] == "TD04" else [],
        "pagamenti": [{"modalita": pag["modalita"] if pag else C.PAGAMENTO["modalita"], "scadenza": d,
                       "importo": imp, "istituto": banca["nome"] if banca else "",
                       "iban": banca["iban"] if banca else ""} for d, imp in rate],
    }
    tot.update(scadenze=rate, pagamento=pag, banca=banca, valuta=valuta or "EUR", codici=tabella)
    return f, tot
