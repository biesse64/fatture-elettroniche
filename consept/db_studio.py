"""Archivio SQLite di Consept: clienti, codici IVA, documenti (fatture e note di credito), righe, impostazioni."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

import config_studio as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS clienti (
    id INTEGER PRIMARY KEY,
    denominazione TEXT NOT NULL,
    cf TEXT DEFAULT '', piva TEXT DEFAULT '',
    indirizzo TEXT DEFAULT '', cap TEXT DEFAULT '', comune TEXT DEFAULT '', provincia TEXT DEFAULT '',
    nazione TEXT DEFAULT 'IT',
    codice_destinatario TEXT DEFAULT '', pec TEXT DEFAULT '', email TEXT DEFAULT '',
    note TEXT DEFAULT '',
    codice TEXT DEFAULT '',                    -- codice cliente (Excel / Easyfatt)
    codice_iva TEXT DEFAULT '',                -- codice IVA predefinito delle righe
    giorni_pagamento TEXT DEFAULT '',          -- scadenza = data fattura + giorni
    id_estero TEXT DEFAULT '',                 -- identificativo fiscale dei clienti esteri
    intento_protocollo TEXT DEFAULT '', intento_data TEXT DEFAULT '',   -- dichiarazione d'intento
    riferimento TEXT DEFAULT '',               -- persona di riferimento
    creato_il TEXT
);
CREATE TABLE IF NOT EXISTS codici_iva (
    codice TEXT PRIMARY KEY,
    aliquota TEXT NOT NULL DEFAULT '0',        -- percentuale, es. '22'
    natura TEXT DEFAULT '',                    -- N1, N2.1, N3.5... (vuota se c'e' l'IVA)
    rif_norm TEXT DEFAULT '',                  -- riferimento normativo stampato in fattura
    bollo INTEGER NOT NULL DEFAULT 0,          -- 1 = operazione soggetta a bollo
    descrizione TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS documenti (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL DEFAULT 'TD01',          -- TD01 fattura, TD04 nota di credito
    anno INTEGER NOT NULL, numero INTEGER NOT NULL, data TEXT NOT NULL,
    suffisso TEXT NOT NULL DEFAULT '',         -- es. 'A' per i numeri 66/A di Easyfatt
    cliente_id INTEGER REFERENCES clienti(id),
    terzo_pagatore TEXT DEFAULT '',
    note TEXT DEFAULT '',
    bollo INTEGER NOT NULL DEFAULT 1,          -- 1 = addebita il bollo se dovuto
    rif_numero TEXT DEFAULT '', rif_data TEXT DEFAULT '',
    stato TEXT NOT NULL DEFAULT 'bozza',
    progressivo TEXT DEFAULT '', file_xml TEXT DEFAULT '', file_pdf TEXT DEFAULT '',
    generato_il TEXT DEFAULT '', inviato_il TEXT DEFAULT '',
    id_sdi TEXT DEFAULT '', esito_il TEXT DEFAULT '', esito_note TEXT DEFAULT '',
    totale TEXT DEFAULT '',
    storico INTEGER NOT NULL DEFAULT 0,        -- 1 = importato da Easyfatt, gia' inviato
    saldato INTEGER NOT NULL DEFAULT 0,        -- 1 = pagamento ricevuto
    saldato_il TEXT DEFAULT '',                -- data del saldo (vuota se non nota)
    giorni_pagamento TEXT DEFAULT '',          -- vuoto = quelli del cliente
    UNIQUE (anno, numero, suffisso)
);
CREATE TABLE IF NOT EXISTS righe (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES documenti(id) ON DELETE CASCADE,
    ordine INTEGER NOT NULL,
    tipo TEXT NOT NULL,                        -- onorario | anticipazione
    descrizione TEXT DEFAULT '',
    importo TEXT DEFAULT '',                   -- vuoto = riga solo descrittiva
    quantita TEXT DEFAULT '',                  -- facoltativi: ore x tariffa (importo = quantita x prezzo)
    um TEXT DEFAULT '',
    prezzo TEXT DEFAULT '',
    codice_iva TEXT DEFAULT ''                 -- vuoto = predefinito del cliente
);
CREATE TABLE IF NOT EXISTS impostazioni (chiave TEXT PRIMARY KEY, valore TEXT);
CREATE TABLE IF NOT EXISTS incassi (             -- pagamenti ricevuti: anche parziali (acconti)
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES documenti(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    importo TEXT NOT NULL,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pagamenti (           -- condizioni di pagamento (come in Easyfatt)
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,                 -- es. 'Bonifico 30 gg.'
    modalita TEXT NOT NULL DEFAULT 'MP05',     -- codice FatturaPA: MP01 contanti, MP05 bonifico, MP12 RiBa...
    giorni TEXT NOT NULL DEFAULT '0',          -- una scadenza '30', piu' rate '30,60,90'
    fine_mese INTEGER NOT NULL DEFAULT 0       -- 1 = scadenza a fine mese
);
CREATE TABLE IF NOT EXISTS banche (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,                        -- come compare in fattura
    iban TEXT DEFAULT '', bic TEXT DEFAULT '',
    valuta TEXT NOT NULL DEFAULT 'EUR',        -- conto per gli incassi in questa valuta
    dettagli TEXT DEFAULT '',                  -- coordinate per i conti senza IBAN (es. account e routing USA)
    predefinita INTEGER NOT NULL DEFAULT 0     -- 1 = proposta per la sua valuta
);
"""


