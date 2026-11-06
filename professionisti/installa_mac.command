#!/bin/bash
# Installazione sul Mac (una volta sola): librerie, icona nel Dock e in Applicazioni.
cd "$(dirname "$0")"
CARTELLA="$(pwd)"
exec > >(tee installa.log) 2>&1                   # tutto quello che appare va anche in installa.log
echo "macOS $(sw_vers -productVersion) - $(date)"
export PATH="/Library/Frameworks/Python.framework/Versions/Current/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

if ! python3 -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null; then
  echo "Manca Python 3 su questo Mac."
  echo "Si apre la pagina di python.org: scarica 'macOS 64-bit universal2 installer', installalo,"
  echo "poi fai di nuovo doppio clic su installa_mac.command."
  open "https://www.python.org/downloads/macos/"
  read -r -p "Premi Invio per chiudere"
  exit 1
fi

# Python di python.org: senza i certificati non si collega alla PEC (SSL). Lo script ufficiale li installa.
for f in /Applications/Python\ 3.*/Install\ Certificates.command; do
  [ -f "$f" ] && { echo "0/3  Certificati di Python..."; bash "$f" >/dev/null 2>&1; }
done

echo "1/3  Librerie..."
python3 -m pip install --user --quiet -r requirements.txt || { echo "Installazione librerie non riuscita."; read -r -p "Invio per chiudere"; exit 1; }

NOME=$(python3 -c "import config_studio as C; print(getattr(C, 'NOME_APP', 'Fatture'))")
if [ -w /Applications ]; then DEST=/Applications; else DEST="$HOME/Applications"; mkdir -p "$DEST"; fi
rm -rf "$HOME/Applications/$NOME.app"            # eventuale versione precedente
APP="$DEST/$NOME.app"
echo "2/3  Programma '$NOME' in $DEST..."
chmod +x avvia_sfondo.sh avvia.command
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script quoted form of \"$CARTELLA/avvia_sfondo.sh\" & \" > /dev/null 2>&1 &\""
if [ -f static/icona.png ]; then
  T=$(mktemp -d); mkdir "$T/icona.iconset"
  for s in 16 32 128 256 512; do
    sips -z $s $s static/icona.png --out "$T/icona.iconset/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) static/icona.png --out "$T/icona.iconset/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$T/icona.iconset" -o "$APP/Contents/Resources/applet.icns"
  # Dai macOS recenti l'icona dell'app sta in Assets.car e applet.icns viene ignorato (icona bianca):
  # si toglie Assets.car e si indica applet.icns nell'Info.plist, poi si rifirma l'app (firma locale).
  rm -f "$APP/Contents/Resources/Assets.car"
  PL="$APP/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$PL" 2>/dev/null
  /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile applet" "$PL" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string applet" "$PL"
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1
  touch "$APP"
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null
fi

echo "   controllo: $APP"
ls -la "$APP/Contents/Resources" 2>&1 | sed 's/^/     /'
/usr/libexec/PlistBuddy -c "Print :CFBundleIconFile" "$APP/Contents/Info.plist" 2>&1 | sed 's/^/     icona: /'
codesign --verify "$APP" 2>&1 && echo "     firma: ok"

echo "3/3  Icona nel Dock..."
APP="$APP" NOME="$NOME" python3 - <<'PY'
import os, plistlib, subprocess, urllib.parse
app, nome = os.environ["APP"], os.environ["NOME"]
dock = plistlib.loads(subprocess.run(["defaults", "export", "com.apple.dock", "-"], capture_output=True).stdout)
url = "file://" + urllib.parse.quote(app) + "/"
apps = [t for t in dock.get("persistent-apps", [])
        if nome + ".app" not in urllib.parse.unquote(t.get("tile-data", {}).get("file-data", {}).get("_CFURLString", ""))]
apps.append({"tile-data": {"file-data": {"_CFURLString": url, "_CFURLStringType": 15}, "file-label": nome},
             "tile-type": "file-tile"})
dock["persistent-apps"] = apps
subprocess.run(["defaults", "import", "com.apple.dock", "-"], input=plistlib.dumps(dock), check=True)
PY
killall Dock
echo
echo "Fatto. Da ora si apre con l'icona '$NOME' nel Dock (o da $DEST)."
read -r -p "Premi Invio per chiudere"
