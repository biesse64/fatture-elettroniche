"""Copia di cortesia PDF con l'impaginazione dello Studio Legale (logo MP, onorari, cassa, anticipazioni)."""
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import config_studio as C
from calcoli_studio import euro
from fatturapa_core import riepilogo

ROSSO = colors.HexColor("#B32E35")
SCURO = colors.HexColor("#1E1E24")
GRIGIO = colors.HexColor("#F3F1F1")
LINEA = colors.HexColor("#C9C3C3")

st = {
    "n": ParagraphStyle("n", fontName="Helvetica", fontSize=9, leading=12, textColor=SCURO),
    "p": ParagraphStyle("p", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=colors.HexColor("#4A4A50")),
    "studio": ParagraphStyle("s", fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=SCURO),
    "tit": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=ROSSO, alignment=TA_RIGHT),
    "dx": ParagraphStyle("dx", fontName="Helvetica", fontSize=9, leading=12, alignment=TA_RIGHT, textColor=SCURO),
    "lbl": ParagraphStyle("l", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=ROSSO),
    "lbldx": ParagraphStyle("ld", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=ROSSO, alignment=TA_RIGHT),
    "b": ParagraphStyle("b", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=SCURO),
    "tot": ParagraphStyle("tt", fontName="Helvetica-Bold", fontSize=11, leading=14, alignment=TA_RIGHT, textColor=SCURO),
}


def P(t, s="n"):
    return Paragraph(escape(str(t or "")).replace("\n", "<br/>"), st[s])


def data_it(iso):
    return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""


