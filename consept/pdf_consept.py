"""
Copia di cortesia PDF di una fattura Consept, generata dallo stesso modello usato per l'XML
(stessa impaginazione del programma Excel). Con extra["valuta"] = "USD" produce la copia per il
cliente in dollari: stessi numero e voci, importi in USD e coordinate della banca in dollari.
"""
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from reportlab.lib.utils import ImageReader
import testo_ricco

BLU = colors.HexColor("#1F3864")
GRIGIO = colors.HexColor("#F2F2F2")
LINEA = colors.HexColor("#BFBFBF")

st = {
    "n": ParagraphStyle("n", fontName="Helvetica", fontSize=8.5, leading=11),
    "punto": ParagraphStyle("pt", fontName="Helvetica", fontSize=8.5, leading=11, leftIndent=9, bulletIndent=1.5),
    "piccolo": ParagraphStyle("p", fontName="Helvetica", fontSize=7.5, leading=9.5,
                              textColor=colors.HexColor("#404040")),
    "az": ParagraphStyle("az", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=BLU),
    "tit": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=BLU,
                          alignment=TA_RIGHT),
    "dx": ParagraphStyle("dx", fontName="Helvetica", fontSize=8.5, leading=11, alignment=TA_RIGHT),
    "lbl": ParagraphStyle("l", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=BLU),
    "lbldx": ParagraphStyle("ld", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=BLU,
                            alignment=TA_RIGHT),
    "b": ParagraphStyle("b", fontName="Helvetica-Bold", fontSize=8.5, leading=11),
    "bdx": ParagraphStyle("bdx", fontName="Helvetica-Bold", fontSize=10, leading=13, alignment=TA_RIGHT),
}


VALUTA = {"simbolo": "€"}


def euro(x):
    """Importo nella valuta della copia che si sta creando (€ oppure USD)."""
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{VALUTA['simbolo']} {s}"


def euro_vero(x):
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {s}"


def num(x):
    s = format(x.normalize(), "f")
    return s.replace(".", ",")


def data_it(iso):
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def P(t, stile="n"):
    return Paragraph(escape(str(t or "")).replace("\n", "<br/>"), st[stile])


def R(t):
    """Descrizione o nota con **grassetto** ed elenco: una lista di paragrafi (anche dentro una cella)."""
    return testo_ricco.pdf(t, st["n"], st["punto"])


