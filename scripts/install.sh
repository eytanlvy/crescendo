#!/bin/zsh
# Installe / met à jour la dictée vocale. Idempotent : relancer après avoir changé [whisper] model/threads
# ou [cleanup] model dans config.toml.
set -euo pipefail

REPO=${0:A:h:h}
DICTATE="$REPO/bin/dictate"
LA_DIR="$HOME/Library/LaunchAgents"
UID_=$(id -u)
step() { print -P "%F{cyan}==>%f $*"; }

step "Dépendances Homebrew"
for f in whisper.cpp sox ollama; do brew list --formula $f >/dev/null 2>&1 || brew install $f; done
brew list --cask hammerspoon >/dev/null 2>&1 || brew install --cask hammerspoon

step "Vocabulaire personnel"
if [[ ! -f "$REPO/vocabulary.txt" ]]; then
  cp "$REPO/vocabulary.example.txt" "$REPO/vocabulary.txt"
  echo "  vocabulary.txt créé à partir de l'exemple : complétez-le avec vos termes (non versionné)."
fi

conf() { "$DICTATE" config --json | /opt/homebrew/bin/python3 -c "import json,sys; c=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1"; }
DATA_DIR=$(conf 'c["paths"]["data_dir"]')
MODEL=$(conf 'c["whisper"]["model"]')
WHISPER_PORT=$(conf 'c["whisper"]["url"].rsplit(":",1)[1].strip("/")')
THREADS=$(conf 'c["whisper"]["threads"]')
LLM=$(conf 'c["cleanup"]["model"]')
mkdir -p "$DATA_DIR/logs" "${MODEL:h}"

step "Modèle Whisper : ${MODEL:t}"
if [[ ! -s "$MODEL" ]]; then
  curl -fL --progress-bar -o "$MODEL.part" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${MODEL:t}"
  mv "$MODEL.part" "$MODEL"
fi

# Un LaunchAgent par service. Les binaires et modèles sont hors du Bureau : launchd n'a pas besoin
# d'autorisation « Fichiers et dossiers ». GGML_METAL_RESIDENCY_KEEP_ALIVE_S garde les poids en mémoire GPU
# (sinon ils sont relâchés après 180 s d'inactivité et la dictée suivante est plus lente).
write_agent() { # label, programme+args (séparés par \n), variables d'env (NOM=val\n)
  local label=$1 args=$2 envs=$3 plist="$LA_DIR/$1.plist"
  {
    print '<?xml version="1.0" encoding="UTF-8"?>'
    print '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    print '<plist version="1.0"><dict>'
    print "  <key>Label</key><string>$label</string>"
    print '  <key>ProgramArguments</key><array>'
    for a in ${(f)args}; do print "    <string>$a</string>"; done
    print '  </array>'
    print '  <key>EnvironmentVariables</key><dict>'
    for e in ${(f)envs}; do print "    <key>${e%%=*}</key><string>${e#*=}</string>"; done
    print '  </dict>'
    print '  <key>RunAtLoad</key><true/>'
    print '  <key>KeepAlive</key><true/>'
    print '  <key>ProcessType</key><string>Interactive</string>'
    print "  <key>StandardOutPath</key><string>$DATA_DIR/logs/$label.log</string>"
    print "  <key>StandardErrorPath</key><string>$DATA_DIR/logs/$label.log</string>"
    print '</dict></plist>'
  } > "$plist"
  launchctl bootout "gui/$UID_/$label" 2>/dev/null || true
  # bootout est asynchrone : charger avant la fin du déchargement échoue (« Bootstrap failed: 5 »).
  for _ in {1..50}; do launchctl print "gui/$UID_/$label" >/dev/null 2>&1 || break; sleep 0.1; done
  for attempt in {1..5}; do
    launchctl bootstrap "gui/$UID_" "$plist" 2>/dev/null && return 0
    sleep 1
  done
  launchctl bootstrap "gui/$UID_" "$plist"  # dernier essai, avec le message d'erreur
}

step "Service whisper-server (port $WHISPER_PORT)"
write_agent com.voice-dictation.whisper "/opt/homebrew/bin/whisper-server
-m
$MODEL
--host
127.0.0.1
--port
$WHISPER_PORT
-t
$THREADS" "GGML_METAL_RESIDENCY_KEEP_ALIVE_S=31536000"

step "Service Ollama"
# Agent dédié plutôt que `brew services` : il permet de fixer les variables d'environnement.
brew services stop ollama >/dev/null 2>&1 || true
write_agent com.voice-dictation.ollama "/opt/homebrew/bin/ollama
serve" "OLLAMA_KEEP_ALIVE=-1
OLLAMA_FLASH_ATTENTION=1
OLLAMA_HOST=127.0.0.1:11434
GGML_METAL_RESIDENCY_KEEP_ALIVE_S=31536000"
for i in {1..30}; do curl -sf http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done

step "Modèle de nettoyage : $LLM"
/opt/homebrew/bin/ollama list | awk '{print $1}' | grep -qx "$LLM" || /opt/homebrew/bin/ollama pull "$LLM"

step "Hammerspoon"
mkdir -p ~/.hammerspoon
INIT=~/.hammerspoon/init.lua
touch $INIT
# Retire un éventuel ancien bloc puis ajoute le bloc courant.
/opt/homebrew/bin/python3 - "$INIT" <<'EOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
s = re.sub(r"\n?-- >>> voice-dictation >>>.*?-- <<< voice-dictation <<<\n?", "\n", s, flags=re.S)
open(p, "w").write(s.rstrip("\n") + ("\n" if s.strip() else ""))
EOF
cat >> $INIT <<EOF
-- >>> voice-dictation >>>
require("hs.ipc")
hs.autoLaunch(true)
hs.consoleOnTop(false)
dictation = dofile("$REPO/hammerspoon/dictation.lua").start()
-- <<< voice-dictation <<<
EOF
defaults write org.hammerspoon.Hammerspoon MJShowDockIconKey -bool false
defaults write org.hammerspoon.Hammerspoon HSUploadCrashData -bool false
# Redémarrage plutôt que rechargement via `hs` : interrompre une requête IPC en cours fait planter
# Hammerspoon (hs.ipc répond alors à un port mort).
pkill -x Hammerspoon 2>/dev/null && for _ in {1..50}; do pgrep -xq Hammerspoon || break; sleep 0.1; done
open -a Hammerspoon

step "Terminé. Vérification : $REPO/bin/doctor"
