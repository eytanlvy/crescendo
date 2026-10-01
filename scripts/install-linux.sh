#!/usr/bin/env bash
# Installe crescendo sur Linux. Idempotent : peut être relancé.
#
#   scripts/install-linux.sh [options]
#
#   --model NOM        modèle Whisper (défaut : large-v3-turbo-q8_0 avec CUDA, small sinon)
#   --llm NOM          modèle de nettoyage Ollama (défaut : celui de config.toml)
#   --hold-key KEY     push-to-talk par maintien d'une touche via evdev (ex. KEY_RIGHTCTRL)
#   --shortcut COMBO   raccourci GNOME en mode bascule (défaut : <Control><Alt>space ; « none » pour aucun)
#   --no-systemd       ne crée pas de services : lance whisper-server en arrière-plan (CI, conteneurs)
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DATA_DIR="$HOME/.local/share/voice-dictation"
MODELS="$DATA_DIR/models"
WHISPER_SRC="$DATA_DIR/whisper.cpp"
WHISPER_REF="${WHISPER_REF:-v1.9.4}"
UNIT_DIR="$HOME/.config/systemd/user"
PORT=8178

MODEL="" LLM="" HOLD_KEY="" SHORTCUT="<Control><Alt>space" USE_SYSTEMD=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL=$2; shift ;;
    --llm) LLM=$2; shift ;;
    --hold-key) HOLD_KEY=$2; shift ;;
    --shortcut) SHORTCUT=$2; shift ;;
    --no-systemd) USE_SYSTEMD=0 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "option inconnue : $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
[[ "$(uname -s)" == Linux ]] || { echo "Ce script est pour Linux (macOS : scripts/install.sh)." >&2; exit 1; }

# --------------------------------------------------------------------------- dépendances système
SESSION=${XDG_SESSION_TYPE:-}
[[ -z "$SESSION" && -n "${WAYLAND_DISPLAY:-}" ]] && SESSION=wayland
[[ -z "$SESSION" ]] && SESSION=x11
step "Distribution et session : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") / $SESSION"

if command -v apt-get >/dev/null; then
  PKGS=(build-essential cmake git curl python3 alsa-utils libnotify-bin)
  X11=(xclip xdotool x11-utils); WAYLAND=(wl-clipboard ydotool); EVDEV=(python3-evdev)
  install_pkgs() { sudo apt-get update -q && sudo DEBIAN_FRONTEND=noninteractive apt-get install -yq "$@"; }
elif command -v dnf >/dev/null; then
  PKGS=(gcc-c++ make cmake git curl python3 alsa-utils libnotify)
  X11=(xclip xdotool xprop); WAYLAND=(wl-clipboard ydotool); EVDEV=(python3-evdev)
  install_pkgs() { sudo dnf install -y "$@"; }
elif command -v pacman >/dev/null; then
  PKGS=(base-devel cmake git curl python alsa-utils libnotify)
  X11=(xclip xdotool xorg-xprop); WAYLAND=(wl-clipboard ydotool); EVDEV=(python-evdev)
  install_pkgs() { sudo pacman -S --needed --noconfirm "$@"; }
else
  echo "Gestionnaire de paquets non reconnu (apt, dnf, pacman). Installez à la main : cmake, git, curl," \
       "python3, alsa-utils, xclip+xdotool+xprop (X11) ou wl-clipboard+ydotool (Wayland)." >&2
  exit 1
fi
if [[ "$SESSION" == wayland ]]; then PKGS+=("${WAYLAND[@]}"); else PKGS+=("${X11[@]}"); fi
[[ -n "$HOLD_KEY" ]] && PKGS+=("${EVDEV[@]}")
step "Paquets : ${PKGS[*]}"
install_pkgs "${PKGS[@]}"

python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11+ requis." >&2; exit 1; }

# --------------------------------------------------------------------------- whisper.cpp
CUDA=0
if command -v nvidia-smi >/dev/null && command -v nvcc >/dev/null; then CUDA=1; fi
if [[ -z "$MODEL" ]]; then
  if (( CUDA )); then MODEL=large-v3-turbo-q8_0; else MODEL=small; fi
