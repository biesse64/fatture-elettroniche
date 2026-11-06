"""
Configurazione di Consept S.a.s.: unica fonte di verita'.

Programma separato da quello dei professionisti (Studio Legale e Ing. Stefanutti): nato dalla stessa
base, ha i suoi aggiornamenti. Societa' in regime ordinario: IVA per riga secondo i codici IVA
(22%, non soggette art. 7-ter, non imponibili con dichiarazione d'intento, escluse art. 15),
clienti italiani ed esteri, niente cassa ne' ritenuta. Bollo virtuale indicato nell'XML quando
dovuto, non addebitato al cliente (lo versa il commercialista).
"""
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATI = BASE / "dati"                 # database e documenti generati
DB_PATH = DATI / "studio.db"
USCITA = DATI / "uscita"             # uscita/<anno>/ con XML e PDF; anteprime in uscita/anteprime/
LOGO = BASE / "static" / "logo_studio.png"   # intestazione del PDF
NOME_APP = "Fatture Consept"         # nome dell'icona nel Dock
PORTA = 5079                         # Studio Legale 5077, Ing 5078

FATTURE_IN_PREPARAZIONE = False      # passo 2 completato: il modulo fattura è attivo

AZIENDA = True                       # cedente societa': Denominazione e REA, non nome/cognome/albo

# ---------------------------------------------------------------- cedente
STUDIO = {
    "intestazione": "Consept S.a.s.",
    "denominazione": "Consept S.a.s di Ing. Bruno Stefanutti&C.",   # come nelle fatture gia' emesse
    "cf": "04089410288",
    "piva": "04089410288",
    "regime_fiscale": "RF01",                     # ordinario
    "indirizzo": "Via Bachelet 20",
    "cap": "35010",
    "comune": "Limena",
    "provincia": "PD",
    "telefono": "+39 049 8841887",
    "email": "info@consept.it",
    "pec": "info@pec.consept.it",
    "web": "www.consept.it",
    "rea_ufficio": "PD",
    "rea_numero": "361003",
    "banca": "Banca Intesa San Paolo - Filiale Limena",
    "iban": "IT46Y0306962619100000000631",
    # campi dei professionisti, non usati da una societa'
    "titolo": "", "nome": "", "cognome": "",
    "albo": "", "provincia_albo": "", "numero_albo": "", "data_albo": "",
}

# ---------------------------------------------------------------- regole fiscali
# L'IVA di ogni riga viene dal suo codice IVA (tabella "Codici IVA", modificabile dal programma);
# se la riga non ne ha uno, vale quello predefinito del cliente, poi questo.
CODICE_IVA_PREDEFINITO = "22"
IVA_PERC = "22"                      # aliquota del codice predefinito
NATURA_RIGHE = None
RIF_RIGHE = ""
RIF_FORFETTARIO = ""

CASSA = None                         # societa': nessuna cassa previdenziale
RITENUTA = None                      # nessuna ritenuta d'acconto

# Bollo: indicato nell'XML (BolloVirtuale SI) se le operazioni senza IVA superano la soglia,
# ma non addebitato in fattura. Le nature soggette vengono dai codici IVA con "bollo" = si.
BOLLO = {"soglia": "77.47", "importo": "2.00", "addebita": False, "descrizione": "Imposta di bollo"}

ANTICIPAZIONI = {"natura": "N1", "rif_norm": "Escluso art. 15 DPR 633/72",
                 "etichetta": "Spese escluse art. 15"}
ANTICIPAZIONI_TIPICHE = []

PAGAMENTO = {"modalita": "MP05", "descrizione": "Bonifico"}
PAGAMENTO_PREDEFINITO = "Bonifico vista fattura"     # se il cliente non ne ha uno suo

ALLEGA_PDF = True                    # la copia PDF va anche dentro l'XML, come nel programma Excel

NUMERO_XML_CON_ANNO = True           # come Easyfatt per Consept: "23/2026"

# Parti del modulo da mostrare
MOSTRA_ANTICIPAZIONI = False
MOSTRA_TERZO_PAGATORE = False
MOSTRA_QUANTITA = True               # quantita' x prezzo

# ---------------------------------------------------------------- testi fissi del PDF
TESTO_RITENUTA = ""
TESTO_PRIVATI = "Copia della fattura elettronica è disponibile nella Sua area riservata dell'Agenzia delle Entrate."
TESTO_TERZO = "Il pagamento verrà effettuato da {terzo}."
TESTO_BOLLO = "Imposta di bollo assolta in modo virtuale ai sensi del D.M. 17/06/2014."
TESTO_PRIVACY = ("Nel rispetto della normativa vigente, ivi incluso D.Lgs. 196/03 e Reg. UE 2016/679, informiamo "
                 "che i Vs. dati saranno utilizzati ai soli fini connessi ai rapporti commerciali in essere.")

PORTALE_ADE = "https://ivaservizi.agenziaentrate.gov.it/portale/"

# ---------------------------------------------------------------- invio allo SDI via PEC
# La password e' la stessa gia' salvata nel Portachiavi dal programma Excel (servizio "fatture-pec").
PEC = {"indirizzo": "info@pec.consept.it",
       "utente": "info@pec.consept.it",
       "smtp_server": "server.pec-email.com", "smtp_porta": 465,
       "imap_server": "imap.pec-email.com", "imap_porta": 993}


STATI = {
    "bozza": "Bozza",
    "generata": "Pronta da inviare",
    "inviata": "Inviata, in attesa di esito",
    "consegnata": "Consegnata",
    "mancata": "Consegnata (cassetto fiscale)",       # ricevuta MC: per i privati e' l'esito normale
    "scartata": "Scartata",
    "convertito": "Pagato, fattura creata",       # avviso di fattura trasformato in fattura
}
