# Modifiche

## 1.0 — 6 novembre 2026

Prima versione nel repository: il codice in uso sui Mac a questa data.

Funzioni principali presenti:
- fatture e note di credito FatturaPA, controlli fiscali, validazione XSD, copia PDF di cortesia;
- invio allo SDI via PEC con lettura degli esiti; primo invio a sdi01 e indirizzo dedicato
  appreso dalla prima ricevuta; invio multiplo;
- «Consegnata (cassetto fiscale)» per le ricevute di impossibilità di recapito (privati, esteri);
- numeri fuori sequenza (66/A, 66 bis) con avviso sulle date;
- PDF anche per le fatture importate (ricostruito dall'XML originale);
- totali dell'anno in Documenti, con base del contributo e, per Ing, netto dopo le ritenute;
- Ing: ritenuta disattivabile per i privati, voci di vendita beni/software (IVA 22%, senza
  Inarcassa né ritenuta);
- XML e PDF in `dati/uscita/<anno>/<mm-mese>/`; i file spostati a mano vengono ritrovati per nome;
- grassetto ed elenchi puntati nelle descrizioni e nelle note (solo nel PDF; allo SDI testo semplice);
- import da Easyfatt (DefXml, Excel) e dai file XML; reimport di una fattura inviata (`--inviata`);
- Consept: codici IVA, pagamenti, più banche, fatture in USD, bozze dal foglio presenze.
