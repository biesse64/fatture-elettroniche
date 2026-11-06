#!/bin/bash
# Doppio clic per aprire il programma delle fatture dello studio.
cd "$(dirname "$0")"
if ! python3 -c "import flask, lxml, reportlab, openpyxl, keyring" 2>/dev/null; then
  echo "Prima installazione delle librerie (serve solo la prima volta)..."
  python3 -m pip install --user -r requirements.txt || {
    echo "Installazione non riuscita: chiama Bruno."; read -r -p "Premi Invio per chiudere"; exit 1; }
fi
python3 app_studio.py
