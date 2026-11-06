#!/bin/bash
# Avvio senza finestra del Terminale: lo usa l'icona nel Dock creata da installa_mac.command.
cd "$(dirname "$0")"
export PATH="/Library/Frameworks/Python.framework/Versions/Current/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
PORTA=$(python3 -c "import config_studio as C; print(C.PORTA)")
if curl -s -o /dev/null "http://127.0.0.1:$PORTA/"; then
  open "http://127.0.0.1:$PORTA/"          # gia' aperto: riapre solo la pagina
  exit 0
fi
mkdir -p dati
nohup python3 app_studio.py >> dati/programma.log 2>&1 &
