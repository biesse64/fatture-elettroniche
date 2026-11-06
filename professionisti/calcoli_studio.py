"""
Calcoli dello studio: onorari, bollo, contributo Cassa Forense, anticipazioni, totale,
calcolo all'indietro dal totale, e costruzione del modello fattura per il motore FatturaPA.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

import config_studio as C

ZERO = Decimal("0")
CENT = Decimal("0.01")


def q2(x):
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def importo(s):
    """'1.050,00' / '1050,5' / '1050.50' / '1.050' -> Decimal; vuoto -> None; non valido -> ValueError."""
    s = str(s or "").strip().replace("€", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        raise ValueError(f"importo non valido: {s!r}")
    return q2(Decimal(s))


def euro(x):
    s = f"{Decimal(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {s}"


# Regole della posizione fiscale (config_studio): forfettario (avvocata) oppure ordinario con IVA
# e ritenuta d'acconto (es. ingegnere). I valori mancanti nel config valgono "come il forfettario".
ALIQ_CASSA = Decimal(C.CASSA["aliquota_perc"]) / 100 if C.CASSA else ZERO
ALIQ_IVA = Decimal(getattr(C, "IVA_PERC", "0")) / 100
NATURA_RIGHE = getattr(C, "NATURA_RIGHE", getattr(C, "NATURA_FORFETTARIO", None))
RIF_RIGHE = getattr(C, "RIF_RIGHE", getattr(C, "RIF_FORFETTARIO", ""))
RITENUTA = getattr(C, "RITENUTA", None)          # {"tipo": "RT01", "aliquota_perc": "20", "causale": "A"}
ALIQ_RIT = Decimal(RITENUTA["aliquota_perc"]) / 100 if RITENUTA else ZERO
BOLLO = Decimal(C.BOLLO["importo"]) if C.BOLLO else ZERO
SOGLIA_BOLLO = Decimal(C.BOLLO["soglia"]) if C.BOLLO else ZERO


def totali(righe, addebita_bollo=True, con_ritenuta=True):
    """righe: dict con tipo ('onorario'|'anticipazione'|'vendita') e importo (Decimal o None).
    vendita = beni o software venduti: IVA si', ma niente contributo cassa e niente ritenuta.
    con_ritenuta=False: cliente che non e' sostituto d'imposta (es. un privato)."""
    somma = lambda tipo: sum((r["importo"] for r in righe if r["tipo"] == tipo and r["importo"] is not None), ZERO)
    onorari, anticip, vendite = somma("onorario"), somma("anticipazione"), somma("vendita")
    # bollo (solo senza IVA): dovuto quando l'importo supera la soglia, prima del bollo stesso
    dovuto = bool(C.BOLLO) and ALIQ_IVA == 0 and q2(onorari * (1 + ALIQ_CASSA)) + anticip > SOGLIA_BOLLO
    bollo = BOLLO if (dovuto and addebita_bollo) else ZERO
    base_cassa = onorari + (bollo if C.BOLLO and C.BOLLO["soggetto_cassa"] else ZERO)
    cassa = q2(base_cassa * ALIQ_CASSA)
    imponibile = onorari + bollo + cassa + vendite
    iva = q2(imponibile * ALIQ_IVA)
    totale = imponibile + iva + anticip
    # sugli onorari: esclusi contributo cassa, IVA, anticipazioni e vendite
    ritenuta = q2(onorari * ALIQ_RIT) if con_ritenuta else ZERO
    return {"onorari": onorari, "bollo": bollo, "bollo_dovuto": dovuto, "base_cassa": base_cassa,
            "cassa": cassa, "anticipazioni": anticip, "vendite": vendite, "imponibile": imponibile, "iva": iva,
            "totale": totale, "ritenuta": ritenuta, "netto": totale - ritenuta}


def scorporo(totale_voluto, righe, addebita_bollo=True, campo="totale", con_ritenuta=True):
    """Calcolo all'indietro: l'importo della PRIMA riga di onorario tale che il totale del
    documento (o il netto a pagare, campo="netto") sia esattamente quello voluto, a parita'
    delle altre righe. Restituisce (importo, valore_ottenuto)."""
    righe = [dict(r) for r in righe]
    idx = next((i for i, r in enumerate(righe) if r["tipo"] == "onorario"), None)
    if idx is None:
        righe.insert(0, {"tipo": "onorario", "importo": ZERO})
        idx = 0
    t = Decimal(totale_voluto)

    def valore(x):
        righe[idx]["importo"] = x
        return totali(righe, addebita_bollo, con_ritenuta)[campo]

    pendenza = (valore(Decimal(2000)) - valore(Decimal(1000))) / 1000
    x = Decimal(1000)
    for _ in range(3):                          # pochi passi: il calcolo e' lineare a tratti (bollo)
        x = q2(x + (t - valore(x)) / pendenza)
    migliore = None
    for d in range(-5, 6):
        prova = x + CENT * d
        ottenuto = valore(prova)
        scarto = abs(ottenuto - t)
        if migliore is None or scarto < migliore[2]:
            migliore = (prova, ottenuto, scarto)
        if scarto == 0:
            break
    return migliore[0], migliore[1]


def leggi_righe_db(righe_db):
    out = []
    for r in righe_db:
        k = r.keys()
        val = lambda c: importo(r[c]) if c in k and (r[c] or "").strip() else None
        out.append({"tipo": r["tipo"], "descrizione": r["descrizione"] or "", "importo": val("importo"),
                    "quantita": val("quantita"), "prezzo": val("prezzo"),
                    "um": (r["um"] or "") if "um" in k else ""})
    return out


def applica_ritenuta(doc):
    """La ritenuta si applica se la posizione la prevede e il documento non la esclude (cliente privato)."""
    k = doc.keys() if hasattr(doc, "keys") else doc
    return bool(RITENUTA) and ("ritenuta" not in k or doc["ritenuta"] is None or bool(int(doc["ritenuta"])))


def numero_xml(doc):
    """Numero del documento come va nell'XML: '59', '66/A' (o '59/2026' se configurato con l'anno)."""
    suff = doc["suffisso"] if "suffisso" in doc.keys() and doc["suffisso"] and doc["tipo"] != "AVV" else ""
    n = f"{doc['numero']}/{suff}" if suff else str(doc["numero"])
    return f"{n}/{doc['anno']}" if C.NUMERO_XML_CON_ANNO else n


def rif_xml(rif):
    """Riferimento alla fattura stornata ('59/2026', '66/A/2026') -> IdDocumento ('59', '66/A')."""
    rif = (rif or "").strip()
    if not C.NUMERO_XML_CON_ANNO and re.fullmatch(r".+/\d{4}", rif):
        return rif.rsplit("/", 1)[0]
    return rif


def modello_fattura(doc, righe_db, cli, studio, progressivo):
    """Documento dell'archivio -> dizionario per fatturapa_core.costruisci_xml."""
    righe = leggi_righe_db(righe_db)
    con_rit = applica_ritenuta(doc)
    tot = totali(righe, bool(doc["bollo"]), con_rit)
    linee = []
    for r in righe:
        if r["importo"] is None:
            linee.append({"descr": r["descrizione"], "descrittiva": True})
            continue
        anticip = r["tipo"] == "anticipazione"
        con_qta = r["quantita"] is not None and r["prezzo"] is not None
        linee.append({"descr": r["descrizione"] or "-", "qta": r["quantita"] if con_qta else Decimal("1"),
                      "um": r["um"] if con_qta else "", "prezzo": r["prezzo"] if con_qta else r["importo"],
                      "totale": r["importo"],
                      "aliquota": ZERO if anticip else ALIQ_IVA * 100,
                      "natura": C.ANTICIPAZIONI["natura"] if anticip else NATURA_RIGHE,
                      "rif_norm": C.ANTICIPAZIONI["rif_norm"] if anticip else RIF_RIGHE,
                      "descrittiva": False, "tipo": r["tipo"],
                      "ritenuta": bool(RITENUTA) and con_rit and r["tipo"] == "onorario",
                      "tipo_cessione": "AC" if anticip else ""})
    if tot["bollo"]:
        linee.append({"descr": C.BOLLO["descrizione"], "qta": Decimal("1"), "um": "", "prezzo": tot["bollo"],
                      "totale": tot["bollo"], "aliquota": ZERO, "natura": NATURA_RIGHE,
                      "rif_norm": RIF_RIGHE, "descrittiva": False, "tipo": "bollo"})
    prima = next((l for l in linee if not l.get("descrittiva")), None)
    if prima is None:
        raise ValueError("Il documento non ha righe con importo.")
    for l in linee:
        if l.get("descrittiva"):
            l.update(qta=None, um="", prezzo=ZERO, totale=ZERO, aliquota=ZERO, natura=prima["natura"],
                     rif_norm=prima["rif_norm"], tipo="descrittiva")

    causale = []
    if doc["terzo_pagatore"]:
        causale.append(C.TESTO_TERZO.format(terzo=doc["terzo_pagatore"]))
    if doc["note"]:
        causale.append(doc["note"])

    nazione = (cli["nazione"] or "IT").upper()
    f = {
        "trasmittente": studio["cf"], "progressivo": progressivo,
        "cedente": {"piva": studio["piva"], "cf": studio["cf"], "nome": studio["nome"],
                    "cognome": studio["cognome"], "titolo": studio["titolo"],
                    "albo": studio["albo"], "provincia_albo": studio["provincia_albo"],
                    "numero_albo": studio["numero_albo"], "data_albo": studio["data_albo"],
                    "regime_fiscale": studio["regime_fiscale"], "indirizzo": studio["indirizzo"],
                    "cap": studio["cap"], "comune": studio["comune"], "provincia": studio["provincia"],
                    "email": studio["email"]},
        "cliente": {"nazione": nazione, "piva": cli["piva"] or "", "cf": cli["cf"] or "",
                    "id_estero": cli["piva"] if nazione != "IT" else "",
                    "denominazione": cli["denominazione"], "indirizzo": cli["indirizzo"] or "",
                    "cap": cli["cap"] or "", "comune": cli["comune"] or "", "provincia": cli["provincia"] or "",
                    "codice_destinatario": cli["codice_destinatario"] or "", "pec": cli["pec"] or ""},
        "tipo": doc["tipo"], "data": doc["data"], "numero": numero_xml(doc),
        "causale": "\n".join(causale),       # a capo: le note possono avere un elenco
        "righe": linee,
        "cassa": {"tipo": C.CASSA["tipo"], "perc": Decimal(C.CASSA["aliquota_perc"]), "importo": tot["cassa"],
                  "base": tot["base_cassa"], "aliquota": ALIQ_IVA * 100, "natura": NATURA_RIGHE,
                  "rif_norm": RIF_RIGHE, "ritenuta": False} if tot["cassa"] else None,
        "bollo": {"attivo": bool(C.BOLLO), "soglia": C.BOLLO["soglia"] if C.BOLLO else "0",
                  "importo": C.BOLLO["importo"] if C.BOLLO else "0",
                  "nature_soggette": sorted({n for n in (NATURA_RIGHE, C.ANTICIPAZIONI["natura"]) if n})},
        "ritenuta": {"tipo": RITENUTA["tipo"], "aliquota": RITENUTA["aliquota_perc"], "importo": tot["ritenuta"],
                     "causale": RITENUTA.get("causale", "A")} if RITENUTA and tot["ritenuta"] else None,
        "intento": None,
        "fatture_collegate": [(rif_xml(doc["rif_numero"]), doc["rif_data"] or "")] if doc["tipo"] == "TD04" else [],
        "pagamenti": [] if doc["tipo"] == "TD04" else [{
            "modalita": C.PAGAMENTO["modalita"], "scadenza": doc["data"], "importo": tot["netto"],
            "istituto": studio["banca"], "iban": studio["iban"]}],
    }
    return f, tot


