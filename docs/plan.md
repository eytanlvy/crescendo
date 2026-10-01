# Plan d'implémentation — dictée push-to-talk locale

**Objectif** : maintenir ⌥Space → parler → relâcher → texte transcrit, nettoyé et collé au curseur, 100 % local.
**Architecture** : Hammerspoon (Lua, fin) gère raccourci, enregistrement `rec`, overlay, sons et collage ; il appelle
un pipeline Python stdlib (`bin/dictate --json <wav>`) qui interroge `whisper-server` (Metal, résident) puis Ollama
(nettoyage), applique garde-fous et vocabulaire, écrit l'historique et renvoie le texte.
**Stack** : whisper.cpp 1.9.4 (`large-v3-turbo` q5_0/q8_0), Ollama 0.35 (`qwen2.5:3b-instruct` / `llama3.2:3b`),
sox 14.4, Hammerspoon, Python 3.14 stdlib, pytest via uv.

## Arborescence

```
config.toml              # LA config (raccourcis, modèles, timeouts, langue, nettoyage…)
vocabulary.txt           # termes (→ prompt Whisper) + remplacements « faux => juste »
dictate/                 # pipeline Python, stdlib uniquement
  config.py  vocab.py  audio.py  filters.py  whisper.py  cleanup.py  pipeline.py  cli.py
bin/dictate  bin/doctor  # points d'entrée
hammerspoon/dictation.lua
launchd/                 # gabarit LaunchAgent whisper-server (généré par install.sh)
scripts/install.sh  scripts/uninstall.sh
bench/                   # génération d'échantillons, benchmark WER/latence
tests/                   # pytest (unitaires + intégration marquée)
```

Données hors dépôt (et hors Bureau, pour éviter les blocages TCC de launchd) :
`~/.local/share/voice-dictation/{models/, history.jsonl, e2e.jsonl, audio/, logs/}`.

## Tâches

1. **Socle** — git, `.gitignore`, `pyproject.toml` (pytest via uv), installs brew, modèles Whisper, modèles Ollama. ✅ en cours
2. **Config** (TDD) — `config.toml` + `dictate/config.py` : lecture tomllib, valeurs par défaut, validation (types,
   raccourcis), export JSON pour Lua (`dictate config --json`).
3. **Vocabulaire** (TDD) — parsing `vocabulary.txt`, prompt Whisper borné (~224 tokens, estimation prudente),
   remplacements insensibles à la casse sur frontières de mots, normalisation de casse des termes à majuscules
   (github → GitHub), espaces insécables → espaces.
4. **Audio + filtres** (TDD) — durée/RMS d'un wav (stdlib), rejet < 0,3 s et silence ; filtre anti-hallucinations
   (Amara.org, « Merci d'avoir regardé », [BLANK_AUDIO], (musique), écho du prompt, boucles de répétition).
5. **Client Whisper + service** — multipart stdlib vers `/inference` ; LaunchAgent `whisper-server` ;
   benchmark q5_0 vs q8_0 et `auto` vs `fr` (WER + latence) sur échantillons `say` puis dictées réelles.
6. **Nettoyage LLM** (TDD) — client Ollama (`keep_alive:-1`, `temperature:0`, timeout → brut), prompt système +
   exemples few-shot anti-« réponse » ; garde-fous : sortie trop longue, code apparu, préambule (« Voici… »),
   listes apparues, faible recouvrement lexical (traduction/réponse/résumé) → texte brut. Tests d'intégration
   piégeux (impératifs, questions, texte propre, FR/EN). Départage qwen2.5:3b vs llama3.2:3b.
7. **Pipeline + CLI + historique** (TDD, faux serveurs HTTP) — orchestration, latences par étape, `history.jsonl`,
   codes d'erreur explicites (whisper down ≠ ollama down), conservation des wav récents, `--warmup`.
8. **Hammerspoon** — ⌥Space / ⌥⇧Space (appui/relâche, répétitions neutralisées), `rec` démarré à l'appui,
   queue d'enregistrement configurable, Échap annule, max 120 s, overlay `hs.canvas` (● REC / …), sons,
   collage atomique ⌘V + restauration du presse-papiers (type transitoire), Entrée optionnelle, notifications
   d'erreur, mesure bout-en-bout (`e2e.jsonl`), mesure du « trou » de démarrage de `rec`.
9. **Installation** — `install.sh` (LaunchAgent whisper, `brew services` ollama, init.lua Hammerspoon, lancement
   au login, CLI `hs`) et `uninstall.sh` (désinstallation complète).
10. **Permissions** — pause utilisateur : Accessibilité + Micro pour Hammerspoon (+ accès Bureau).
11. **Mesures** — délai de démarrage `rec`, latence p50/max, empreinte mémoire, conflits ⌥Space, espace insécable,
    insertion dans Terminal.app, cmux (terminal de Claude Code), VS Code (éditeur + terminal), navigateur, Slack.
12. **doctor + README** — vérifications services/modèles/permissions/latence ; doc utilisation, config,
    vocabulaire, historique, dépannage, désinstallation.
13. **Démo réelle** — dictées de l'utilisateur (corpus réel pour le benchmark final), récap chiffré, questions
    vocabulaire.

## Critères de fin

Tests verts ; démo de bout en bout réelle ; latence relâche→insertion mesurée (p50 et max, cible ≤ 2 s pour ~10 s
de parole) ; mémoire mesurée ; démarrage automatique au login vérifié ; `doctor` au vert.
