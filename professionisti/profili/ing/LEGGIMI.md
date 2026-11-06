# Fatture Dott. Ing. Bruno Stefanutti

Stesso programma dello Studio Legale, configurato per il regime ordinario:
IVA 22% su onorari e contributo Inarcassa 4% (TC04), ritenuta d'acconto 20% sugli onorari,
niente bollo. Quantità × prezzo per le attività a ore. Gira su http://127.0.0.1:5078
(lo Studio Legale usa la 5077: possono essere aperti insieme).

## Prima volta
1. Sblocca la cartella: `xattr -dr com.apple.quarantine fatture_ing`
2. Doppio clic su `avvia.command`.
3. In **Impostazioni**: "Prima fattura emessa con questo programma" = **6** (le 1-5 sono state emesse con InfoSvil).

## Uso
Come lo Studio Legale: Nuova fattura → Anteprima PDF → Genera → invio allo SDI → esito.
"Calcola da" ricava l'onorario dal totale documento oppure dal netto a pagare.

## File
Uguali a quelli dello Studio Legale, tranne `config_studio.py` (i tuoi dati e le regole fiscali).