def crea_pdf(percorso, f, tot, studio, privato):
    """f: modello fattura (calcoli_studio.modello_fattura); tot: totali; privato: cliente senza P.IVA."""
    cli = f["cliente"]
    doc = SimpleDocTemplate(str(percorso), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=12 * mm, bottomMargin=18 * mm,
                            title=f"{'Nota di credito' if f['tipo'] == 'TD04' else 'Fattura'} {f['numero']}",
                            author=C.STUDIO["intestazione"])
    W = A4[0] - 32 * mm
    el = []

    # --- intestazione: logo + nome dello studio, contatti
    testa = []
    if C.LOGO.exists():
        iw, ih = ImageReader(str(C.LOGO)).getSize()
        h = 15 * mm
        testa.append(Image(str(C.LOGO), width=h * iw / ih, height=h))
    if testa:
        t = Table([[testa, P(C.STUDIO["intestazione"], "studio")]], colWidths=[62 * mm, W - 62 * mm])
    else:                                          # senza logo: solo il nome
        t = Table([[P(C.STUDIO["intestazione"], "studio")]], colWidths=[W])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    el.append(t)
    tel_mail = " - ".join(x for x in (f"Tel. {studio['telefono']}" if studio["telefono"] else "", studio["email"]) if x)
    righe_contatti = [f"{studio['indirizzo']} - {studio['cap']} {studio['comune']} ({studio['provincia']})", tel_mail,
                      f"PEC {studio['pec']}" if studio["pec"] else "", studio["web"],
                      f"C.F. {studio['cf']} - P.IVA {studio['piva']}"]
    contatti = "<br/>".join(escape(x) for x in righe_contatti if x)
    tipo = "NOTA DI CREDITO" if f["tipo"] == "TD04" else "FATTURA"
    numero = Paragraph(f"n. <b>{escape(f['numero'])}</b> del <b>{data_it(f['data'])}</b>", st["dx"])
    t = Table([[Paragraph(contatti, st["p"]), [P(tipo, "tit"), numero]]], colWidths=[W * 0.62, W * 0.38])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("LINEBELOW", (0, 0), (-1, 0), 1.2, ROSSO), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    el += [t, Spacer(1, 6 * mm)]

    # --- destinatario (senza riquadro Destinazione: si tratta di prestazioni)
    loc = f"{cli['cap'] + ' ' if cli['cap'] else ''}{cli['comune']}"
    if cli["provincia"]:
        loc += f" ({cli['provincia']})"
    righe_cli = [P("DESTINATARIO", "lbl"), P(cli["denominazione"], "b"), P(cli["indirizzo"]), P(loc)]
    if cli["nazione"] != "IT":
        righe_cli.append(P(cli["nazione"]))
    ids = []
    if cli["piva"]:
        ids.append(f"P.IVA {cli['piva']}")
    if cli["cf"] and cli["cf"] != cli["piva"]:
        ids.append(f"Cod. Fisc. {cli['cf']}")
    if ids:
        righe_cli.append(P(" - ".join(ids)))
    t = Table([[righe_cli, ""]], colWidths=[W * 0.55, W * 0.45])
    t.setStyle(TableStyle([("BOX", (0, 0), (0, 0), 0.6, LINEA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (0, 0), 6), ("TOPPADDING", (0, 0), (0, 0), 5),
                           ("BOTTOMPADDING", (0, 0), (0, 0), 6)]))
    el += [t, Spacer(1, 6 * mm)]

    # --- righe: onorari, bollo, anticipazioni (con ore x tariffa se presenti)
    con_qta = any(not r.get("descrittiva") and r.get("qta") is not None and r["qta"] != 1 for r in f["righe"])
    if con_qta:
        dati = [[P("Descrizione", "lbl"), P("Q.tà", "lbldx"), P("Prezzo", "lbldx"), P("Importo", "lbldx")]]
        larghezze = [W * 0.58, W * 0.10, W * 0.14, W * 0.18]
    else:
        dati = [[P("Descrizione", "lbl"), P("Importo", "lbldx")]]
        larghezze = [W * 0.78, W * 0.22]

    def riga_pdf(r):
        imp = "" if r.get("descrittiva") else euro(r["totale"])
        if not con_qta:
            return [P(r["descr"]), P(imp, "dx")]
        q = "" if r.get("descrittiva") or r.get("qta") is None else \
            f"{r['qta']:f}".rstrip("0").rstrip(".").replace(".", ",") + (f" {r['um']}" if r.get("um") else "")
        pr = "" if r.get("descrittiva") or r.get("qta") is None else euro(r["prezzo"])
        return [P(r["descr"]), P(q, "dx"), P(pr, "dx"), P(imp, "dx")]

    stile = [("BACKGROUND", (0, 0), (-1, 0), GRIGIO), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA),
             ("VALIGN", (0, 0), (-1, -1), "TOP")]
    ant = [r for r in f["righe"] if r.get("tipo") == "anticipazione"]
    for r in f["righe"]:
        if r.get("tipo") != "anticipazione":
            dati.append(riga_pdf(r))
    if ant:
        dati.append([P(C.ANTICIPAZIONI["etichetta"].upper() + " (non soggette a contributo previdenziale)", "lbl")]
                    + [""] * (len(larghezze) - 1))
        for r in ant:
            dati.append(riga_pdf(r))
    t = Table(dati, colWidths=larghezze, repeatRows=1)
    t.setStyle(TableStyle(stile))
    el += [t, Spacer(1, 6 * mm)]

    # --- riepilogo e totali
    if tot["iva"]:                                 # regime ordinario: riepilogo IVA
        riep = [[P("Riepilogo IVA", "lbl"), P("Imponibile", "lbldx"), P("Imposta", "lbldx")]]
        for g in riepilogo(f)["gruppi"]:
            nome = f"IVA {g['aliquota']:.0f}%" if g["aliquota"] else f"{g['natura']} {g['rif_norm']}"
            riep.append([P(nome), P(euro(g["imponibile"]), "dx"), P(euro(g["imposta"]), "dx")])
        tr = Table(riep, colWidths=[W * 0.22, W * 0.15, W * 0.13])
    else:
        riep = [[P("Riepilogo", "lbl"), P("Importo", "lbldx")],
                [P(f"{C.RIF_FORFETTARIO} - non soggetto IVA"), P(euro(tot["onorari"] + tot["bollo"] + tot["cassa"]), "dx")]]
        if tot["anticipazioni"]:
            riep.append([P(f"{C.ANTICIPAZIONI['etichetta']} - {C.ANTICIPAZIONI['rif_norm']}"),
                         P(euro(tot["anticipazioni"]), "dx")])
        tr = Table(riep, colWidths=[W * 0.38, W * 0.14])
    tr.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), GRIGIO), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA),
                            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    cassa = [P(f"{C.CASSA['descrizione']} {C.CASSA['aliquota_perc']}% su {euro(tot['base_cassa'])}"),
             P(euro(tot["cassa"]), "dx")]
    if tot["iva"]:
        righe_tot = [[P("Onorari"), P(euro(tot["onorari"]), "dx")], cassa,
                     [P("Imponibile"), P(euro(tot["imponibile"]), "dx")],
                     [P(f"IVA {C.IVA_PERC}%"), P(euro(tot["iva"]), "dx")]]
    else:
        # come in Easyfatt: onorari + bollo in un'unica voce "Tot. importi non soggetti IVA"
        righe_tot = [[P("Tot. importi non soggetti IVA"), P(euro(tot["onorari"] + tot["bollo"]), "dx")], cassa]
    if tot["anticipazioni"]:
        righe_tot.append([P(C.ANTICIPAZIONI["etichetta"]), P(euro(tot["anticipazioni"]), "dx")])
    if tot["ritenuta"]:
        rit = C.RITENUTA
        righe_tot += [[P("Totale documento"), P(euro(tot["totale"]), "dx")],
                      [P(f"{rit.get('descrizione', 'Ritenuta')} {rit['aliquota_perc']}% su {euro(tot['onorari'])}"),
                       P("- " + euro(tot["ritenuta"]), "dx")],
                      [P("NETTO A PAGARE", "b"), Paragraph(euro(tot["netto"]), st["tot"])]]
    else:
        righe_tot.append([P("TOTALE DOCUMENTO", "b"), Paragraph(euro(tot["totale"]), st["tot"])])
    tt = Table(righe_tot, colWidths=[W * 0.33, W * 0.15])
    n = len(righe_tot) - 1
    tt.setStyle(TableStyle([("LINEABOVE", (0, n), (-1, n), 1, ROSSO), ("BACKGROUND", (0, n), (-1, n), GRIGIO),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    t = Table([[tr, tt]], colWidths=[W * 0.52, W * 0.48])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    el += [KeepTogether(t), Spacer(1, 5 * mm)]

    # --- pagamento, riferimento, note
    blocco = [P(C.TESTO_RITENUTA, "b"), Spacer(1, 3 * mm)] if C.TESTO_RITENUTA else []
    if f["tipo"] == "TD04":
        rif = "; ".join(f"n. {i}" + (f" del {data_it(d)}" if d else "") for i, d in f["fatture_collegate"])
        blocco += [P("RIFERIMENTO", "lbl"), P(f"Nota di credito a storno, totale o parziale, della fattura {rif}."),
                   P(f"Importo a credito del cliente: {euro(tot['netto'])}", "b")]
    for p in f["pagamenti"]:
        blocco += [P("PAGAMENTO", "lbl"),
                   P(f"{C.PAGAMENTO['descrizione']} - scadenza {data_it(p['scadenza'])}: {euro(p['importo'])}"),
                   P(p["istituto"]), P(f"IBAN {p['iban']}", "b")]
    note = []
    if f["causale"]:
        note.append(P(f["causale"]))
    if privato:
        note.append(P(C.TESTO_PRIVATI))
    if (tot["bollo"] or tot["bollo_dovuto"]) and C.TESTO_BOLLO:
        note.append(P(C.TESTO_BOLLO))
    el.append(KeepTogether(blocco + [Spacer(1, 4 * mm)] + note))

    def piede(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.6)
        canvas.setFillColor(colors.HexColor("#5A5A60"))
        canvas.drawString(16 * mm, 11 * mm, C.TESTO_PRIVACY[:150])
        canvas.drawString(16 * mm, 8 * mm, C.TESTO_PRIVACY[150:])
        canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Pag. {d.page}")
        canvas.restoreState()

    doc.build(el, onFirstPage=piede, onLaterPages=piede)
