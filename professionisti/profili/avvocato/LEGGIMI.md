# Fatture dello Studio Legale

Programma locale per emettere fatture e note di credito elettroniche dello studio
(regime forfettario, contributo Cassa Forense 4%, bollo, anticipazioni). Si usa nel browser,
ma gira solo sul Mac: i dati non vanno su internet.

## Prima volta (la fa Bruno)
1. Copia la cartella dove vuoi tenerla (es. Documenti/Fatture studio).
2. Serve Python 3: da Terminale `python3 --version`; se il Mac propone di installare gli
   strumenti per sviluppatori, accetta.
3. Il Mac blocca `avvia.command` perché è stato scaricato da internet ("Apple non è in grado di
   verificare..."): premi **Fine**, non "Sposta nel Cestino". Poi, una volta sola, da Terminale:
   ```
   xattr -dr com.apple.quarantine "percorso/della/cartella"
   ```
   (scrivi `xattr -dr com.apple.quarantine ` e trascina la cartella nella finestra del Terminale).
   In alternativa: Impostazioni di Sistema > Privacy e sicurezza > in fondo "Apri comunque".
   Al primo avvio installa da solo le librerie.
4. In **Impostazioni**: numero da cui ripartire nel 2026 (l'ultimo di Easyfatt + 1), IBAN, numero albo.

## Import da Easyfatt (una volta, a programma chiuso)
Da Easyfatt: clienti esportati in Excel, documenti dell'anno esportati in formato Easyfatt-Xml. Poi:
```
cd cartella-del-programma
python3 -m pip install --user openpyxl        (solo la prima volta)
python3 importa_easyfatt.py Clienti.xlsx Documenti.DefXml
```
Con `--prova` controlla senza scrivere. Si può rilanciare: quello che c'è già viene saltato.
I documenti entrano come "Consegnata" con lo stato saldata/da incassare di Easyfatt; lo script
ricalcola ogni totale e segnala quelli diversi da Easyfatt. Il prossimo numero riparte dall'ultimo importato.

## Uso
Doppio clic su `avvia.command`: si apre il browser su http://127.0.0.1:5077.
Per chiudere il programma basta chiudere la finestra del Terminale.

1. **Nuova fattura**: cliente (o Nuovo cliente), voci di onorario, eventuali anticipazioni
   (contributo unificato ecc.), compagnia che paga se è un sinistro.
   Il riepilogo si aggiorna mentre scrivi. **Calcola dal totale** ricava l'onorario da un totale tondo.
2. **Anteprima PDF** per controllare, poi **Genera fattura**: crea l'XML e la copia PDF.
3. **Mostra il file XML nel Finder** e **Apri il portale**: su Fatture e Corrispettivi, con lo SPID,
   Fatture elettroniche > Trasmissione, carica il file. Poi **Ho caricato il file**.
4. Quando lo SDI risponde (Monitoraggio delle fatture) registra l'esito:
   - Consegnata o Mancata consegna: la fattura è emessa. Manda il PDF al cliente.
   - Scartata: **Correggi**, sistema e genera di nuovo (stesso numero, nuovo file XML).
5. **Crea nota di credito** dalla pagina di una fattura consegnata: riprende cliente e voci.

Se ti accorgi di un errore dopo aver generato ma PRIMA di caricare sul portale:
**Torna in bozza per correggere**.

## Dove sono i dati
Tutto nella cartella `dati/`: `studio.db` (clienti e documenti) e `uscita/<anno>/` (XML e PDF).
Per una copia di sicurezza basta copiare la cartella `dati`.

## File
| File | A cosa serve |
|---|---|
| `avvia.command` | avvio con doppio clic |
| `app_studio.py` | il programma (pagine e azioni) |
| `config_studio.py` | dati dello studio e regole fiscali (unico punto da modificare) |
| `calcoli_studio.py` | onorari, bollo, contributo 4%, anticipazioni, calcolo dal totale |
| `db_studio.py` | archivio clienti e documenti |
| `pdf_studio.py` | copia di cortesia PDF |
| `fatturapa_core.py` + `xsd/` | XML FatturaPA validato sullo schema ufficiale (stesso motore di Consept) |
| `importa_easyfatt.py` | import di clienti e documenti da Easyfatt |
| `templates/`, `static/` | pagine, stile e logo |

## Non ancora fatto
Applicazione Mac vera e propria (icona nel Dock).
