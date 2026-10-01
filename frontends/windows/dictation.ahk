; Frontend Windows (EXPÉRIMENTAL) de la dictée vocale : l'équivalent de hammerspoon/dictation.lua.
; Requiert AutoHotkey v2, Python 3.11+, sox (enregistrement), whisper-server et Ollama lancés.
; Lancer : double-clic sur ce fichier (ou un raccourci dans shell:startup pour le démarrage de session).
#Requires AutoHotkey v2.0
#SingleInstance Force
#MaxThreadsPerHotkey 1   ; l'auto-répétition de la touche tenue ne relance rien
Persistent

REPO := RegExReplace(A_ScriptDir, "\\frontends\\windows$")
DICTATE := REPO "\bin\dictate"
PYTHON := "python"
PYTHON := Cfg("paths.python")
SOX := Cfg("recording.rec_binary")
MIN_MS := Number(Cfg("recording.min_duration_s")) * 1000
TAIL_MS := Number(Cfg("recording.tail_ms"))
MAX_S := Cfg("recording.max_duration_s")
RESTORE_MS := Number(Cfg("output.restore_clipboard_delay_ms"))
ENTER_MS := Number(Cfg("output.enter_delay_ms"))
SOUNDS := Cfg("feedback.sounds") = "true"

global recPid := 0, recFile := "", tPress := 0, cancelled := false, overlay := 0

; Lit une valeur de config.toml via le pipeline (une seule source de vérité).
Cfg(key) {
    tmp := A_Temp "\dictation-cfg-" A_TickCount ".txt"
    RunWait(A_ComSpec ' /c ""' PYTHON '" "' DICTATE '" config --get ' key ' > "' tmp '""', , "Hide")
    value := Trim(FileRead(tmp, "UTF-8"), " `t`r`n")
    FileDelete(tmp)
    return value
}

; "alt+shift+space" → "!+Space"
ToAhk(spec) {
    mods := Map("cmd", "#", "alt", "!", "ctrl", "^", "shift", "+")
    keys := Map("space", "Space", "return", "Enter", "escape", "Esc", "tab", "Tab", "delete", "Delete")
    out := ""
    parts := StrSplit(spec, "+")
    for i, part in parts {
        if i < parts.Length
            out .= mods[part]
        else
            out .= keys.Has(part) ? keys[part] : (RegExMatch(part, "^f\d+$") ? StrUpper(part) : part)
    }
    return out
}

MainKey(spec) {
    parts := StrSplit(spec, "+")
    key := parts[parts.Length]
    return key = "space" ? "Space" : key
}

Play(name) {
    if !SOUNDS
        return
    files := Map("start", "Speech On.wav", "stop", "Speech Off.wav", "error", "Windows Critical Stop.wav")
    try SoundPlay(A_WinDir "\Media\" files[name])
}

ShowOverlay(label, color) {
    global overlay
    HideOverlay()
    overlay := Gui("+AlwaysOnTop -Caption +ToolWindow +E0x20")
    overlay.BackColor := "1E1E1E"
    overlay.SetFont("s11 bold", "Segoe UI")
    overlay.AddText("c" color " w110 Center", label)
    overlay.Show("NoActivate y12 xCenter AutoSize")
}

HideOverlay() {
    global overlay
    if overlay {
        overlay.Destroy()
        overlay := 0
    }
}

StartDictation(mode, spec) {
    global recPid, recFile, tPress, cancelled
    if recPid
        return
    cancelled := false
    recFile := A_Temp "\dictation-" A_TickCount ".pcm"
    ; PCM brut + petit tampon : sox est tué à l'arrêt, un wav aurait un en-tête incomplet.
    Run('"' SOX '" -q --buffer 1024 -t waveaudio default -t raw -r 16000 -c 1 -b 16 -e signed-integer "'
        recFile '" trim 0 ' MAX_S, , "Hide", &recPid)
    tPress := A_TickCount
    Play("start")
    ShowOverlay("● REC", "FF453A")
    KeyWait(MainKey(spec))          ; relâchement de la touche principale, que ⌥ soit encore tenue ou non
    Stop(mode)
}

Stop(mode) {
    global recPid, recFile, tPress, cancelled
    if !recPid || cancelled
        return
    held := A_TickCount - tPress
    if held >= MIN_MS
        Sleep(TAIL_MS)
    try ProcessClose(recPid)
    recPid := 0
    window := A_TickCount - tPress
    if held < MIN_MS {
        HideOverlay()
        try FileDelete(recFile)
        return
    }
    ShowOverlay("…", "BBBBBB")
    out := recFile ".txt"
    app := ""
    try app := WinGetProcessName("A")
    code := RunWait('"' PYTHON '" "' DICTATE '" "' recFile '" --text-out "' out '" --mode ' mode
        ' --rec-window-ms ' window ' --app "' app '"', , "Hide")
    text := FileExist(out) ? FileRead(out, "UTF-8") : ""
    for f in [recFile, out, RegExReplace(recFile, "\.pcm$", ".wav")]
        try FileDelete(f)
    HideOverlay()
    if code != 0 {
        Play("error")
        TrayTip("Échec de la transcription. Lancez : python bin\dictate history -n 1", "Dictée", 3)
        return
    }
    if text != ""
        Paste(text, mode = "enter")
}

Paste(text, enter) {
    saved := ClipboardAll()
    A_Clipboard := ""
    A_Clipboard := text
    if !ClipWait(1) {
        A_Clipboard := saved
        return
    }
    ; Attendre le relâchement des modificateurs : sinon Ctrl+V deviendrait Alt+Ctrl+V.
    for key in ["Alt", "Shift", "Ctrl", "LWin", "RWin"]
        KeyWait(key, "T1.5")
    Send("^v")
    if enter {
        Sleep(ENTER_MS)
        Send("{Enter}")
    }
    Sleep(RESTORE_MS)
    A_Clipboard := saved
    Play("stop")
}

Cancel(*) {
    global recPid, recFile, cancelled
    if !recPid
        return
    cancelled := true
    try ProcessClose(recPid)
    recPid := 0
    try FileDelete(recFile)
    HideOverlay()
}

dictateSpec := Cfg("hotkeys.dictate")
enterSpec := Cfg("hotkeys.dictate_and_enter")
Hotkey(ToAhk(dictateSpec), (*) => StartDictation("insert", dictateSpec))
Hotkey(ToAhk(enterSpec), (*) => StartDictation("enter", enterSpec))
HotIf((*) => recPid != 0)
for k in ["Esc", "!Esc", "+!Esc", "+Esc", "^Esc"]
    Hotkey(k, Cancel)
HotIf()
TrayTip("Prête : maintenez " dictateSpec " pour dicter.", "Dictée", 1)
