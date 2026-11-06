#!/bin/bash
# Prepara la cartella del programma per una posizione, pronta da copiare o da mandare.
#
#   strumenti/prepara.sh avvocato     -> out/fatture_avvocato/      e out/fatture_avvocato-<versione>.zip
#   strumenti/prepara.sh ing          -> out/fatture_ing/           e out/fatture_ing-<versione>.zip
#   strumenti/prepara.sh consept      -> out/fatture_consept/       e out/fatture_consept-<versione>.zip
#
# Contiene solo il programma: niente dati. Per aggiornare un'installazione si copia tutto sopra la
# cartella esistente, a programma chiuso: la cartella dati/ non viene toccata.
set -euo pipefail
cd "$(dirname "$0")/.."
POS="${1:-}"
VER="$(cat VERSIONE)"
case "$POS" in
  avvocato|ing) SRC=professionisti; PROFILO="professionisti/profili/$POS" ;;
  consept)      SRC=consept;        PROFILO="" ;;
  *) echo "uso: $0 avvocato|ing|consept"; exit 1 ;;
esac
DEST="out/fatture_$POS"
rm -rf "$DEST" "out/fatture_$POS-$VER.zip"
mkdir -p "$DEST"
cp -R "$SRC/." "$DEST/"
rm -rf "$DEST/profili"
if [ -n "$PROFILO" ]; then
  cp -R "$PROFILO/." "$DEST/"
fi
find "$DEST" \( -name __pycache__ -o -name .DS_Store \) -prune -exec rm -rf {} +
echo "$VER" > "$DEST/VERSIONE"
chmod +x "$DEST"/*.command "$DEST"/*.sh
(cd out && zip -qr "fatture_$POS-$VER.zip" "fatture_$POS")
echo "pronto: $DEST  (zip: out/fatture_$POS-$VER.zip, versione $VER)"
