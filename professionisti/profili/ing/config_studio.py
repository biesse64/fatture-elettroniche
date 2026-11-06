"""
Configurazione di Ing. Bruno Stefanutti: unica fonte di verita'.

Regime ordinario: IVA 22% su onorari e contributo Inarcassa 4%, ritenuta d'acconto 20%
sugli onorari, niente bollo (lo gestisce il commercialista). Stessi moduli del programma
dello Studio Legale: cambia solo questo file (e il logo).
"""
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATI = BASE / "dati"                 # database e documenti generati
DB_PATH = DATI / "studio.db"
USCITA = DATI / "uscita"             # uscita/<anno>/ con XML e PDF; anteprime in uscita/anteprime/
LOGO = BASE / "static" / "logo_studio.png"   # facoltativo: senza logo il PDF usa solo il nome
NOME_APP = "Fatture Ing"                 # nome dell'icona nel Dock
PORTA = 5078                         # diversa da quella dello Studio Legale (5077)

# ---------------------------------------------------------------- cedente
STUDIO = {
    "intestazione": "Dott. Ing. Bruno Stefanutti",
    "titolo": "Ing.",
    "nome": "Bruno",
    "cognome": "Stefanutti",
    "cf": "STFBRN64T19L736L",
    "piva": "03416470270",
    "regime_fiscale": "RF01",                     # ordinario
    "indirizzo": "Via Sandro Gallo 161",
    "cap": "30126",
    "comune": "Lido di Venezia",
    "provincia": "VE",
    "telefono": "+39 041 5265203",
    "email": "bruno.stefanutti@consept.it",
    "pec": "bruno.stefanutti@ingpec.eu",
    "web": "",
    "albo": "Ordine degli Ingegneri della Provincia di Venezia",
    "provincia_albo": "VE",
    "numero_albo": "2359",
    "data_albo": "",                              # AAAA-MM-GG, facoltativo
    "banca": "Banca Fineco",
    "iban": "IT58Q0301503200000003259287",
}

# ---------------------------------------------------------------- regole fiscali
IVA_PERC = "22"
NATURA_RIGHE = None                  # righe imponibili: nessuna natura
RIF_RIGHE = ""
RIF_FORFETTARIO = ""                 # non usato: regime ordinario

CASSA = {"tipo": "TC04", "aliquota_perc": "4", "descrizione": "Contributo Inarcassa"}

RITENUTA = {"tipo": "RT01", "aliquota_perc": "20", "causale": "A",
            "descrizione": "Ritenuta d'acconto"}

BOLLO = None                         # non addebitato in fattura

# Anticipazioni in nome e per conto del cliente (art. 15): per ora non usate, restano possibili.
ANTICIPAZIONI = {"natura": "N1", "rif_norm": "Escluse ex art. 15 DPR 633/72",
                 "etichetta": "Spese anticipate escluse art. 15"}
ANTICIPAZIONI_TIPICHE = []

PAGAMENTO = {"modalita": "MP05", "descrizione": "Bonifico"}

NUMERO_XML_CON_ANNO = False          # come le fatture gia' emesse: "5"

# Parti del modulo da mostrare (quelle dello Studio Legale non servono qui)
MOSTRA_ANTICIPAZIONI = False
MOSTRA_TERZO_PAGATORE = False
MOSTRA_QUANTITA = True             # ore x tariffa
# Vendite di beni o software (hardware, licenze) fuori dall'attivita' professionale:
# IVA 22%, ma niente contributo Inarcassa e niente ritenuta d'acconto.
MOSTRA_VENDITE = True

# ---------------------------------------------------------------- testi fissi del PDF
TESTO_RITENUTA = ""
TESTO_PRIVATI = "Copia della fattura elettronica è disponibile nella Sua area riservata dell'Agenzia delle Entrate."
TESTO_TERZO = "Il pagamento verrà effettuato da {terzo}."
TESTO_BOLLO = ""
TESTO_PRIVACY = ("Nel rispetto della normativa vigente, ivi incluso D.Lgs. 196/03 e Reg. UE 2016/679, informiamo "
                 "che i Vs. dati saranno utilizzati ai soli fini connessi ai rapporti professionali in essere.")

PORTALE_ADE = "https://ivaservizi.agenziaentrate.gov.it/portale/"

# ---------------------------------------------------------------- invio allo SDI via PEC
PEC = {"indirizzo": "bruno.stefanutti@ingpec.eu",
       "utente": "bruno.stefanutti@ingpec.eu",
       "smtp_server": "smtps.pec.aruba.it", "smtp_porta": 465,
       "imap_server": "imaps.pec.aruba.it", "imap_porta": 993}


STATI = {
    "bozza": "Bozza",
    "generata": "Pronta da inviare",
    "inviata": "Inviata, in attesa di esito",
    "consegnata": "Consegnata",
    "mancata": "Consegnata (cassetto fiscale)",       # ricevuta MC: per i privati e' l'esito normale
    "scartata": "Scartata",
    "convertito": "Pagato, fattura creata",       # avviso di fattura trasformato in fattura
}