fi
step "whisper.cpp $WHISPER_REF ($( ((CUDA)) && echo CUDA || echo CPU))"
mkdir -p "$MODELS"
if [[ ! -d "$WHISPER_SRC/.git" ]]; then
  git clone -q --depth 1 --branch "$WHISPER_REF" https://github.com/ggml-org/whisper.cpp "$WHISPER_SRC"
fi
CMAKE_OPTS=(-DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF)
(( CUDA )) && CMAKE_OPTS+=(-DGGML_CUDA=1)
cmake -S "$WHISPER_SRC" -B "$WHISPER_SRC/build" "${CMAKE_OPTS[@]}" >/dev/null
cmake --build "$WHISPER_SRC/build" -j "$(nproc)" --target whisper-server >/dev/null
SERVER="$WHISPER_SRC/build/bin/whisper-server"
[[ -x "$SERVER" ]] || { echo "Compilation de whisper-server échouée." >&2; exit 1; }
if (( ! CUDA )) && [[ "$MODEL" == large* ]]; then
  warn "Sans GPU CUDA, $MODEL sera lent : préférez --model small ou base."
fi

MODEL_FILE="$MODELS/ggml-$MODEL.bin"
step "Modèle Whisper : ggml-$MODEL.bin"
if [[ ! -s "$MODEL_FILE" ]]; then
  curl -fL --progress-bar -o "$MODEL_FILE.part" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$MODEL.bin"
  mv "$MODEL_FILE.part" "$MODEL_FILE"
fi

# --------------------------------------------------------------------------- configuration
step "Configuration"
[[ -f "$REPO/vocabulary.txt" ]] || { cp "$REPO/vocabulary.example.txt" "$REPO/vocabulary.txt"; echo "  vocabulary.txt créé (complétez-le)"; }
# Les modèles choisis sont écrits dans config.toml ([whisper] model, et [cleanup] model si --llm).
python3 - "$REPO/config.toml" "$MODEL_FILE" "$LLM" <<'PY'
import re, sys
path, model, llm = sys.argv[1:4]
s = open(path, encoding="utf-8").read()

def set_model(text, section, value):
    head, sep, rest = text.partition(f"[{section}]")
    assert sep, f"section [{section}] introuvable dans config.toml"
    rest, n = re.subn(r'(?m)^model = "[^"]*"', lambda m: f'model = "{value}"', rest, count=1)
    assert n == 1, f"clé {section}.model introuvable dans config.toml"
    return head + sep + rest

s = set_model(s, "whisper", model)
if llm:
    s = set_model(s, "cleanup", llm)
open(path, "w", encoding="utf-8").write(s)
PY
LLM=$(python3 "$REPO/bin/dictate" config --get cleanup.model)
THREADS=$(( $(nproc) > 8 ? 8 : $(nproc) ))

# --------------------------------------------------------------------------- Ollama
step "Ollama et le modèle $LLM"
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
if ! curl -sf http://127.0.0.1:11434/api/version >/dev/null; then
  (ollama serve >/dev/null 2>&1 &)   # l'installeur Ollama crée normalement un service ; sinon on le lance
  for _ in $(seq 1 30); do curl -sf http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done
fi
ollama pull "$LLM"

# --------------------------------------------------------------------------- services
DAEMON_ARGS="run"
[[ -n "$HOLD_KEY" ]] && DAEMON_ARGS+=" --hold-key $HOLD_KEY"
if (( USE_SYSTEMD )) && systemctl --user show-environment >/dev/null 2>&1; then
  step "Services systemd utilisateur"
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/crescendo-whisper.service" <<EOF
[Unit]
Description=crescendo: whisper.cpp server

[Service]
ExecStart=$SERVER -m $MODEL_FILE --host 127.0.0.1 --port $PORT -t $THREADS
Restart=on-failure