# ---------------------------------------------------------------- fatture del programma precedente
def modello_da_xml(percorso):
    """Fattura gia' emessa da un altro programma -> (modello, totali) letti dal file FatturaPA originale,
    senza ricalcolare: la copia PDF riporta esattamente importi, IVA, cassa e ritenuta inviati allo SDI."""
    from lxml import etree
    x = etree.parse(str(percorso), etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True))
    loc = lambda tag: f"*[local-name()='{tag}']"
    tutti = lambda el, *tags: el.xpath("./" + "/".join(loc(t) for t in tags))
    uno = lambda el, *tags: ((tutti(el, *tags) or [None])[0])
    txt = lambda el, *tags: ((uno(el, *tags).text or "").strip() if el is not None and uno(el, *tags) is not None else "")
    num = lambda el, *tags: Decimal(txt(el, *tags) or "0")
    radice = x.getroot()
    testa, corpo = uno(radice, "FatturaElettronicaHeader"), uno(radice, "FatturaElettronicaBody")
    cc = uno(testa, "CessionarioCommittente")
    ana = uno(cc, "DatiAnagrafici")
    nome = txt(ana, "Anagrafica", "Denominazione") or \
        f"{txt(ana, 'Anagrafica', 'Nome')} {txt(ana, 'Anagrafica', 'Cognome')}".strip()
    cliente = {"denominazione": nome, "piva": txt(ana, "IdFiscaleIVA", "IdCodice"), "cf": txt(ana, "CodiceFiscale"),
               "indirizzo": txt(cc, "Sede", "Indirizzo"), "cap": txt(cc, "Sede", "CAP"),
               "comune": txt(cc, "Sede", "Comune"), "provincia": txt(cc, "Sede", "Provincia"),
               "nazione": txt(cc, "Sede", "Nazione") or "IT",
               "codice_destinatario": txt(testa, "DatiTrasmissione", "CodiceDestinatario"),
               "pec": txt(testa, "DatiTrasmissione", "PECDestinatario")}
    dgd = uno(corpo, "DatiGenerali", "DatiGeneraliDocumento")
    righe = []
    for dl in tutti(corpo, "DatiBeniServizi", "DettaglioLinee"):
        tot = num(dl, "PrezzoTotale")
        qta = txt(dl, "Quantita")
        r = {"descr": txt(dl, "Descrizione") or "-", "totale": tot, "aliquota": num(dl, "AliquotaIVA"),
             "natura": txt(dl, "Natura") or None, "rif_norm": txt(dl, "RiferimentoAmministrazione"),
             "qta": Decimal(qta) if qta else Decimal("1"), "um": txt(dl, "UnitaMisura"),
             "prezzo": num(dl, "PrezzoUnitario") if qta else tot, "tipo": "onorario",
             "ritenuta": txt(dl, "Ritenuta") == "SI", "descrittiva": not tot and not qta}
        righe.append(r)
    gruppi = tutti(corpo, "DatiBeniServizi", "DatiRiepilogo")
    for r in righe:                                  # riferimento normativo della natura, dal riepilogo
        if r["natura"]:
            g = next((g for g in gruppi if txt(g, "Natura") == r["natura"]), None)
            r["rif_norm"] = txt(g, "RiferimentoNormativo") if g is not None else ""
    cs = uno(dgd, "DatiCassaPrevidenziale")
    cassa = None if cs is None else {
        "tipo": txt(cs, "TipoCassa"), "perc": num(cs, "AlCassa"), "importo": num(cs, "ImportoContributoCassa"),
        "base": num(cs, "ImponibileCassa"), "aliquota": num(cs, "AliquotaIVA"), "natura": txt(cs, "Natura") or None,
        "rif_norm": "", "ritenuta": txt(cs, "Ritenuta") == "SI"}
    rt = uno(dgd, "DatiRitenuta")
    ritenuta = num(rt, "ImportoRitenuta") if rt is not None else ZERO
    voci = sum((r["totale"] for r in righe), ZERO)
    soggette = sum((r["totale"] for r in righe if r["ritenuta"]), ZERO)
    if rt is not None and soggette:              # voci con Ritenuta SI: sono gli onorari
        onorari = soggette
    elif cassa and cassa["base"]:                # altrimenti la base del contributo, o tutte le voci
        onorari = cassa["base"]
    else:
        onorari = voci
    if cassa and not cassa["base"]:
        cassa["base"] = onorari
    imponibile = sum((num(g, "ImponibileImporto") for g in gruppi), ZERO)
    iva = sum((num(g, "Imposta") for g in gruppi), ZERO)
    totale = num(dgd, "ImportoTotaleDocumento") or imponibile + iva
    bollo = num(dgd, "DatiBollo", "ImportoBollo")
    pagamenti = [{"modalita": txt(p, "ModalitaPagamento"), "scadenza": txt(p, "DataScadenzaPagamento")
                  or txt(dgd, "Data"), "importo": num(p, "ImportoPagamento"),
                  "istituto": txt(p, "IstitutoFinanziario"), "iban": txt(p, "IBAN")}
                 for p in tutti(corpo, "DatiPagamento", "DettaglioPagamento")]
    collegate = [(txt(c, "IdDocumento"), txt(c, "Data")) for c in tutti(corpo, "DatiGenerali", "DatiFattureCollegate")]
    f = {"tipo": txt(dgd, "TipoDocumento"), "numero": txt(dgd, "Numero"), "data": txt(dgd, "Data"),
         "cliente": cliente, "righe": righe, "cassa": cassa, "fatture_collegate": collegate, "pagamenti": pagamenti,
         "causale": " ".join(c.text or "" for c in tutti(dgd, "Causale")).strip()}
    tot = {"onorari": onorari, "vendite": voci - onorari, "anticipazioni": ZERO, "bollo": ZERO,
           "bollo_dovuto": bool(bollo), "base_cassa": cassa["base"] if cassa else ZERO,
           "cassa": cassa["importo"] if cassa else ZERO, "imponibile": imponibile, "iva": iva, "totale": totale,
           "ritenuta": ritenuta, "netto": totale - ritenuta}
    return f, tot

