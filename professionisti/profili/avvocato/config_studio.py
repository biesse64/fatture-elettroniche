"""
Configurazione dello Studio Legale Margherita Pellecchi: unica fonte di verita'.

Dati del cedente, regole fiscali (forfettario, Cassa Forense, bollo, anticipazioni),
testi fissi del PDF e percorsi. Gli altri moduli leggono da qui e non contengono
valori scritti a mano. I dati modificabili dall'utente (es. IBAN) si cambiano anche
dalla pagina Impostazioni, che li salva nel database e prevalgono su questi.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATI = BASE / "dati"                 # database e documenti generati
DB_PATH = DATI / "studio.db"
USCITA = DATI / "uscita"             # uscita/<anno>/ con XML e PDF; anteprime in uscita/anteprime/
LOGO = BASE / "static" / "logo_studio.png"
NOME_APP = "Fatture Studio"                 # nome dell'icona nel Dock
PORTA = 5077

# ---------------------------------------------------------------- cedente
STUDIO = {
    "intestazione": "Studio Legale Margherita Pellecchi",
    "titolo": "Avv.",
    "nome": "Margherita",
    "cognome": "Pellecchi",
    "cf": "PLLMGH67P55G337Y",
    "piva": "01808540205",
    "regime_fiscale": "RF19",                     # forfettario
    "indirizzo": "Str. Privata Ville I.C.I.P., 10",
    "cap": "46100",
    "comune": "Mantova",
    "provincia": "MN",
    "telefono": "+39 0376 225751",
    "email": "info@studiolegalemargheritapellecchi.it",
    "pec": "margherita.pellecchi@mantova.pecavvocati.it",
    "web": "https://studiolegalemargheritapellecchi.it",
    "albo": "Ordine degli Avvocati di Mantova",
    "provincia_albo": "MN",
    "numero_albo": "",                            # facoltativo: da completare
    "data_albo": "",                              # AAAA-MM-GG, facoltativo
    "banca": "Banco BPM - Banca Popolare di Verona",
    "iban": "IT58I0503411501000000000111",
}

# ---------------------------------------------------------------- regole fiscali
NATURA_FORFETTARIO = "N2.2"
RIF_FORFETTARIO = "Art.1 c.54-89 L.190/2014 Reg. forfettario"

CASSA = {"tipo": "TC01", "aliquota_perc": "4", "descrizione": "Contrib. previd."}   # Cassa Forense

# Bollo: riga "bollo" da 2 euro addebitata al cliente, soggetta a cassa (prassi dello
# studio confermata dal commercialista), e bollo virtuale dichiarato nell'XML.
BOLLO = {"importo": "2.00", "soglia": "77.47", "descrizione": "bollo", "soggetto_cassa": True}

# Anticipazioni (es. contributo unificato): escluse dalla cassa, riepilogo separato nel PDF.
# Natura come in Easyfatt ("FC Fuori campo IVA" -> N2.2); in alternativa N1 "Escluso art. 15".
ANTICIPAZIONI = {"natura": "N2.2", "rif_norm": "Fuori campo IVA",
                 "etichetta": "Anticipazioni spese escluse"}
ANTICIPAZIONI_TIPICHE = ["Contributo unificato", "Marca da bollo per iscrizione a ruolo",
                         "Spese di notifica", "Diritti di copia"]

PAGAMENTO = {"modalita": "MP05", "descrizione": "Bonifico vista fattura"}

# Numero nella fattura elettronica: come Easyfatt per lo studio, solo il numero ("59"), senza l'anno.
NUMERO_XML_CON_ANNO = False

# ---------------------------------------------------------------- testi fissi del PDF
TESTO_RITENUTA = ("Il compenso non è soggetto a ritenuta d'acconto ai sensi della legge 190 "
                  "del 23/12/2014 art. 1 comma 67.")
TESTO_PRIVATI = "Copia della fattura elettronica è disponibile nella Sua area riservata dell'Agenzia delle Entrate."
TESTO_TERZO = "Il pagamento verrà effettuato da {terzo} terza solvente."
TESTO_BOLLO = "Imposta di bollo assolta in modo virtuale ai sensi dell'art. 6 D.M. 17/06/2014."
TESTO_PRIVACY = ("Nel rispetto della normativa vigente, ivi incluso D.Lgs. 196/03 e Reg. UE 2016/679, informiamo "
                 "che i Vs. dati saranno utilizzati ai soli fini connessi ai rapporti professionali in essere.")

PORTALE_ADE = "https://ivaservizi.agenziaentrate.gov.it/portale/"

# ---------------------------------------------------------------- invio allo SDI via PEC
PEC = {"indirizzo": "margherita.pellecchi@mantova.pecavvocati.it",
       "utente": "margherita.pellecchi@mantova.pecavvocati.it",
       "smtp_server": "pro-smtps.sicurezzapostale.it", "smtp_porta": 465,
       "imap_server": "pro-imaps.sicurezzapostale.it", "imap_porta": 993}


STATI = {
    "bozza": "Bozza",
    "generata": "Pronta da inviare",
    "inviata": "Inviata, in attesa di esito",
    "consegnata": "Consegnata",
    "mancata": "Consegnata (cassetto fiscale)",       # ricevuta MC: per i privati e' l'esito normale
    "scartata": "Scartata",
    "convertito": "Pagato, fattura creata",       # avviso di fattura trasformato in fattura
}
