"""
Motore FatturaPA 1.2.3 (FPR12) indipendente dalla sorgente dei dati.

Gli adattatori (export Easyfatt, Excel di inserimento, ...) preparano un dizionario
'fattura' con la struttura descritta in costruisci_xml() e il motore produce l'XML,
lo valida contro lo schema ufficiale e calcola riepiloghi e totali.
"""
import base64
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from lxml import etree

from testo_ricco import piano

BASE = Path(__file__).resolve().parent
XSD = BASE / "xsd" / "Schema_del_file_xml_FatturaPA_v1.2.3.xsd"
NS = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
ZERO = Decimal("0")

PAESI = {
    "italia": "IT", "arabia saudita": "SA", "stati uniti": "US", "svizzera": "CH",
    "regno unito": "GB", "germania": "DE", "francia": "FR", "spagna": "ES",
    "austria": "AT", "belgio": "BE", "paesi bassi": "NL", "olanda": "NL",
    "emirati arabi uniti": "AE", "qatar": "QA", "kuwait": "KW", "bahrein": "BH",
    "oman": "OM", "egitto": "EG", "turchia": "TR", "san marino": "SM",
    "cina": "CN", "india": "IN", "giappone": "JP", "canada": "CA", "brasile": "BR",
}


class Errore(Exception):
    pass


# ---------------------------------------------------------------- utilita'
def D(s, default="0"):
    if isinstance(s, Decimal):
        return s
    if isinstance(s, (int, float)):
        return Decimal(str(s))
    s = (s or "").strip()
    return Decimal(s) if s else Decimal(default)


def q2(x):
    return Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP)


def f2(x):
    return str(q2(x))


def f_qta(x):
    s = format(Decimal(x).normalize(), "f")
    if "." not in s:
        s += ".00"
    intero, dec = s.split(".")
    return f"{intero}.{dec.ljust(2, '0')[:8]}"


def latin1(s, maxlen):
    """Lo schema accetta solo Basic Latin + Latin-1: sostituisce il resto."""
    s = str(s or "")
    sost = {"’": "'", "‘": "'", "“": '"', "”": '"',
            "–": "-", "—": "-", "€": "EUR", "…": "..."}
    out = "".join(sost.get(c, c) if ord(c) > 255 else c for c in s)
    out = "".join(c if ord(c) <= 255 else "?" for c in out)
    out = re.sub(r"[ \t]{2,}", " ", out.replace("\r\n", "\n")).strip()
    return out[:maxlen]


def codice_paese(nome):
    nome = (nome or "").strip()
    if not nome:
        return "IT"
    if len(nome) == 2 and nome.isalpha():
        return nome.upper()
    cod = PAESI.get(nome.lower())
    if not cod:
        raise Errore(f"Paese {nome!r} non in tabella PAESI: usa il codice ISO a 2 lettere")
    return cod


def sub(parent, tag, text=None):
    el = etree.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


_schema = None


def valida(tree):
    global _schema
    if _schema is None:
        parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
        _schema = etree.XMLSchema(etree.parse(str(XSD), parser))
    if not _schema.validate(tree):
        raise Errore("XML non valido rispetto allo schema:\n  " +
                     "\n  ".join(f"riga {e.line}: {e.message}" for e in _schema.error_log))


# ---------------------------------------------------------------- calcoli
def riepilogo(fattura):
    """Raggruppa per aliquota/natura (il contributo cassa entra nell'imponibile del
    suo gruppo) e calcola imposta e totali. Usato sia per l'XML sia per il PDF."""
    voci = [(r["aliquota"], r["natura"], r["rif_norm"], r["totale"]) for r in fattura["righe"]]
    cs = fattura.get("cassa")
    if cs:
        voci.append((cs["aliquota"], cs["natura"], cs["rif_norm"], cs["importo"]))
    gruppi = {}
    for al, nat, rif, imp in voci:
        # un riepilogo per aliquota, natura e riferimento normativo (come Easyfatt: le anticipazioni
        # "Fuori campo IVA" restano separate dagli onorari del forfettario, pur con la stessa natura)
        g = gruppi.setdefault((al, nat, rif), {"aliquota": al, "natura": nat, "rif_norm": rif,
                                               "imponibile": ZERO})
        g["imponibile"] += imp
    for g in gruppi.values():
        g["imposta"] = q2(g["imponibile"] * g["aliquota"] / 100)
    righe = sorted(gruppi.values(), key=lambda g: (-g["aliquota"], g["natura"] or "", g["rif_norm"] or ""))
    imponibile = sum(g["imponibile"] for g in righe)
    imposta = sum(g["imposta"] for g in righe)
    return {"gruppi": righe, "imponibile": imponibile, "imposta": imposta,
            "totale": imponibile + imposta}


