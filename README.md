# Fatture elettroniche

Programmi locali (Flask + SQLite, sul Mac) per emettere fatture e note di credito FatturaPA
e inviarle allo SDI via PEC. Sostituiscono Danea Easyfatt per tre posizioni:

| Posizione | Regime | Cartella sul Mac | Porta |
|---|---|---|---|
| Studio Legale Avv. Margherita Pellecchi | forfettario RF19, Cassa Forense 4%, bollo | `fatture_consept/app` (e sul Mac dell'avvocata) | 5077 |
| Dott. Ing. Bruno Stefanutti | ordinario, IVA 22%, Inarcassa 4%, ritenuta 20% | `fatture_consept/fatture_ing` | 5078 |
| Consept S.a.s. | ordinario, più codici IVA, USD, più banche | `fatture_consept/consept_web` | 5079 |

## Struttura

```
professionisti/            codice comune ad avvocato e Ing
  profili/avvocato/        config_studio.py, LEGGIMI.md, icone e logo dell'avvocata
  profili/ing/             config_studio.py, LEGGIMI.md, icone di Ing
consept/                   programma Consept (codice proprio)
strumenti/prepara.sh       prepara la cartella installabile di una posizione
VERSIONE                   numero di versione corrente
```

Avvocato e Ing usano gli stessi file: cambiano solo `config_studio.py` (dati e regole fiscali) e
le immagini. Una modifica in `professionisti/` vale per entrambi.

## Cosa NON va nel repository

Mai: la cartella `dati/` (archivio `studio.db`, XML e PDF delle fatture, anteprime), export di
Easyfatt, ricevute, fogli Excel, `bozze_presenze.json`. Lo impedisce `.gitignore`, ma prima di ogni
commit si controlla comunque con `git status`. Le password PEC stanno nel Portachiavi del Mac,
non in nessun file. I `config_studio.py` contengono i dati anagrafici e l'IBAN dei titolari: per
questo il repository è **privato**.

## Preparare un'installazione o un aggiornamento

```
strumenti/prepara.sh avvocato      # oppure: ing, consept
```

Crea `out/fatture_<posizione>/` e lo zip `out/fatture_<posizione>-<versione>.zip` con il solo
programma. Per **aggiornare** un'installazione: chiudere il programma (Chiudi, in alto), copiare
tutto il contenuto sopra la cartella del programma, riaprire dal Dock. La cartella `dati/` non è
nello zip e non viene toccata.

Per una **prima installazione** valgono le istruzioni nel `LEGGIMI.md` di ogni posizione
(`installa_mac.command` crea l'app nel Dock).

## Versioni

Ogni modifica pubblicata alza `VERSIONE` e ha una riga in `CHANGELOG.md`; ogni cartella preparata
contiene il file `VERSIONE`, così si sa sempre cosa gira su ogni Mac.
