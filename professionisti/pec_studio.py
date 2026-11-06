"""
Invio allo SDI via PEC e lettura delle ricevute dalla casella PEC.

- La password della PEC sta nel Portachiavi del Mac (keyring), mai nell'archivio.
- Primo invio a sdi01@pec.fatturapa.it; lo SDI comunica poi un indirizzo dedicato
  (sdiNN@pec.fatturapa.it), che viene riconosciuto e salvato da solo.
- La lettura delle ricevute si puo' ripetere quando si vuole: aggiorna solo cio' che cambia.
"""
import email
import imaplib
import re
import smtplib
import ssl
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid

from lxml import etree

import config_studio as C
import db_studio as db

PRIMO_INDIRIZZO = "sdi01@pec.fatturapa.it"
SERVIZIO_PORTACHIAVI = "fatture-pec"
ESITI = {"RC": "consegnata", "MC": "mancata", "AT": "mancata", "NS": "scartata"}
GIORNI_RICERCA = 60          # ricevute cercate negli ultimi giorni (oltre alla data del primo invio in attesa)


class ErrorePec(Exception):
    pass


def configurata():
    p = getattr(C, "PEC", None)
    return bool(p and p.get("smtp_server") and p.get("imap_server"))


def indirizzo_sdi():
    return db.impostazione("pec.indirizzo_sdi", PRIMO_INDIRIZZO) or PRIMO_INDIRIZZO


# ---------------------------------------------------------------- password (Portachiavi)
def _keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        raise ErrorePec("Manca la libreria keyring: chiudi il programma e riaprilo con avvia.command.")


def salva_password(pw):
    _keyring().set_password(SERVIZIO_PORTACHIAVI, C.PEC["utente"], pw)


def password():
    pw = _keyring().get_password(SERVIZIO_PORTACHIAVI, C.PEC["utente"])
    if not pw:
        raise ErrorePec("Password della PEC non ancora inserita: scrivila in Impostazioni.")
    return pw


# ---------------------------------------------------------------- connessioni
def apri_smtp():
    p, ctx = C.PEC, ssl.create_default_context()
    try:
        if int(p["smtp_porta"]) in (587, 25):
            s = smtplib.SMTP(p["smtp_server"], int(p["smtp_porta"]), timeout=30)
            s.starttls(context=ctx)
        else:
            s = smtplib.SMTP_SSL(p["smtp_server"], int(p["smtp_porta"]), context=ctx, timeout=30)
        s.login(p["utente"], password())
        return s
    except smtplib.SMTPAuthenticationError:
        raise ErrorePec("La PEC ha rifiutato la password: correggila in Impostazioni.")
    except (OSError, smtplib.SMTPException) as e:
        raise ErrorePec(f"Invio PEC non riuscito ({p['smtp_server']}): {e}")


def apri_imap():
    p = C.PEC
    try:
        i = imaplib.IMAP4_SSL(p["imap_server"], int(p["imap_porta"]), ssl_context=ssl.create_default_context())
        i.login(p["utente"], password())
        return i
    except imaplib.IMAP4.error:
        raise ErrorePec("La casella PEC ha rifiutato la password: correggila in Impostazioni.")
    except OSError as e:
        raise ErrorePec(f"Lettura della casella PEC non riuscita ({p['imap_server']}): {e}")


def verifica():
    """Prova login SMTP e IMAP senza inviare nulla. Restituisce i messaggi da mostrare."""
    s = apri_smtp()
    s.noop()
    s.quit()
    i = apri_imap()
    _, n = i.select("INBOX", readonly=True)
    i.logout()
    return f"Connessione riuscita: invio e lettura funzionano ({n[0].decode()} messaggi nella casella)."


# ---------------------------------------------------------------- invio
def primo_invio_in_attesa():
    """Documento del primo invio allo SDI, se e' ancora senza ricevuta: finche' lo SDI non ha assegnato
    l'indirizzo dedicato (con la prima ricevuta) non si inviano altri file."""
    if indirizzo_sdi() != PRIMO_INDIRIZZO:
        return None
    with db.conn() as c:
        return c.execute("SELECT * FROM documenti WHERE stato = 'inviata' AND storico = 0 AND esito_note LIKE 'PEC a %' "
                         "ORDER BY inviato_il LIMIT 1").fetchone()


def invia(doc, xml_path):
    """Manda l'XML allo SDI. Restituisce l'indirizzo usato."""
    dest = indirizzo_sdi()
    if dest == PRIMO_INDIRIZZO:
        with db.conn() as c:
            in_attesa = c.execute("SELECT COUNT(*) AS n FROM documenti WHERE stato = 'inviata' AND storico = 0 "
                                  "AND esito_note LIKE 'PEC%'").fetchone()["n"]
        if in_attesa:
            raise ErrorePec("È il primo invio via PEC: aspetta la ricevuta del documento già inviato. Con la "
                            "ricevuta lo SDI comunica l'indirizzo dedicato da usare per i successivi.")
    msg = EmailMessage()
    msg["From"] = C.PEC["indirizzo"]
    msg["To"] = dest
    msg["Subject"] = f"Invio fattura elettronica {xml_path.name}"
    msg["Message-ID"] = make_msgid(domain=C.PEC["indirizzo"].split("@")[-1])
    msg.set_content(f"Trasmissione al Sistema di Interscambio del file {xml_path.name}.")
    msg.add_attachment(xml_path.read_bytes(), maintype="application", subtype="xml", filename=xml_path.name)
    s = apri_smtp()
    try:
        s.send_message(msg)
    finally:
        s.quit()
    return dest


