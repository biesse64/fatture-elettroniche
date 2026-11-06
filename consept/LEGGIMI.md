# Fatture Consept (versione web)

Programma delle fatture di Consept S.a.s., separato da quello dei professionisti (Studio Legale e
Ing. Stefanutti): è nato dalla stessa base ma ha aggiornamenti suoi.

## Stato

- **Clienti, codici IVA, pagamenti e banche**: importati dall'Excel e da Easyfatt, modificabili dal programma.
- **Storico** dal 2018 (elenco Easyfatt, solo totali) e fatture 20–23/2026 con le voci (dall'Excel).
- **Modulo fattura attivo**: IVA per riga (codice della riga, altrimenti del cliente, altrimenti 22),
  scadenze dalla condizione di pagamento, dichiarazione d'intento per N8c, clienti esteri (XXXXXXX),
  copia per il cliente in dollari, PDF allegato all'XML, invio allo SDI via PEC (sdi28).
- **Bollo virtuale**: opzione nelle Impostazioni, spenta (lo gestisce il commercialista).
- Per un mese conviene affiancarlo all'Excel e confrontare gli XML (`confronta_xml.py` del programma Excel).

## Fatture con copia in dollari

Spunta «Copia per il cliente in dollari», scrivi il cambio (1 USD = … EUR) e i prezzi in dollari: il prezzo
in euro si calcola dal cambio e si può correggere (ad esempio arrotondarlo). Generando si ottengono l'XML in
euro per lo SDI, la copia PDF in euro e la copia PDF in dollari con le coordinate Wise, con lo stesso numero.

## Installazione sul Mac (una volta sola)

Doppio clic su `installa_mac.command`: crea l'icona **Fatture Consept** nel Dock e in Applicazioni.
Il programma si apre nel browser all'indirizzo http://127.0.0.1:5079/.

La password della PEC è quella già salvata nel Portachiavi dal programma Excel: non va reinserita.

## Import dall'Excel (a programma chiuso, da Terminale nella cartella del programma)

```
python3 importa_excel.py ../fatture_consept/fatture_consept_2026.xlsx --prova
python3 importa_excel.py ../fatture_consept/fatture_consept_2026.xlsx
```

Importa codici IVA, clienti e fatture con le voci (rilanciabile: aggiorna, non cancella), l'indirizzo SDI
dedicato (sdi28) e il progressivo dei file XML già usati.

Dagli export di Easyfatt: `python3 importa_easyfatt.py codici_iva.xlsx` e
`python3 importa_easyfatt.py storico_fatture_tutte.xlsx`.

## Dove stanno i dati

`dati/studio.db` (archivio) e `dati/uscita/` (XML e PDF). Da salvare nei backup.

## Bozze dal foglio presenze (bozze_presenze.py)

Dal foglio presenze, pulsante **Genera bozze** (oppure da Terminale `python3 bozze_presenze.py --mese 10/2026`):
per ogni cliente con giornate nel mese crea una fattura in **bozza** nel programma, con data il primo del mese
dopo e una voce "Descrizione – mese" + elenco giornate (`08/10/2026 (G)`), quantità in giornate (g = 1, m/p = 0,5)
x tariffa. Poi le controlli, le generi e le invii dal programma come sempre. Il programma può restare aperto
(ricarica la pagina per vederle).
- Cliente, tariffa e descrizione per ogni cliente del foglio presenze: `bozze_presenze.json` (codice cliente
  del programma, tariffa, descrizione, `fatturare: false` per i clienti interni). Cliente vuoto = segnalato e saltato.
- Numerazione: primo numero libero dopo l'ultima fattura emessa, quindi il numero di una bozza eliminata viene riusato.
- Una bozza già creata per lo stesso cliente e mese non viene rifatta finché esiste; se la elimini, al giro dopo
  viene ricreata (per non fatturare un cliente quel mese: `fatturare: false`, oppure non rilanciare il mese).
- Prima di scrivere salva una copia dell'archivio in `dati/copie_bozze/`. `--prova` mostra cosa farebbe.
