"""
Grassetto ed elenchi puntati nelle descrizioni delle voci e nelle note.

Si scrive testo semplice con due segni:
    **parole in grassetto**
    - riga di elenco            (anche "* " o "• " a inizio riga)

Nel PDF diventano grassetto e punti elenco veri; nell'XML per lo SDI (solo testo) i ** spariscono e
ogni riga di elenco comincia con "- ", l'unico segno sicuro per lo schema FatturaPA.
"""
import re
from xml.sax.saxutils import escape

from markupsafe import Markup

GRASSETTO = re.compile(r"\*\*(.+?)\*\*", re.S)
PUNTO = re.compile(r"^[ \t]*(?:[-*•·])[ \t]+(.*)$")


def _righe(s):
    """[(e_punto, testo), ...] riga per riga."""
    out = []
    for riga in str(s or "").replace("\r\n", "\n").strip("\n").split("\n"):
        m = PUNTO.match(riga)
        out.append((True, m.group(1).strip()) if m else (False, riga.rstrip()))
    return out


def piano(s):
    """Testo per l'XML: senza ** e con le righe di elenco che iniziano con "- "."""
    righe = [("- " + t if p else t) for p, t in _righe(s)]
    return "\n".join(righe).replace("**", "").strip()


def _grassetto(t, apri, chiudi):
    return GRASSETTO.sub(lambda m: f"{apri}{m.group(1)}{chiudi}", t)


def pdf(s, stile, stile_punto):
    """Flowable ReportLab: un paragrafo per ogni blocco di testo, uno per ogni punto elenco."""
    from reportlab.platypus import Paragraph
    out, testo = [], []

    def chiudi_testo():
        if testo:
            out.append(Paragraph(_grassetto(escape("\n".join(testo)), "<b>", "</b>").replace("\n", "<br/>"), stile))
            testo.clear()

    for p, t in _righe(s):
        if p:
            chiudi_testo()
            out.append(Paragraph(_grassetto(escape(t), "<b>", "</b>"), stile_punto, bulletText="•"))
        else:
            testo.append(t)
    while testo and not testo[-1].strip():
        testo.pop()
    chiudi_testo()
    return out or [Paragraph("", stile)]


def html(s):
    """Per le pagine del programma: <strong> e <ul><li>."""
    parti, punti, testo = [], [], []

    def chiudi():
        if testo:
            parti.append("<br>".join(_grassetto(escape(t), "<strong>", "</strong>") for t in testo))
            testo.clear()
        if punti:
            parti.append("<ul class=\"elenco-voce\">" + "".join(
                f"<li>{_grassetto(escape(t), '<strong>', '</strong>')}</li>" for t in punti) + "</ul>")
            punti.clear()

    for p, t in _righe(s):
        if p:
            if testo:
                chiudi()
            punti.append(t)
        else:
            if punti:
                chiudi()
            testo.append(t)
    chiudi()
    return Markup("".join(parti))