# ---------------------------------------------------------------- ricevute
def _allegati_xml(msg):
    visti = set()
    for part in msg.walk():                      # entra anche nella busta PEC (postacert.eml)
        nome = part.get_filename() or ""
        if not nome.lower().endswith(".xml") or part.get_content_type() == "message/rfc822":
            continue
        dati = part.get_payload(decode=True) or b""
        if (nome, len(dati)) not in visti:
            visti.add((nome, len(dati)))
            yield nome, dati


def _indirizzo_annunciato(msg):
    """Avviso dello SDI 'Il nuovo indirizzo da utilizzare per inviare le prossime fatture ... e' sdiNN@...'."""
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            testo = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
            m = re.search(r"nuovo indirizzo da utilizzare.{0,200}?(sdi\d+@pec\.fatturapa\.it)", testo, re.I | re.S)
            if m:
                return m.group(1).lower()
    return ""


def _mittenti_sdi(msg):
    """sdiNN@pec.fatturapa.it nelle intestazioni (lo SDI scrive 'Per conto di: sdiNN@pec.fatturapa.it')."""
    trovati = []
    for part in msg.walk():
        for h in ("From", "Reply-To", "Sender", "X-Sender"):
            trovati += re.findall(r"sdi\d+@pec\.fatturapa\.it", str(part.get(h, "")), re.I)
    return [t.lower() for t in trovati if t.lower() != PRIMO_INDIRIZZO]


def _leggi_ricevuta(nome, dati):
    """IT..._00001_RC_001.xml -> (file fattura, tipo, id SDI, dettaglio errori)."""
    m = re.match(r"^(IT[0-9A-Z]+_[0-9A-Za-z]{5})_(RC|NS|MC|AT|DT|NE)_\d{3}\.xml$", nome, re.I)
    if not m:
        return None
    id_sdi, dettaglio = "", ""
    try:
        t = etree.fromstring(dati, etree.XMLParser(resolve_entities=False, no_network=True))
        id_sdi = (t.findtext(".//IdentificativoSdI") or "").strip()
        dettaglio = " | ".join(f"{(e.findtext('Codice') or '').strip()} {(e.findtext('Descrizione') or '').strip()}"
                               for e in t.iter("Errore"))[:500]
    except etree.XMLSyntaxError:
        pass
    return m.group(1) + ".xml", m.group(2).upper(), id_sdi, dettaglio


def aggiorna_esiti():
    """Legge la casella PEC e aggiorna i documenti inviati. Restituisce (cambiamenti, avvisi)."""
    with db.conn() as c:
        docs = c.execute("SELECT * FROM documenti WHERE file_xml != '' AND storico = 0").fetchall()
    per_file = {d["file_xml"].rsplit("/", 1)[-1]: d for d in docs}
    in_attesa = [d["inviato_il"][:10] for d in docs if d["stato"] == "inviata" and d["inviato_il"]]
    dal = date.today() - timedelta(days=GIORNI_RICERCA)
    if in_attesa:
        dal = min(dal, date.fromisoformat(min(in_attesa)))
    cambiamenti, avvisi = [], []
    i = apri_imap()
    try:
        i.select("INBOX", readonly=True)
        # solo i messaggi dello SDI ("Per conto di: sdiNN@pec.fatturapa.it"): la casella puo' averne migliaia
        _, ids = i.search(None, f'(SINCE "{dal.strftime("%d-%b-%Y")}" FROM "fatturapa.it")')
        for mid in ids[0].split():
            _, dati = i.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(dati[0][1])
            # indirizzo dedicato: dall'avviso esplicito, oppure dal mittente di una ricevuta per un nostro file
            # (non da altre PEC dello SDI, ad esempio le fatture ricevute dai fornitori)
            nuovo = _indirizzo_annunciato(msg)
            if not nuovo and indirizzo_sdi() == PRIMO_INDIRIZZO and any(
                    (r := _leggi_ricevuta(n, x)) and r[0] in per_file for n, x in _allegati_xml(msg)):
                nuovo = next(iter(_mittenti_sdi(msg)), "")
            if nuovo and nuovo != indirizzo_sdi():
                db.salva_impostazione("pec.indirizzo_sdi", nuovo)
                avvisi.append(f"Lo SDI ha assegnato l'indirizzo {nuovo}: i prossimi invii andranno lì.")
            for nome, contenuto in _allegati_xml(msg):
                ric = _leggi_ricevuta(nome, contenuto)
                if not ric or ric[0] not in per_file:
                    continue
                file_xml, tipo, id_sdi, dettaglio = ric
                d = per_file[file_xml]
                stato = ESITI.get(tipo)
                if not stato:
                    continue
                if tipo == "NS" and re.search(r"\b(00002|00404)\b", dettaglio):
                    # duplicato: la stessa fattura era gia' arrivata allo SDI per un'altra via
                    if d["stato"] == "inviata":
                        avvisi.append(f"{d['numero']}/{d['anno']}: scartata come duplicato ({dettaglio}). "
                                      "Controlla nel Monitoraggio del portale se risulta già consegnata.")
                    continue
                if d["stato"] == stato and (not id_sdi or d["id_sdi"] == id_sdi):
                    continue
                if d["stato"] in ("consegnata", "mancata") and stato == "scartata":
                    continue                     # ricevuta piu' vecchia di un esito gia' positivo
                db.aggiorna_documento(d["id"], stato=stato, id_sdi=id_sdi or d["id_sdi"],
                                      esito_il=db.adesso(), esito_note=dettaglio if stato == "scartata" else "Esito letto dalla ricevuta PEC dello SDI")
                cambiamenti.append((d, stato, dettaglio))
    finally:
        i.logout()
    return cambiamenti, avvisi
