#!/usr/bin/env bash
# Désinstalle crescendo sur Linux : services, raccourcis GNOME, whisper.cpp compilé, modèles, historique.
#   scripts/uninstall-linux.sh            (Ollama et les paquets système sont conservés)
#   scripts/uninstall-linux.sh --ollama   supprime aussi le modèle de nettoyage d'Ollama
set -uo pipefail
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
step() { printf '\033[36m==>\033[0m %s\n' "$*"; }

step "Services systemd utilisateur"
for unit in crescendo.service crescendo-whisper.service; do
  systemctl --user disable --now "$unit" 2>/dev/null
  rm -f "$HOME/.config/systemd/user/$unit"
done
systemctl --user daemon-reload 2>/dev/null
pkill -f "voice-dictation/whisper.cpp/build/bin/whisper-server" 2>/dev/null
pkill -f "frontends/linux/dictation_daemon.py" 2>/dev/null

if command -v gsettings >/dev/null && gsettings list-schemas 2>/dev/null | grep -qx org.gnome.settings-daemon.plugins.media-keys; then
  step "Raccourcis GNOME"
  BASE=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
  current=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)
  updated=$(python3 - "$current" "$BASE" <<'PY'
import ast, sys
cur, base = sys.argv[1], sys.argv[2]
items = [] if cur.startswith("@as") else ast.literal_eval(cur)
print(str([i for i in items if i not in (f"{base}/crescendo/", f"{base}/crescendo-enter/")]))
PY
)
  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$updated"
  for id in crescendo crescendo-enter; do
    gsettings reset-recursively "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE/$id/" 2>/dev/null
  done
fi

if [[ "${1:-}" == --ollama ]] && command -v ollama >/dev/null; then
  step "Modèle Ollama"
  ollama rm "$(python3 "$REPO/bin/dictate" config --get cleanup.model)"
fi

step "Données : whisper.cpp, modèles, historique, audio"
rm -rf "$HOME/.local/share/voice-dictation"

cat <<EOT

Désinstallation terminée. Restent en place :
  - Ollama (désinstallation : https://github.com/ollama/ollama/blob/main/docs/linux.md#uninstall)
  - les paquets système installés (cmake, xclip, xdotool…)
  - le dépôt : rm -rf "$REPO"
EOT