@contextmanager
def conn():
    C.DATI.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(C.DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def inizializza():
    with conn() as c:
        vecchio = c.execute("SELECT sql FROM sqlite_master WHERE name = 'documenti'").fetchone()
        if vecchio and "suffisso" not in vecchio["sql"]:
            raise SystemExit(f"L'archivio {C.DB_PATH} è di una versione di prova precedente: "
                             "elimina la cartella 'dati' e riavvia.")
        c.executescript(SCHEMA)
        if "collegato_id" not in {r["name"] for r in c.execute("PRAGMA table_info(documenti)")}:
            c.execute("ALTER TABLE documenti ADD COLUMN collegato_id INTEGER")   # avviso -> fattura creata
        # colonne aggiunte nelle versioni successive (l'archivio esistente resta valido)
        presenti = {r["name"] for r in c.execute("PRAGMA table_info(righe)")}
        for col in ("quantita", "um", "prezzo"):
            if col not in presenti:
                c.execute(f"ALTER TABLE righe ADD COLUMN {col} TEXT DEFAULT ''")
        aggiungi_colonne(c, "documenti", netto="TEXT DEFAULT ''", pagamento="TEXT DEFAULT ''",
                         banca_id="INTEGER", imponibile="TEXT DEFAULT ''", iva="TEXT DEFAULT ''",
                         valuta="TEXT DEFAULT ''",          # '' = solo euro; 'USD' = copia per il cliente in dollari
                         cambio="TEXT DEFAULT ''",          # 1 USD = cambio EUR
                         file_pdf_valuta="TEXT DEFAULT ''")
        aggiungi_colonne(c, "righe", prezzo_valuta="TEXT DEFAULT ''", importo_valuta="TEXT DEFAULT ''")
        aggiungi_colonne(c, "clienti", pagamento="TEXT DEFAULT ''")
        if not c.execute("SELECT 1 FROM pagamenti LIMIT 1").fetchone():
            c.executemany("INSERT INTO pagamenti (nome, modalita, giorni, fine_mese) VALUES (?, ?, ?, ?)",
                          PAGAMENTI_INIZIALI)
        if not c.execute("SELECT 1 FROM banche LIMIT 1").fetchone():
            c.executemany("INSERT INTO banche (nome, iban, bic, valuta, dettagli, predefinita) VALUES (?, ?, ?, ?, ?, ?)",
                          BANCHE_INIZIALI)
        if not c.execute("SELECT 1 FROM codici_iva LIMIT 1").fetchone():
            c.executemany("INSERT INTO codici_iva (codice, aliquota, natura, rif_norm, bollo, descrizione) "
                          "VALUES (?, ?, ?, ?, ?, ?)", CODICI_IVA_INIZIALI)


def aggiungi_colonne(c, tabella, **colonne):
    """Colonne aggiunte nelle versioni successive: l'archivio esistente resta valido."""
    presenti = {r["name"] for r in c.execute(f"PRAGMA table_info({tabella})")}
    for nome, tipo in colonne.items():
        if nome not in presenti:
            c.execute(f"ALTER TABLE {tabella} ADD COLUMN {nome} {tipo}")


# condizioni di pagamento di partenza (dai tipi di pagamento di Easyfatt usati per le vendite)
PAGAMENTI_INIZIALI = [
    ("Bonifico vista fattura", "MP05", "0", 0),
    ("Bonifico bancario", "MP05", "0", 0),
    ("Bonifico 30 gg.", "MP05", "30", 0),
    ("Bonifico 30 gg F.M.", "MP05", "30", 1),
    ("Bonifico 60 gg. D.F.", "MP05", "60", 0),
    ("Bonifico 60 gg F.M.", "MP05", "60", 1),
    ("Bonifico 90 gg F.M.", "MP05", "90", 1),
    ("Bonifico 90 gg. F.M.D.F.", "MP05", "90", 1),
    ("Pagamento tre rate: ordine, 30 gg., 60 gg.", "MP05", "0,30,60", 0),
    ("Riba", "MP12", "0", 0),
    ("RIBA 30 gg F.M.", "MP12", "30", 1),
    ("RIBA 60 gg F.M.", "MP12", "60", 1),
    ("RIBA 90 gg F.M.", "MP12", "90", 1),
    ("RIBA 30-60 gg F.M.", "MP12", "30,60", 1),
    ("RIBA 30-60-90 gg F.M.", "MP12", "30,60,90", 1),
    ("Contanti", "MP01", "0", 0),
    ("Assegno", "MP02", "0", 0),
    ("Assegno circolare", "MP03", "0", 0),
    ("Carta di credito", "MP08", "0", 0),
    ("Carta di pagamento", "MP08", "0", 0),
    ("Bancomat", "MP08", "0", 0),
    ("PayPal", "MP08", "0", 0),
    ("Bollettino di c/c postale", "MP18", "0", 0),
    ("Domiciliazione bancaria", "MP16", "0", 0),
    ("Rid", "MP09", "0", 0),
    ("SDD Core", "MP20", "0", 0),
    ("SDD B2B", "MP21", "0", 0),
]

BANCHE_INIZIALI = [
    ("Banca Intesa Sanpaolo - Filiale Limena", "IT46Y0306962619100000000631", "", "EUR", "", 1),
    ("Wise US Inc.", "", "TRWIUS35XXX", "USD",
     "108 W 13th St, Wilmington, DE 19801, United States\n"
     "Account holder: CONSEPT DI BRUNO STEFANUTTI & C. SAS\n"
     "Account number: 210573958646\nRouting number: 101019628", 1),
]

# codici di partenza (gli stessi dell'Excel Consept); si modificano dalla pagina Codici IVA
CODICI_IVA_INIZIALI = [
    ("22", "22", "", "", 0, "IVA 22%"),
    ("NS7x", "0", "N2.1", "Non sogg. art. 7-ter DPR 633/72 extra-UE", 1, "Servizi a clienti extra-UE"),
    ("NS7UE", "0", "N2.1", "Non sogg. art. 7-ter DPR 633/72 - inversione contabile", 1, "Servizi a clienti UE"),
    ("N8c", "0", "N3.5", "Non imp. art. 8 c. 1 lett. c DPR 633/72", 1, "Esportatore abituale (dichiarazione d'intento)"),
    ("X15", "0", "N1", "Escluso art. 15 DPR 633/72", 1, "Spese escluse art. 15"),
]


def adesso():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- impostazioni
MODIFICABILI = ["telefono", "email", "pec", "web"]


def impostazione(chiave, default=""):
    with conn() as c:
        r = c.execute("SELECT valore FROM impostazioni WHERE chiave = ?", (chiave,)).fetchone()
    return r["valore"] if r else default


def salva_impostazione(chiave, valore):
    with conn() as c:
        c.execute("INSERT INTO impostazioni (chiave, valore) VALUES (?, ?) "
                  "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore", (chiave, valore))


def studio():
    """Dati dello studio: config + valori modificati dalla pagina Impostazioni."""
    s = dict(C.STUDIO)
    for k in MODIFICABILI:
        v = impostazione(f"studio.{k}", None)
        if v is not None:
            s[k] = v
    return s


def prossimo_progressivo(consuma=True):
    """Progressivo d'invio (nome del file XML). Con consuma=False lo legge senza usarlo."""
    with conn() as c:
        r = c.execute("SELECT valore FROM impostazioni WHERE chiave = 'progressivo'").fetchone()
        n = int(r["valore"]) + 1 if r else 1
        if consuma:
            c.execute("INSERT INTO impostazioni (chiave, valore) VALUES ('progressivo', ?) "
                      "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore", (str(n),))
    return f"{n:05d}"


def prossimo_numero(anno):
    """Numerazione unica per anno (fatture e note di credito). Rispetta un eventuale
    'primo numero' impostato per continuare la numerazione di Easyfatt."""
    with conn() as c:
        r = c.execute("SELECT MAX(numero) AS m FROM documenti WHERE anno = ? AND tipo != 'AVV'", (anno,)).fetchone()
    massimo = r["m"] or 0
    primo = impostazione(f"primo_numero.{anno}", "")
    if primo.isdigit():
        massimo = max(massimo, int(primo) - 1)
    return massimo + 1


SUFFISSO_AVVISO = "AVV"          # gli avvisi hanno una numerazione propria (suffisso interno, non stampato)


def prossimo_avviso(anno):
    with conn() as c:
        r = c.execute("SELECT MAX(numero) AS m FROM documenti WHERE anno = ? AND tipo = 'AVV'", (anno,)).fetchone()
    return (r["m"] or 0) + 1


# ---------------------------------------------------------------- clienti
CAMPI_CLIENTE = ["denominazione", "cf", "piva", "indirizzo", "cap", "comune", "provincia", "nazione",
                 "codice_destinatario", "pec", "email", "note", "codice_iva", "giorni_pagamento", "id_estero",
                 "intento_protocollo", "intento_data", "riferimento", "pagamento"]


# ---------------------------------------------------------------- codici IVA
CAMPI_CODICE_IVA = ["codice", "aliquota", "natura", "rif_norm", "bollo", "descrizione"]


def codici_iva():
    with conn() as c:
        return c.execute("SELECT * FROM codici_iva ORDER BY CAST(aliquota AS REAL) DESC, codice").fetchall()


def codice_iva(codice):
    with conn() as c:
        return c.execute("SELECT * FROM codici_iva WHERE codice = ?", (codice,)).fetchone()


def salva_codice_iva(d, vecchio=None):
    valori = [d.get(k, "") for k in CAMPI_CODICE_IVA]
    with conn() as c:
        if vecchio:
            c.execute(f"UPDATE codici_iva SET {', '.join(k + ' = ?' for k in CAMPI_CODICE_IVA)} WHERE codice = ?",
                      (*valori, vecchio))
            if vecchio != d["codice"]:                 # rinominato: aggiorna clienti e righe
                c.execute("UPDATE clienti SET codice_iva = ? WHERE codice_iva = ?", (d["codice"], vecchio))
                c.execute("UPDATE righe SET codice_iva = ? WHERE codice_iva = ?", (d["codice"], vecchio))
        else:
            c.execute(f"INSERT INTO codici_iva ({', '.join(CAMPI_CODICE_IVA)}) VALUES "
                      f"({', '.join('?' for _ in CAMPI_CODICE_IVA)})", valori)


def uso_codice_iva(codice):
    """Quanti clienti e righe usano il codice (per non eliminarne uno in uso)."""
    with conn() as c:
        return (c.execute("SELECT COUNT(*) AS n FROM clienti WHERE codice_iva = ?", (codice,)).fetchone()["n"]
                + c.execute("SELECT COUNT(*) AS n FROM righe WHERE codice_iva = ?", (codice,)).fetchone()["n"])


def elimina_codice_iva(codice):
    with conn() as c:
        c.execute("DELETE FROM codici_iva WHERE codice = ?", (codice,))


# ---------------------------------------------------------------- pagamenti e banche
MODALITA = {
    "MP01": "Contanti", "MP02": "Assegno", "MP03": "Assegno circolare", "MP05": "Bonifico",
    "MP07": "Bollettino bancario", "MP08": "Carta di pagamento", "MP09": "RID", "MP12": "RiBa",
    "MP13": "MAV", "MP16": "Domiciliazione bancaria", "MP18": "Bollettino di c/c postale",
    "MP19": "SEPA Direct Debit", "MP20": "SEPA Direct Debit CORE", "MP21": "SEPA Direct Debit B2B",
    "MP23": "PagoPA",
}
CAMPI_PAGAMENTO = ["nome", "modalita", "giorni", "fine_mese"]
CAMPI_BANCA = ["nome", "iban", "bic", "valuta", "dettagli", "predefinita"]


def pagamenti():
    with conn() as c:
        return c.execute("SELECT * FROM pagamenti ORDER BY nome COLLATE NOCASE").fetchall()


def pagamento(pid=None, nome=None):
    with conn() as c:
        if nome is not None:
            return c.execute("SELECT * FROM pagamenti WHERE nome = ?", (nome,)).fetchone()
        return c.execute("SELECT * FROM pagamenti WHERE id = ?", (pid,)).fetchone()


def salva_record(tabella, campi, dati, rid=None):
    valori = [dati.get(k, "") for k in campi]
    with conn() as c:
        if rid:
            c.execute(f"UPDATE {tabella} SET {', '.join(k + ' = ?' for k in campi)} WHERE id = ?", (*valori, rid))
            return rid
        return c.execute(f"INSERT INTO {tabella} ({', '.join(campi)}) VALUES ({', '.join('?' for _ in campi)})",
                         valori).lastrowid


def elimina_record(tabella, rid):
    with conn() as c:
        c.execute(f"DELETE FROM {tabella} WHERE id = ?", (rid,))


def banche():
    with conn() as c:
        return c.execute("SELECT * FROM banche ORDER BY valuta, predefinita DESC, nome").fetchall()


def banca(bid):
    with conn() as c:
        return c.execute("SELECT * FROM banche WHERE id = ?", (bid,)).fetchone()


def banca_predefinita(valuta="EUR"):
    with conn() as c:
        return c.execute("SELECT * FROM banche WHERE valuta = ? ORDER BY predefinita DESC, id LIMIT 1",
                         (valuta,)).fetchone()


def salva_banca(dati, bid=None):
    bid = salva_record("banche", CAMPI_BANCA, dati, bid)
    if dati.get("predefinita"):                    # una sola predefinita per valuta
        with conn() as c:
            c.execute("UPDATE banche SET predefinita = 0 WHERE valuta = ? AND id != ?", (dati["valuta"], bid))
    return bid


def uso_pagamento(nome):
    with conn() as c:
        return (c.execute("SELECT COUNT(*) AS n FROM clienti WHERE pagamento = ?", (nome,)).fetchone()["n"]
                + c.execute("SELECT COUNT(*) AS n FROM documenti WHERE pagamento = ?", (nome,)).fetchone()["n"])


def uso_banca(bid):
    with conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM documenti WHERE banca_id = ?", (bid,)).fetchone()["n"]


def cliente_per_codice(codice):
    with conn() as c:
        return c.execute("SELECT * FROM clienti WHERE codice = ?", (codice,)).fetchone()


def clienti(cerca=""):
    with conn() as c:
        if cerca:
            q = f"%{cerca}%"
            return c.execute("SELECT * FROM clienti WHERE denominazione LIKE ? OR cf LIKE ? OR piva LIKE ? "
                             "OR codice = ? ORDER BY denominazione COLLATE NOCASE", (q, q, q, cerca)).fetchall()
        return c.execute("SELECT * FROM clienti ORDER BY denominazione COLLATE NOCASE").fetchall()


def cliente(cid):
    with conn() as c:
        return c.execute("SELECT * FROM clienti WHERE id = ?", (cid,)).fetchone()


def salva_cliente(dati, cid=None):
    valori = [dati.get(k, "") for k in CAMPI_CLIENTE]
    with conn() as c:
        if cid:
            c.execute(f"UPDATE clienti SET {', '.join(k + ' = ?' for k in CAMPI_CLIENTE)} WHERE id = ?",
                      (*valori, cid))
            return cid
        cur = c.execute(f"INSERT INTO clienti ({', '.join(CAMPI_CLIENTE)}, creato_il) "
                        f"VALUES ({', '.join('?' for _ in CAMPI_CLIENTE)}, ?)", (*valori, adesso()))
        return cur.lastrowid


def documenti_cliente(cid):
    with conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM documenti WHERE cliente_id = ?", (cid,)).fetchone()["n"]


def elimina_cliente(cid):
    with conn() as c:
        c.execute("DELETE FROM clienti WHERE id = ?", (cid,))


# ---------------------------------------------------------------- documenti
def documenti(anno=None, cerca=""):
    sql = ("SELECT d.*, c.denominazione AS cliente FROM documenti d LEFT JOIN clienti c ON c.id = d.cliente_id "
           "WHERE 1=1")
    par = []
    if anno:
        sql += " AND d.anno = ?"
        par.append(anno)
    if cerca:
        sql += " AND (c.denominazione LIKE ? OR d.terzo_pagatore LIKE ? OR CAST(d.numero AS TEXT) = ?)"
        par += [f"%{cerca}%", f"%{cerca}%", cerca]
    sql += " ORDER BY d.anno DESC, d.numero DESC, d.suffisso DESC"
    with conn() as c:
        return c.execute(sql, par).fetchall()


def con_voci():
    """Documenti con almeno una voce con importo: di questi si puo' ricostruire la copia PDF."""
    with conn() as c:
        return {r[0] for r in c.execute("SELECT DISTINCT documento_id FROM righe WHERE TRIM(importo) != ''")}


def anni():
    with conn() as c:
        return [r["anno"] for r in c.execute("SELECT DISTINCT anno FROM documenti ORDER BY anno DESC")]


def documento(did):
    with conn() as c:
        d = c.execute("SELECT * FROM documenti WHERE id = ?", (did,)).fetchone()
        if not d:
            return None, []
        r = c.execute("SELECT * FROM righe WHERE documento_id = ? ORDER BY ordine", (did,)).fetchall()
    return d, r


def documento_per_numero(anno, numero, suffisso=""):
    with conn() as c:
        return c.execute("SELECT * FROM documenti WHERE anno = ? AND numero = ? AND suffisso = ?",
                         (anno, numero, suffisso)).fetchone()


CAMPI_DOC = ["tipo", "anno", "numero", "suffisso", "data", "cliente_id", "terzo_pagatore", "note", "bollo",
             "rif_numero", "rif_data", "pagamento", "banca_id", "valuta", "cambio"]
CAMPI_RIGA = ["tipo", "descrizione", "importo", "quantita", "um", "prezzo", "codice_iva", "prezzo_valuta",
              "importo_valuta"]


def _scrivi_righe(c, did, righe):
    for i, r in enumerate(righe):
        c.execute(f"INSERT INTO righe (documento_id, ordine, {', '.join(CAMPI_RIGA)}) "
                  f"VALUES (?, ?, {', '.join('?' for _ in CAMPI_RIGA)})",
                  (did, i, *[r.get(k, "") or "" for k in CAMPI_RIGA]))


def salva_documento(dati, righe, did=None):
    """dati: campi di CAMPI_DOC; righe: lista di dict tipo/descrizione/importo."""
    valori = [dati.get(k, None if k in ("cliente_id", "banca_id") else "") for k in CAMPI_DOC]
    with conn() as c:
        if did:
            c.execute(f"UPDATE documenti SET {', '.join(k + ' = ?' for k in CAMPI_DOC)}, totale = ?, netto = ? "
                      "WHERE id = ?", (*valori, dati.get("totale", ""), dati.get("netto", ""), did))
            c.execute("DELETE FROM righe WHERE documento_id = ?", (did,))
        else:
            cur = c.execute(f"INSERT INTO documenti ({', '.join(CAMPI_DOC)}, totale, netto) "
                            f"VALUES ({', '.join('?' for _ in CAMPI_DOC)}, ?, ?)",
                            (*valori, dati.get("totale", ""), dati.get("netto", "")))
            did = cur.lastrowid
        _scrivi_righe(c, did, righe)
    return did


def sostituisci_righe(did, righe):
    """Voci di un documento gia' registrato (es. storico che riceve il dettaglio dall'Excel)."""
    with conn() as c:
        c.execute("DELETE FROM righe WHERE documento_id = ?", (did,))
        _scrivi_righe(c, did, righe)


# ---------------------------------------------------------------- incassi
def incassi(did):
    with conn() as c:
        return c.execute("SELECT * FROM incassi WHERE documento_id = ? ORDER BY data, id", (did,)).fetchall()


def incassato():
    """id documento -> somma incassata (solo i documenti con almeno un incasso registrato)."""
    from decimal import Decimal
    out = {}
    with conn() as c:
        for r in c.execute("SELECT documento_id, importo FROM incassi"):
            out[r["documento_id"]] = out.get(r["documento_id"], Decimal(0)) + Decimal(r["importo"])
    return out


def aggiungi_incasso(did, data, importo, note=""):
    with conn() as c:
        c.execute("INSERT INTO incassi (documento_id, data, importo, note) VALUES (?, ?, ?, ?)",
                  (did, data, str(importo), note))


def elimina_incasso(did, iid):
    with conn() as c:
        c.execute("DELETE FROM incassi WHERE id = ? AND documento_id = ?", (iid, did))


def elimina_incassi(did):
    with conn() as c:
        c.execute("DELETE FROM incassi WHERE documento_id = ?", (did,))


def aggiorna_documento(did, **campi):
    with conn() as c:
        c.execute(f"UPDATE documenti SET {', '.join(k + ' = ?' for k in campi)} WHERE id = ?",
                  (*campi.values(), did))


def elimina_documento(did):
    with conn() as c:
        c.execute("DELETE FROM documenti WHERE id = ? AND stato = 'bozza'", (did,))