def crea_pdf(percorso, f, riep, extra):
    """extra: tel, email, pec, web, note_pie, bollo (bool), descr_codici {codice: descrizione},
    logo (percorso immagine, facoltativo), bozza (bool: filigrana BOZZA per le anteprime),
    modalita (testo della modalita' di pagamento), banca (riga del conto: nome, iban, bic, dettagli),
    valuta ("EUR" | "USD"), nota_valuta (testo sotto il pagamento nella copia in dollari)."""
    VALUTA["simbolo"] = "€" if extra.get("valuta", "EUR") == "EUR" else extra["valuta"]
    ced, cli = f["cedente"], f["cliente"]
    doc = SimpleDocTemplate(str(percorso), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm,
                            title=f"Fattura {f['numero']}", author=ced.get("denominazione", ""))
    W = A4[0] - 32 * mm
    el = []

    # --- intestazione
    nome = ced.get("denominazione") or f"{ced.get('titolo', '')} {ced['nome']} {ced['cognome']}".strip()
    contatti = " - ".join(x for x in (
        f"Tel. {extra['tel']}" if extra.get("tel") else "",
        extra.get("email", ""), f"PEC {extra['pec']}" if extra.get("pec") else "",
        extra.get("web", "")) if x)
    if extra.get("logo"):
        iw, ih = ImageReader(str(extra["logo"])).getSize()
        h = min(W * ih / iw, 32 * mm)
        el += [Image(str(extra["logo"]), width=h * iw / ih, height=h, hAlign="LEFT"), Spacer(1, 3 * mm)]
    sx = [P(nome, "b" if extra.get("logo") else "az"),
          P(f"{ced['indirizzo']} - {ced['cap']} {ced['comune']} ({ced['provincia']})"),
          P(contatti),
          P(f"P.IVA {ced['piva']}" + (f" - C.F. {ced['cf']}" if ced.get("cf") and ced["cf"] != ced["piva"] else ""))]
    titolo = {"TD04": "NOTA DI CREDITO", "AVV": "AVVISO DI FATTURA"}.get(f.get("tipo"), "FATTURA")
    dx = [P(titolo, "tit"),
          Paragraph(f"n. <b>{escape(f['numero'])}</b> del <b>{data_it(f['data'])}</b>", st["dx"])]
    t = Table([[sx, dx]], colWidths=[W * 0.65, W * 0.35])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, 0), 1.2, BLU),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    el += [t, Spacer(1, 6 * mm)]

    # --- cliente
    loc = f"{cli['cap'] + ' ' if cli.get('cap') else ''}{cli['comune']}"
    if cli.get("provincia"):
        loc += f" ({cli['provincia']})"
    righe_cli = [P("DESTINATARIO", "lbl"), P(cli["denominazione"], "b"), P(cli["indirizzo"]), P(loc)]
    if cli.get("nazione", "IT") != "IT":
        righe_cli.append(P(cli["nazione"]))
    ids = []
    if cli.get("piva"):
        ids.append(f"P.IVA {cli['piva']}")
    if cli.get("cf") and cli.get("cf") != cli.get("piva"):
        ids.append(f"C.F. {cli['cf']}")
    if cli.get("nazione", "IT") != "IT" and cli.get("id_estero"):
        ids.append(f"VAT {cli['id_estero']}")
    if ids:
        righe_cli.append(P(" - ".join(ids)))
    sdi = cli.get("codice_destinatario") or ""
    if sdi and sdi not in ("0000000", "XXXXXXX"):
        righe_cli.append(P(f"Codice destinatario SDI: {sdi}", "piccolo"))
    elif cli.get("pec"):
        righe_cli.append(P(f"PEC: {cli['pec']}", "piccolo"))
    t = Table([[righe_cli, ""]], colWidths=[W * 0.55, W * 0.45])
    t.setStyle(TableStyle([("BOX", (0, 0), (0, 0), 0.6, LINEA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (0, 0), 6), ("TOPPADDING", (0, 0), (0, 0), 5),
                           ("BOTTOMPADDING", (0, 0), (0, 0), 6)]))
    el += [t, Spacer(1, 6 * mm)]

    # --- righe
    dati = [[P("Descrizione", "lbl"), P("Q.ta'", "lbldx"), P("U.M.", "lbl"), P("Prezzo", "lbldx"),
             P("Importo", "lbldx"), P("IVA", "lbl")]]
    for r in f["righe"]:
        if r.get("descrittiva"):
            dati.append([R(r["descr"]), "", "", "", "", ""])
        else:
            dati.append([R(r["descr"]), P(num(r["qta"]) if r.get("qta") is not None else "", "dx"),
                         P(r.get("um", "")), P(euro(r["prezzo"]), "dx"), P(euro(r["totale"]), "dx"),
                         P(r.get("codice", ""))])
    t = Table(dati, colWidths=[W * 0.50, W * 0.08, W * 0.08, W * 0.13, W * 0.13, W * 0.08], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), GRIGIO),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el += [t, Spacer(1, 5 * mm)]

    # --- riepilogo IVA e totali
    codice_di = {}
    for r in f["righe"]:
        codice_di.setdefault((r["aliquota"], r["natura"]), r.get("codice", ""))
    riep_rows = [[P("Riepilogo IVA", "lbl"), P("Imponibile", "lbldx"), P("Imposta", "lbldx")]]
    for g in riep["gruppi"]:
        cod = codice_di.get((g["aliquota"], g["natura"]), "")
        descr = extra["descr_codici"].get(cod) or ""
        testo = f"{cod}: " if cod else ""
        testo += g["rif_norm"] if g["natura"] else (descr or f"IVA {num(g['aliquota'])}%")
        riep_rows.append([P(testo), P(euro(g["imponibile"]), "dx"), P(euro(g["imposta"]), "dx")])
    tr = Table(riep_rows, colWidths=[W * 0.31, W * 0.15, W * 0.12])
    tr.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), GRIGIO),
                            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA),
                            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    tot = Table([[P("Imponibile", "n"), P(euro(riep["imponibile"]), "dx")],
                 [P("IVA", "n"), P(euro(riep["imposta"]), "dx")],
                 [P("TOTALE DOCUMENTO", "b"), Paragraph(euro(riep["totale"]), st["bdx"])]],
                colWidths=[W * 0.22, W * 0.16])
    tot.setStyle(TableStyle([("LINEABOVE", (0, 2), (-1, 2), 1, BLU),
                             ("BACKGROUND", (0, 2), (-1, 2), GRIGIO)]))
    t = Table([[tr, tot]], colWidths=[W * 0.60, W * 0.40])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    el += [KeepTogether(t), Spacer(1, 6 * mm)]

    # --- pagamento e note
    blocco = []
    if f.get("tipo") == "TD04":
        rif = "; ".join(f"n. {i}" + (f" del {data_it(d)}" if d else "") for i, d in f.get("fatture_collegate") or [])
        blocco += [P("RIFERIMENTO", "lbl"),
                   P(f"Nota di credito a storno, totale o parziale, della fattura {rif}." if rif
                     else "Nota di credito."),
                   P(f"Importo a credito del cliente: {euro(riep['totale'])}", "b")]
    if f.get("pagamenti"):
        blocco.append(P("PAGAMENTO", "lbl"))
    modo = extra.get("modalita") or "Bonifico bancario"
    for p in f.get("pagamenti", []):
        riga = f"{modo} - scadenza {data_it(p['scadenza'])}: {euro(p['importo'])}" \
            if p.get("scadenza") else f"{modo}: {euro(p['importo'])}"
        blocco.append(P(riga))
    banca = extra.get("banca")
    if f.get("pagamenti") and banca:
        blocco.append(P(banca["nome"]))
        if banca["iban"]:
            blocco.append(P(f"IBAN {banca['iban']}", "b"))
        if banca["bic"]:
            blocco.append(P(f"BIC/SWIFT {banca['bic']}"))
        if banca["dettagli"]:
            blocco.append(P(banca["dettagli"]))
    elif f.get("pagamenti"):
        p = f["pagamenti"][0]
        if p.get("istituto"):
            blocco.append(P(p["istituto"]))
        if p.get("iban"):
            blocco.append(P(f"IBAN {p['iban']}", "b"))
    if extra.get("nota_valuta"):
        blocco += [Spacer(1, 2 * mm), P(extra["nota_valuta"], "piccolo")]
    note = []
    if f.get("causale"):
        note.extend(R(f["causale"]))
    prot, dt_int = f.get("intento") or (None, None)
    if any(r["natura"] == "N3.5" for r in f["righe"]) and prot and dt_int:
        note.append(P(f"Operazione non imponibile art. 8 c. 1 lett. c DPR 633/72 - dichiarazione "
                      f"d'intento prot. {prot} del {data_it(dt_int)}"))
    if extra.get("bollo"):
        note.append(P("Imposta di bollo assolta in modo virtuale ai sensi dell'art. 6 D.M. 17/06/2014."))
    if extra.get("note_pie"):
        note.append(P(extra["note_pie"]))
    el += [KeepTogether(blocco + [Spacer(1, 4 * mm)] + note)]

    def piede(canvas, d):
        canvas.saveState()
        if extra.get("bozza"):
            canvas.setFont("Helvetica-Bold", 70)
            canvas.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.12))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(40)
            canvas.drawCentredString(0, 0, "BOZZA")
            canvas.setFont("Helvetica-Bold", 16)
            canvas.drawCentredString(0, -30, "anteprima - fattura non ancora generata per lo SDI")
            canvas.restoreState()
            canvas.saveState()
        canvas.setFont("Helvetica", 6.8)
        canvas.setFillColor(colors.HexColor("#595959"))
        if f.get("tipo") == "AVV":
            canvas.drawString(16 * mm, 10 * mm, "Avviso di fattura: documento non valido ai fini fiscali. La fattura "
                              "elettronica sara' emessa al ricevimento del pagamento.")
        else:
            canvas.drawString(16 * mm, 10 * mm, "Copia di cortesia priva di valenza fiscale. La fattura originale e' "
                              "quella elettronica trasmessa tramite il Sistema di Interscambio,")
            canvas.drawString(16 * mm, 7 * mm, "disponibile nell'area riservata del sito dell'Agenzia delle Entrate.")
        canvas.drawRightString(A4[0] - 16 * mm, 7 * mm, f"Pag. {d.page}")
        canvas.restoreState()

    doc.build(el, onFirstPage=piede, onLaterPages=piede)
