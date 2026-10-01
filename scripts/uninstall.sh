#!/bin/zsh
# Désinstallation complète de la dictée vocale.
#   scripts/uninstall.sh            services, config Hammerspoon, données et modèles
#   scripts/uninstall.sh --brew     + désinstalle whisper.cpp, sox, ollama (et ses modèles), Hammerspoon
# Le dépôt lui-même n'est pas supprimé : `rm -rf` le dossier ensuite si vous le souhaitez.
set -uo pipefail

REPO=${0:A:h:h}
UID_=$(id -u)
step() { print -P "%F{cyan}==>%f $*"; }

step "Arrêt et suppression des services"
for label in com.voice-dictation.whisper com.voice-dictation.ollama; do
  launchctl bootout "gui/$UID_/$label" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done

step "Retrait du bloc voice-dictation de ~/.hammerspoon/init.lua"
if [[ -f ~/.hammerspoon/init.lua ]]; then
  /opt/homebrew/bin/python3 - ~/.hammerspoon/init.lua <<'EOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
s = re.sub(r"\n?-- >>> voice-dictation >>>.*?-- <<< voice-dictation <<<\n?", "\n", s, flags=re.S)
open(p, "w").write(s.strip("\n") + ("\n" if s.strip() else ""))
EOF
  pgrep -xq Hammerspoon && /opt/homebrew/bin/hs -t 5 -c "hs.timer.doAfter(0.2, hs.reload)" >/dev/null 2>&1
fi

step "Suppression des données (historique, audio, logs, modèles Whisper)"
rm -rf "$HOME/.local/share/voice-dictation"

if [[ "${1:-}" == "--brew" ]]; then
  step "Désinstallation des paquets Homebrew et des modèles Ollama"
  pkill -x Hammerspoon 2>/dev/null
  # Modèles téléchargés pour ce projet uniquement (les autres modèles Ollama éventuels sont conservés).
  (/opt/homebrew/bin/ollama serve >/dev/null 2>&1 &) ; sleep 2
  for m in qwen2.5:3b-instruct llama3.2:3b qwen3:4b-instruct-2507-q4_K_M gemma3:4b qwen2.5:1.5b-instruct; do
    /opt/homebrew/bin/ollama rm $m 2>/dev/null && echo "  modèle supprimé : $m"
  done
  remaining=$(/opt/homebrew/bin/ollama list 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')
  pkill -f "ollama serve" 2>/dev/null
  if [[ "$remaining" == 0 ]]; then rm -rf ~/.ollama; else echo "  ~/.ollama conservé ($remaining autres modèles)"; fi
  brew uninstall --cask hammerspoon
  brew uninstall whisper.cpp sox ollama
  # Config Hammerspoon supprimée seulement si elle ne contient plus rien d'autre que notre bloc (retiré).
  if [[ -z "$(tr -d '[:space:]' < ~/.hammerspoon/init.lua 2>/dev/null)" ]]; then rm -rf ~/.hammerspoon; fi
  rm -f ~/Library/Preferences/org.hammerspoon.Hammerspoon.plist
fi

cat <<EOF

Désinstallation terminée. Reste éventuellement à faire à la main :
  - Réglages Système ▸ Confidentialité et sécurité ▸ Accessibilité / Micro : retirer Hammerspoon
  - Réglages Système ▸ Général ▸ Ouverture : retirer Hammerspoon des éléments d'ouverture
  - Supprimer le dépôt : rm -rf "$REPO"
EOF