def bollo_dovuto(fattura, riep):
    b = fattura.get("bollo") or {}
    if not b.get("attivo"):
        return False
    senza_iva = sum(g["imponibile"] for g in riep["gruppi"]
                    if g["natura"] in b.get("nature_soggette", []))
    return senza_iva > D(b["soglia"])


# ---------------------------------------------------------------- XML
def costruisci_xml(f):
    """
    f = {
      "trasmittente": "codice fiscale di chi trasmette", "progressivo": "00001",
      "cedente": {"piva", "cf", "denominazione" | "nome"+"cognome"(+"titolo"),
                  "regime_fiscale", "indirizzo", "cap", "comune", "provincia",
                  facoltativi "albo", "provincia_albo", "numero_albo", "data_albo"},
      "cliente": {"nazione" (ISO), "piva", "cf", "id_estero", "denominazione",
                  "indirizzo", "cap", "comune", "provincia", "codice_destinatario", "pec"},
      "tipo": "TD01" (fattura) | "TD04" (nota di credito), "data": "AAAA-MM-GG", "numero": "23/2026",
      "causale": "", "fatture_collegate": [("22/2026", "AAAA-MM-GG")]  (per TD04),
      "righe": [{"descr", "qta" (o None), "um", "prezzo", "totale", "aliquota" (Decimal),
                 "natura" (o None), "rif_norm", "descrittiva" (bool)}],
      "cassa": None | {"tipo", "perc", "importo", "base", "aliquota", "natura", "rif_norm", "ritenuta" (bool)},
      "ritenuta": None | {"tipo": "RT01", "aliquota", "importo", "causale": "A"}  (righe con "ritenuta": True),
      "bollo": {"attivo", "soglia", "importo", "nature_soggette"},
      "intento": None | ("protocollo", "AAAA-MM-GG"),
      "pagamenti": [{"modalita": "MP05", "scadenza", "importo", "istituto", "iban"}],
    }
    Restituisce (albero XML, riepilogo, avvisi).
    """
    avvisi = []
    ced, cli = f["cedente"], f["cliente"]
    riep = riepilogo(f)

    root = etree.Element(f"{{{NS}}}FatturaElettronica", nsmap={"p": NS, "ds": NS_DS, "xsi": NS_XSI})
    root.set("versione", "FPR12")
    root.set(f"{{{NS_XSI}}}schemaLocation", f"{NS} {XSD.name}")

    # ---------- HEADER
    h = sub(root, "FatturaElettronicaHeader")
    dt = sub(h, "DatiTrasmissione")
    idt = sub(dt, "IdTrasmittente")
    sub(idt, "IdPaese", "IT")
    sub(idt, "IdCodice", f["trasmittente"])
    sub(dt, "ProgressivoInvio", f["progressivo"])
    sub(dt, "FormatoTrasmissione", "FPR12")
    paese = cli.get("nazione") or "IT"
    cod_dest = cli.get("codice_destinatario") or ("0000000" if paese == "IT" else "XXXXXXX")
    sub(dt, "CodiceDestinatario", cod_dest)
    if cod_dest == "0000000" and cli.get("pec"):
        sub(dt, "PECDestinatario", cli["pec"])

    cp = sub(h, "CedentePrestatore")
    da = sub(cp, "DatiAnagrafici")
    iva = sub(da, "IdFiscaleIVA")
    sub(iva, "IdPaese", "IT")
    sub(iva, "IdCodice", ced["piva"])
    if ced.get("cf"):
        sub(da, "CodiceFiscale", ced["cf"])
    an = sub(da, "Anagrafica")
    if ced.get("cognome"):
        sub(an, "Nome", latin1(ced["nome"], 60))
        sub(an, "Cognome", latin1(ced["cognome"], 60))
        if ced.get("titolo"):
            sub(an, "Titolo", ced["titolo"])
    else:
        sub(an, "Denominazione", latin1(ced["denominazione"], 80))
    for k_cfg, k_xml in (("albo", "AlboProfessionale"), ("provincia_albo", "ProvinciaAlbo"),
                         ("numero_albo", "NumeroIscrizioneAlbo"), ("data_albo", "DataIscrizioneAlbo")):
        if ced.get(k_cfg):
            sub(da, k_xml, ced[k_cfg])
    sub(da, "RegimeFiscale", ced["regime_fiscale"])
    sede = sub(cp, "Sede")
    sub(sede, "Indirizzo", latin1(ced["indirizzo"], 60))
    sub(sede, "CAP", ced["cap"])
    sub(sede, "Comune", latin1(ced["comune"], 60))
    sub(sede, "Provincia", ced["provincia"])
    sub(sede, "Nazione", "IT")
    if ced.get("rea_ufficio") and ced.get("rea_numero"):
        rea = sub(cp, "IscrizioneREA")
        sub(rea, "Ufficio", ced["rea_ufficio"])
        sub(rea, "NumeroREA", ced["rea_numero"])
        sub(rea, "StatoLiquidazione", "LN")
    if ced.get("email"):
        sub(sub(cp, "Contatti"), "Email", ced["email"])

    cc = sub(h, "CessionarioCommittente")
    da = sub(cc, "DatiAnagrafici")
    if paese == "IT":
        if cli.get("piva"):
            iva = sub(da, "IdFiscaleIVA")
            sub(iva, "IdPaese", "IT")
            sub(iva, "IdCodice", cli["piva"])
        if cli.get("cf"):
            sub(da, "CodiceFiscale", cli["cf"].upper())
        if not cli.get("piva") and not cli.get("cf"):
            raise Errore("Cliente italiano senza partita IVA ne' codice fiscale")
    else:
        id_estero = re.sub(r"\s", "", cli.get("id_estero") or cli.get("piva") or "") or "OO99999999999"
        if id_estero == "OO99999999999":
            avvisi.append("cliente estero senza identificativo fiscale: usato OO99999999999 "
                          "(meglio inserire il VAT number)")
        iva = sub(da, "IdFiscaleIVA")
        sub(iva, "IdPaese", paese)
        sub(iva, "IdCodice", id_estero[:28])
    sub(sub(da, "Anagrafica"), "Denominazione", latin1(cli["denominazione"], 80))
    sede = sub(cc, "Sede")
    sub(sede, "Indirizzo", latin1(cli["indirizzo"], 60))
    cap = re.sub(r"\s", "", cli.get("cap") or "")
    sub(sede, "CAP", cap if paese == "IT" or re.fullmatch(r"\d{5}", cap) else "00000")
    sub(sede, "Comune", latin1(cli["comune"], 60))
    if paese == "IT" and cli.get("provincia"):
        sub(sede, "Provincia", cli["provincia"])
    sub(sede, "Nazione", paese)

    # ---------- BODY
    b = sub(root, "FatturaElettronicaBody")
    dg = sub(b, "DatiGenerali")
    dgd = sub(dg, "DatiGeneraliDocumento")
    sub(dgd, "TipoDocumento", f.get("tipo", "TD01"))
    sub(dgd, "Divisa", "EUR")
    sub(dgd, "Data", f["data"])
    sub(dgd, "Numero", f["numero"])
    rit = f.get("ritenuta")
    if rit and D(rit["importo"]) > 0:
        dr = sub(dgd, "DatiRitenuta")
        sub(dr, "TipoRitenuta", rit["tipo"])                  # RT01 persone fisiche
        sub(dr, "ImportoRitenuta", f2(rit["importo"]))
        sub(dr, "AliquotaRitenuta", f2(D(rit["aliquota"])))
        sub(dr, "CausalePagamento", rit.get("causale", "A"))  # A = lavoro autonomo
    if bollo_dovuto(f, riep):
        bo = sub(dgd, "DatiBollo")
        sub(bo, "BolloVirtuale", "SI")
        sub(bo, "ImportoBollo", f2(D(f["bollo"]["importo"])))
    cs = f.get("cassa")
    if cs:
        dc = sub(dgd, "DatiCassaPrevidenziale")
        sub(dc, "TipoCassa", cs["tipo"])
        sub(dc, "AlCassa", f2(cs["perc"]))
        sub(dc, "ImportoContributoCassa", f2(cs["importo"]))
        sub(dc, "ImponibileCassa", f2(cs["base"]))
        sub(dc, "AliquotaIVA", f2(cs["aliquota"]))
        if cs.get("ritenuta"):
            sub(dc, "Ritenuta", "SI")
        if cs["natura"]:
            sub(dc, "Natura", cs["natura"])
    sub(dgd, "ImportoTotaleDocumento", f2(riep["totale"]))
    causale = latin1(piano(f.get("causale", "")), 1000)        # ** e punti elenco: solo nel PDF
    for i in range(0, len(causale), 200):
        sub(dgd, "Causale", causale[i:i + 200])
    # nota di credito (TD04): riferimento alla fattura stornata
    for id_doc, data_doc in f.get("fatture_collegate") or []:
        fc = sub(dg, "DatiFattureCollegate")
        sub(fc, "IdDocumento", latin1(id_doc, 20))
        if data_doc:
            sub(fc, "Data", data_doc)

    dbs = sub(b, "DatiBeniServizi")
    intento_messo = False
    for n, r in enumerate(f["righe"], 1):
        dl = sub(dbs, "DettaglioLinee")
        sub(dl, "NumeroLinea", n)
        if r.get("tipo_cessione"):                      # es. AC = spesa accessoria (anticipazioni)
            sub(dl, "TipoCessionePrestazione", r["tipo_cessione"])
        sub(dl, "Descrizione", latin1(piano(r["descr"]), 1000) or "-")
        if r.get("qta") is not None and not r.get("descrittiva"):
            sub(dl, "Quantita", f_qta(r["qta"]))
            if r.get("um"):
                sub(dl, "UnitaMisura", latin1(r["um"], 10))
        sub(dl, "PrezzoUnitario", f2(r["prezzo"]))
        sub(dl, "PrezzoTotale", f2(r["totale"]))
        sub(dl, "AliquotaIVA", f2(r["aliquota"]))
        if r.get("ritenuta") and not r.get("descrittiva"):
            sub(dl, "Ritenuta", "SI")
        if r["natura"]:
            sub(dl, "Natura", r["natura"])
        if r["natura"] == "N3.5" and not intento_messo and not r.get("descrittiva"):
            prot, data = f.get("intento") or ("", "")
            if re.fullmatch(r"\d{17}-\d{6}", prot or "") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data or ""):
                adg = sub(dl, "AltriDatiGestionali")
                sub(adg, "TipoDato", "INTENTO")
                sub(adg, "RiferimentoTesto", prot)
                sub(adg, "RiferimentoData", data)
                intento_messo = True
            else:
                avvisi.append("N3.5 senza dati della dichiarazione d'intento (protocollo e data): "
                              "inseriscili PRIMA dell'invio")

    for g in riep["gruppi"]:
        dr = sub(dbs, "DatiRiepilogo")
        sub(dr, "AliquotaIVA", f2(g["aliquota"]))
        if g["natura"]:
            sub(dr, "Natura", g["natura"])
        sub(dr, "ImponibileImporto", f2(g["imponibile"]))
        sub(dr, "Imposta", f2(g["imposta"]))
        if g["natura"]:
            sub(dr, "RiferimentoNormativo", latin1(g["rif_norm"], 100))
        else:
            sub(dr, "EsigibilitaIVA", "I")

    pag = f.get("pagamenti") or []
    if pag:
        dp = sub(b, "DatiPagamento")
        sub(dp, "CondizioniPagamento", "TP02" if len(pag) == 1 else "TP01")
        for p in pag:
            det = sub(dp, "DettaglioPagamento")
            sub(det, "ModalitaPagamento", p.get("modalita", "MP05"))
            if p.get("scadenza"):
                sub(det, "DataScadenzaPagamento", p["scadenza"])
            sub(det, "ImportoPagamento", f2(p["importo"]))
            if p.get("istituto"):
                sub(det, "IstitutoFinanziario", latin1(p["istituto"], 80))
            if p.get("iban"):
                sub(det, "IBAN", re.sub(r"\s", "", p["iban"]))

    for a in f.get("allegati") or []:
        al = sub(b, "Allegati")
        sub(al, "NomeAttachment", a["nome"][:60])
        sub(al, "FormatoAttachment", a.get("formato", "PDF"))
        sub(al, "DescrizioneAttachment", a.get("descrizione", "Copia di cortesia")[:100])
        sub(al, "Attachment", base64.b64encode(a["dati"]).decode("ascii"))

    tree = etree.ElementTree(root)
    valida(tree)
    return tree, riep, list(dict.fromkeys(avvisi))


def nome_file(f):
    return f"IT{f['trasmittente']}_{f['progressivo']}.xml"
