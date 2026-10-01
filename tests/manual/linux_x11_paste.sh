#!/bin/bash
# Test d'insertion réel sous X11 (utilisé par la CI Ubuntu, sous Xvfb) :
# un xterm exécute `cat > fichier`, le Paster du démon Linux y colle un texte accentué,
# puis on vérifie le fichier et la restauration du presse-papiers.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=$(mktemp)
# xterm ne colle pas le presse-papiers avec Ctrl+Maj+V par défaut : on l'y configure.
xterm -xrm 'XTerm*VT100.translations: #override Ctrl Shift <Key>V: insert-selection(CLIPBOARD)' \
      -e bash -c "cat > $OUT" &
XTERM=$!
for _ in $(seq 1 50); do WID=$(xdotool search --pid $XTERM 2>/dev/null | head -1) && [ -n "$WID" ] && break; sleep 0.2; done
xdotool windowactivate --sync "$WID" 2>/dev/null || xdotool windowfocus --sync "$WID"
printf 'ancien contenu' | xclip -selection clipboard -i
python3 - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("d", "frontends/linux/dictation_daemon.py")
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
p = d.Paster()
print("fenêtre active :", p.active_class(), "→", d.paste_keys(p.active_class()))
p("Déploie ça sur GitHub, s'il te plaît.", True)
PY
sleep 0.5
xdotool key ctrl+d
wait $XTERM || true
echo "fichier : $(cat "$OUT")"
echo "presse-papiers : $(xclip -selection clipboard -o)"
grep -qx "Déploie ça sur GitHub, s'il te plaît." "$OUT"
[ "$(xclip -selection clipboard -o)" = "ancien contenu" ]
echo "OK : texte inséré (avec Entrée) et presse-papiers restauré"
