#!/bin/bash
# Test d'insertion réel sous X11 (utilisé par la CI Ubuntu, sous Xvfb + openbox) :
# un xterm exécute `cat > fichier`, le Paster du démon Linux y colle un texte accentué puis Entrée,
# puis on vérifie le fichier et la restauration du presse-papiers.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=$(mktemp)
# xterm ne colle pas le presse-papiers avec Ctrl+Maj+V par défaut : on l'y configure.
xterm -class DictTest -xrm 'DictTest*VT100.translations: #override Ctrl Shift <Key>V: insert-selection(CLIPBOARD)' \
      -e bash -c "cat > $OUT" &
XTERM=$!
trap 'kill $XTERM 2>/dev/null || true' EXIT
WID=$(timeout 15 xdotool search --sync --class DictTest | head -1)
xdotool windowactivate --sync "$WID"
ACTIVE=$(xdotool getactivewindow)
[ "$ACTIVE" = "$WID" ] || { echo "ÉCHEC : la fenêtre de test n'a pas le focus ($ACTIVE ≠ $WID)"; exit 1; }
printf 'ancien contenu' | xclip -selection clipboard -i
timeout 30 python3 - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("d", "frontends/linux/dictation_daemon.py")
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
p = d.Paster()
cls = p.active_class()
print("fenêtre active :", cls, "→", d.paste_keys(cls))
assert d.paste_keys(cls) == "ctrl+shift+v", "xterm doit être reconnu comme terminal"
p("Déploie ça sur GitHub, s'il te plaît.", True)
PY
sleep 0.5
echo "après collage : xterm $(kill -0 $XTERM 2>/dev/null && echo vivant || echo terminé), fichier = $(cat "$OUT")"
if kill -0 $XTERM 2>/dev/null; then
  xdotool key ctrl+d || true
  for _ in $(seq 1 25); do kill -0 $XTERM 2>/dev/null || break; sleep 0.2; done
fi
echo "fichier : $(cat "$OUT")"
echo "presse-papiers : $(xclip -selection clipboard -o)"
grep -qx "Déploie ça sur GitHub, s'il te plaît." "$OUT"
[ "$(xclip -selection clipboard -o)" = "ancien contenu" ]
echo "OK : texte inséré (avec Entrée) et presse-papiers restauré"