[Install]
WantedBy=default.target
EOF
  cat > "$UNIT_DIR/crescendo.service" <<EOF
[Unit]
Description=crescendo: push-to-talk dictation
PartOf=graphical-session.target
After=graphical-session.target crescendo-whisper.service

[Service]
ExecStart=/usr/bin/env python3 $REPO/frontends/linux/dictation_daemon.py $DAEMON_ARGS
Restart=on-failure

[Install]
WantedBy=graphical-session.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now crescendo-whisper.service
  systemctl --user enable crescendo.service
  systemctl --user restart crescendo.service 2>/dev/null || warn "crescendo.service démarrera à la prochaine session graphique"
else
  step "whisper-server en arrière-plan (sans systemd)"
  pgrep -f "whisper-server.*--port $PORT" >/dev/null || \
    nohup "$SERVER" -m "$MODEL_FILE" --host 127.0.0.1 --port $PORT -t $THREADS > "$DATA_DIR/whisper-server.log" 2>&1 &
  warn "Pas de démarrage automatique. Lancez le frontend : python3 $REPO/frontends/linux/dictation_daemon.py $DAEMON_ARGS"
fi
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$PORT/" >/dev/null && break; sleep 1; done
curl -sf "http://127.0.0.1:$PORT/" >/dev/null || { echo "whisper-server ne répond pas (voir les logs)." >&2; exit 1; }

# --------------------------------------------------------------------------- raccourci GNOME
CTL="python3 $REPO/frontends/linux/dictation_daemon.py ctl toggle"
if [[ "$SHORTCUT" != none ]] && command -v gsettings >/dev/null \
   && gsettings list-schemas 2>/dev/null | grep -qx org.gnome.settings-daemon.plugins.media-keys; then
  step "Raccourcis GNOME : $SHORTCUT (dicter), $SHORTCUT + Maj (dicter + Entrée)"
  BASE=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
  ENTER_SHORTCUT=${SHORTCUT/<Control>/<Control><Shift>}
  for spec in "crescendo|$CTL|$SHORTCUT" "crescendo-enter|$CTL enter|$ENTER_SHORTCUT"; do
    IFS='|' read -r id cmd binding <<< "$spec"
    schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE/$id/"
    gsettings set "$schema" name "$id"
    gsettings set "$schema" command "$cmd"
    gsettings set "$schema" binding "$binding"
  done
  current=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)
  updated=$(python3 - "$current" "$BASE" <<'EOF'
import ast, sys
cur, base = sys.argv[1], sys.argv[2]
items = [] if cur.startswith("@as") else ast.literal_eval(cur)
for i in ("crescendo", "crescendo-enter"):
    if f"{base}/{i}/" not in items:
        items.append(f"{base}/{i}/")
print(str(items))
EOF
)
  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$updated"
elif [[ "$SHORTCUT" != none ]]; then
  warn "Raccourci non configuré automatiquement (bureau autre que GNOME). Associez dans vos réglages clavier :"
  echo "    $CTL          (dicter)"
  echo "    $CTL enter    (dicter + Entrée)"
fi

if [[ -n "$HOLD_KEY" ]] && ! id -nG | grep -qw input; then
  sudo usermod -aG input "$USER"
  warn "Ajouté au groupe « input » pour --hold-key : déconnectez-vous puis reconnectez-vous."
fi
if [[ "$SESSION" == wayland ]]; then
  warn "Wayland : le collage passe par ydotool, qui nécessite le démon ydotoold (accès à /dev/uinput)."
fi

# --------------------------------------------------------------------------- vérification
step "Préchauffage des modèles"
python3 "$REPO/bin/dictate" warmup --wait 120
cat <<EOF

crescendo est installé.
  - Dicter : $( [[ -n "$HOLD_KEY" ]] && echo "maintenez $HOLD_KEY, parlez, relâchez" || echo "$SHORTCUT pour démarrer, de nouveau pour coller" )
  - Vocabulaire : $REPO/vocabulary.txt
  - Désinstaller : $REPO/scripts/uninstall-linux.sh
EOF
