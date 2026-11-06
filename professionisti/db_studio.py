"""Archivio SQLite dello studio: clienti, documenti (fatture e note di credito), righe, impostazioni."""
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
    codice TEXT DEFAULT '',                    -- codice cliente di Easyfatt (import)
    ritenuta INTEGER NOT NULL DEFAULT 1,       -- 1 = sostituto d'imposta: trattiene la ritenuta d'acconto
    creato_il TEXT
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
    ritenuta INTEGER NOT NULL DEFAULT 1,       -- 1 = applica la ritenuta d'acconto (se prevista)
    rif_numero TEXT DEFAULT '', rif_data TEXT DEFAULT '',
    stato TEXT NOT NULL DEFAULT 'bozza',
    progressivo TEXT DEFAULT '', file_xml TEXT DEFAULT '', file_pdf TEXT DEFAULT '',
    generato_il TEXT DEFAULT '', inviato_il TEXT DEFAULT '',
    id_sdi TEXT DEFAULT '', esito_il TEXT DEFAULT '', esito_note TEXT DEFAULT '',
    totale TEXT DEFAULT '',
    storico INTEGER NOT NULL DEFAULT 0,        -- 1 = importato da Easyfatt, gia' inviato
    saldato INTEGER NOT NULL DEFAULT 0,        -- 1 = pagamento ricevuto
    saldato_il TEXT DEFAULT '',                -- data del saldo (vuota se non nota)
    UNIQUE (anno, numero, suffisso)
);
CREATE TABLE IF NOT EXISTS righe (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES documenti(id) ON DELETE CASCADE,
    ordine INTEGER NOT NULL,
    tipo TEXT NOT NULL,                        -- onorario | anticipazione | vendita (beni, software)
    descrizione TEXT DEFAULT '',
    importo TEXT DEFAULT '',                   -- vuoto = riga solo descrittiva
    quantita TEXT DEFAULT '',                  -- facoltativi: ore x tariffa (importo = quantita x prezzo)
    um TEXT DEFAULT '',
    prezzo TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS impostazioni (chiave TEXT PRIMARY KEY, valore TEXT);
CREATE TABLE IF NOT EXISTS incassi (             -- pagamenti ricevuti: anche parziali (acconti)
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES documenti(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    importo TEXT NOT NULL,
    note TEXT DEFAULT ''
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
        if "netto" not in {r["name"] for r in c.execute("PRAGMA table_info(documenti)")}:
            c.execute("ALTER TABLE documenti ADD COLUMN netto TEXT DEFAULT ''")   # totale - ritenuta
        if "ritenuta" not in {r["name"] for r in c.execute("PRAGMA table_info(documenti)")}:
            c.execute("ALTER TABLE documenti ADD COLUMN ritenuta INTEGER NOT NULL DEFAULT 1")
        if "ritenuta" not in {r["name"] for r in c.execute("PRAGMA table_info(clienti)")}:
            c.execute("ALTER TABLE clienti ADD COLUMN ritenuta INTEGER NOT NULL DEFAULT 1")
            # i privati (codice fiscale di persona, senza partita IVA) non sono sostituti d'imposta
            c.execute("UPDATE clienti SET ritenuta = 0 WHERE TRIM(COALESCE(piva, '')) = '' "
                      "AND LENGTH(TRIM(COALESCE(cf, ''))) = 16")


def adesso():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- impostazioni
MODIFICABILI = ["iban", "banca", "numero_albo", "data_albo", "telefono", "email", "pec"]


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
                 "codice_destinatario", "pec", "email", "note", "ritenuta"]


def cliente_per_codice(codice):
    with conn() as c:
        return c.execute("SELECT * FROM clienti WHERE codice = ?", (codice,)).fetchone()


def clienti(cerca=""):
    with conn() as c:
        if cerca:
            q = f"%{cerca}%"
            return c.execute("SELECT * FROM clienti WHERE denominazione LIKE ? OR cf LIKE ? OR piva LIKE ? "
                             "ORDER BY denominazione COLLATE NOCASE", (q, q, q)).fetchall()
        return c.execute("SELECT * FROM clienti ORDER BY denominazione COLLATE NOCASE").fetchall()


def cliente(cid):
    with conn() as c:
        return c.execute("SELECT * FROM clienti WHERE id = ?", (cid,)).fetchone()


def salva_cliente(dati, cid=None):
    valori = [dati.get(k, 1 if k == "ritenuta" else "") for k in CAMPI_CLIENTE]
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
             "rif_numero", "rif_data", "ritenuta"]
PREDEFINITI_DOC = {"suffisso": "", "ritenuta": 1}


def salva_documento(dati, righe, did=None):
    """dati: campi di CAMPI_DOC; righe: lista di dict tipo/descrizione/importo."""
    valori = [dati.get(k, PREDEFINITI_DOC.get(k)) for k in CAMPI_DOC]
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
        for i, r in enumerate(righe):
            c.execute("INSERT INTO righe (documento_id, ordine, tipo, descrizione, importo, quantita, um, prezzo) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (did, i, r["tipo"], r["descrizione"], r["importo"], r.get("quantita", ""), r.get("um", ""),
                       r.get("prezzo", "")))
    return did


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
