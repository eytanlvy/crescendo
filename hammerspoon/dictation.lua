-- Dictée vocale push-to-talk : raccourci, enregistrement, overlay, sons, collage.
-- Le travail (Whisper, nettoyage, vocabulaire, historique) est fait par bin/dictate.
-- Chargé depuis ~/.hammerspoon/init.lua (voir scripts/install.sh).

local M = {}

local REPO = debug.getinfo(1, "S").source:sub(2):match("(.*)/hammerspoon/[^/]+$")
local DICTATE = REPO .. "/bin/dictate"
local log = hs.logger.new("dictation", "info")

local cfg                -- config résolue (bin/dictate config --json)
local hotkeys = {}       -- raccourcis permanents
local cancelKeys = {}    -- Échap, actifs seulement pendant l'enregistrement
local rec = nil          -- enregistrement en cours : {task, wav, mode, tPress, tRelease, maxTimer}
local queue = {}         -- enregistrements terminés en attente de transcription
local processing = nil   -- job en cours de transcription
local overlay, overlayTimer
local menu
local recent = {}        -- dernières dictées (menu : recoller)

local function now() return hs.timer.absoluteTime() / 1e6 end -- ms

-------------------------------------------------------------------------------
-- Feedback : sons, overlay, notifications
-------------------------------------------------------------------------------

local function sound(name)
  if not cfg.feedback.sounds or not name or name == "" then return end
  local s = hs.sound.getByName(name)
  if s then s:volume(cfg.feedback.volume):play() end
end

local function notify(title, text)
  log.w(title .. " : " .. (text or ""))
  hs.notify.new({title = "Dictée — " .. title, informativeText = text or "", withdrawAfter = 8}):send()
end

local function hideOverlay()
  if overlayTimer then overlayTimer:stop(); overlayTimer = nil end
  if overlay then overlay:delete(); overlay = nil end
end

local function showOverlay(kind, label)
  if not cfg.feedback.overlay then return end
  hideOverlay()
  local screen = hs.screen.mainScreen():frame()
  local w, h = 118, 34
  overlay = hs.canvas.new({x = screen.x + (screen.w - w) / 2, y = screen.y + 12, w = w, h = h})
  overlay:level(hs.canvas.windowLevels.overlay)
  overlay:behavior({"canJoinAllSpaces", "stationary"})
  overlay:clickActivating(false)
  overlay:appendElements(
    {type = "rectangle", action = "fill", roundedRectRadii = {xRadius = 17, yRadius = 17},
     fillColor = {white = 0.08, alpha = 0.88}},
    {type = "circle", action = "fill", center = {x = 22, y = h / 2}, radius = 6,
     fillColor = kind == "rec" and {red = 1, green = 0.23, blue = 0.19} or {white = 0.6}},
    {type = "text", text = label, frame = {x = 36, y = 7, w = w - 42, h = 22},
     textColor = {white = 1}, textSize = 14, textFont = ".AppleSystemUIFontBold"}
  )
  overlay:show()
end

local function flash(label, seconds)
  showOverlay("info", label)
  overlayTimer = hs.timer.doAfter(seconds or 0.8, hideOverlay)
end

local function showRecording()
  local t0 = rec.tPress
  showOverlay("rec", "REC 0:00")
  overlayTimer = hs.timer.doEvery(0.5, function()
    if overlay and rec then
      local s = math.floor((now() - t0) / 1000)
      overlay[3].text = string.format("REC %d:%02d", s // 60, s % 60)
    end
  end)
end

local function updateMenu()
  if not menu then return end
  menu:setTitle(rec and "🔴" or ((processing or #queue > 0) and "⏳" or "🎙"))
end

-------------------------------------------------------------------------------
-- Collage : presse-papiers transitoire + ⌘V, puis restauration
-------------------------------------------------------------------------------

local function modifiersDown()
  local m = hs.eventtap.checkKeyboardModifiers()
  return m.alt or m.cmd or m.ctrl or m.shift
end

-- Attend que l'utilisateur ait relâché ⌥/⇧ (sinon ⌘V deviendrait ⌥⌘V), au plus 1,5 s.
local function whenModifiersReleased(fn)
  local deadline = now() + 1500
  local function check()
    if modifiersDown() and now() < deadline then
      hs.timer.doAfter(0.03, check)
    else
      fn()
    end
  end
  check()
end

local function paste(text, pressEnter, done)
  local saved = hs.pasteboard.readAllData() or {}
  hs.pasteboard.clearContents()
  -- TransientType : les gestionnaires de presse-papiers ignorent ce contenu.
  hs.pasteboard.writeAllData({["public.utf8-plain-text"] = text, ["org.nspasteboard.TransientType"] = ""})
  local ourCount = hs.pasteboard.changeCount()
  whenModifiersReleased(function()
    hs.eventtap.keyStroke({"cmd"}, "v", 0)
    local tPasted = now()
    if pressEnter then
      hs.timer.doAfter(cfg.output.enter_delay_ms / 1000, function() hs.eventtap.keyStroke({}, "return", 0) end)
    end
    hs.timer.doAfter(cfg.output.restore_clipboard_delay_ms / 1000, function()
      if hs.pasteboard.changeCount() ~= ourCount then return end -- l'utilisateur a copié autre chose entre-temps
      hs.pasteboard.clearContents()
      if next(saved) then hs.pasteboard.writeAllData(saved) end
    end)
    done(tPasted)
  end)
end

-------------------------------------------------------------------------------
-- Historique bout-en-bout (complète history.jsonl écrit par bin/dictate)
-------------------------------------------------------------------------------

local function appendE2E(record)
  local f = io.open(cfg.paths.data_dir .. "/e2e.jsonl", "a")
  if f then f:write(hs.json.encode(record) .. "\n"); f:close() end
end

-------------------------------------------------------------------------------
-- Transcription (file d'attente séquentielle : l'ordre des collages est préservé)
-------------------------------------------------------------------------------

local processNext

local function finishJob(job)
  os.remove(job.wav)
  processing = nil
  updateMenu()
  processNext()
end

local function onPipelineDone(job, exitCode, stdout, stderr)
  if job.timeout then job.timeout:stop() end
  if job.killed then return end
  local ok, res = pcall(hs.json.decode, stdout or "")
  if not ok or type(res) ~= "table" then
    hideOverlay(); sound(cfg.feedback.sound_error)
    notify("erreur du pipeline", (stderr or ""):sub(1, 300))
    return finishJob(job)
  end
  for _, w in ipairs(res.warnings or {}) do notify("attention", w) end
  if res.status == "error" then
    hideOverlay(); sound(cfg.feedback.sound_error)
    local hint = res.error_service == "whisper"
      and "Serveur Whisper indisponible. Lancez bin/doctor." or ""
    notify("échec de la transcription", (res.error or "") .. "\n" .. hint)
    return finishJob(job)
  end
  if res.status ~= "ok" or not res.text or res.text == "" then
    -- silence, appui trop court, hallucination filtrée : rien à insérer
    flash(res.status == "silence" and "silence" or "rien", 0.7)
    return finishJob(job)
  end
  table.insert(recent, 1, res.text)
  if #recent > 5 then table.remove(recent) end
  paste(res.text, job.mode == "enter", function(tPasted)
    if not rec then hideOverlay() end
    sound(cfg.feedback.sound_stop)
    appendE2E({id = res.id, ts = os.date("%Y-%m-%dT%H:%M:%S"), app = job.app, mode = job.mode,
               e2e_ms = math.floor(tPasted - job.tRelease + 0.5),
               pipeline_ms = res.timings_ms and res.timings_ms.total})
    finishJob(job)
  end)
end

processNext = function()
  if processing or #queue == 0 then return end
  local job = table.remove(queue, 1)
  processing = job
  updateMenu()
  if not rec then showOverlay("busy", "…") end
  local args = {DICTATE, job.wav, "--json", "--mode", job.mode,
                "--rec-window-ms", string.format("%.0f", job.window)}
  if job.app then table.insert(args, "--app"); table.insert(args, job.app) end
  job.task = hs.task.new(cfg.paths.python, function(code, out, err) onPipelineDone(job, code, out, err) end, args)
  local limit = cfg.whisper.timeout_s + cfg.cleanup.timeout_s + 10
  job.timeout = hs.timer.doAfter(limit, function()
    job.killed = true
    if job.task:isRunning() then job.task:terminate() end
    hideOverlay(); sound(cfg.feedback.sound_error)
    notify("délai dépassé", string.format("Transcription abandonnée après %d s.", limit))
    finishJob(job)
  end)
  if not job.task:start() then
    job.timeout:stop()
    notify("erreur", "Impossible de lancer " .. DICTATE)
    finishJob(job)
  end
end

-------------------------------------------------------------------------------
-- Enregistrement
-------------------------------------------------------------------------------

local function setCancelKeys(enabled)
  for _, k in ipairs(cancelKeys) do if enabled then k:enable() else k:disable() end end
end

local function startRecording(mode)
  if rec then return end -- appui déjà en cours (autre raccourci)
  local app = hs.application.frontmostApplication()
  local wav = string.format("%s/dictation-%d.wav", os.getenv("TMPDIR"):gsub("/$", ""), math.floor(now() * 1000))
  local r = cfg.recording
  rec = {wav = wav, mode = mode, tPress = now(), app = app and app:bundleID() or nil}
  rec.task = hs.task.new(r.rec_binary, function(code, _, err)
    if rec and rec.task and code ~= 0 and not rec.stopping then
      log.e("rec a échoué : " .. (err or ""))
    end
  end, {"-q", "-c", "1", "-r", "16000", "-b", "16", "-e", "signed-integer", wav,
        "trim", "0", tostring(r.max_duration_s)})
  if not rec.task:start() then
    rec = nil
    sound(cfg.feedback.sound_error)
    notify("micro", "Impossible de lancer " .. r.rec_binary)
    return
  end
  sound(cfg.feedback.sound_start)
  showRecording()
  setCancelKeys(true)
  rec.maxTimer = hs.timer.doAfter(r.max_duration_s, function() M.stop() end)
  updateMenu()
end

function M.cancel()
  if not rec then return end
  local r = rec
  rec = nil
  setCancelKeys(false)
  r.maxTimer:stop()
  r.stopping = true
  r.task:terminate()
  hs.timer.doAfter(0.3, function() os.remove(r.wav) end)
  if processing or #queue > 0 then showOverlay("busy", "…") else flash("annulé", 0.6) end
  updateMenu()
end

function M.stop()
  if not rec then return end
  local r = rec
  r.tRelease = now()
  if r.tRelease - r.tPress < cfg.recording.min_duration_s * 1000 then
    return M.cancel() -- appui trop court : ignoré
  end
  rec = nil
  setCancelKeys(false)
  r.maxTimer:stop()
  r.stopping = true
  showOverlay("busy", "…")
  updateMenu()
  -- On continue d'enregistrer tail_ms après le relâchement (fin du dernier mot), puis SIGINT :
  -- sox finalise proprement l'en-tête wav.
  hs.timer.doAfter(cfg.recording.tail_ms / 1000, function()
    local tStop = now()
    local function enqueue()
      table.insert(queue, {wav = r.wav, mode = r.mode, app = r.app, tRelease = r.tRelease,
                           window = tStop - r.tPress})
      processNext()
    end
    if r.task:isRunning() then
      r.task:setCallback(enqueue)
      r.task:interrupt()
    else
      enqueue() -- rec déjà terminé (durée max atteinte)
    end
  end)
end

-------------------------------------------------------------------------------
-- Menu (état + recoller les dernières dictées)
-------------------------------------------------------------------------------

local function menuItems()
  local items = {}
  for i, text in ipairs(recent) do
    local label = #text > 60 and (text:sub(1, 57) .. "…") or text
    table.insert(items, {title = i .. ". " .. label, fn = function() paste(text, false, function() end) end})
  end
  if #items == 0 then table.insert(items, {title = "Aucune dictée récente", disabled = true}) end
  table.insert(items, {title = "-"})
  table.insert(items, {title = "Ouvrir la configuration", fn = function() hs.execute("open -t " .. REPO .. "/config.toml") end})
  table.insert(items, {title = "Ouvrir le vocabulaire", fn = function() hs.execute("open -t " .. REPO .. "/vocabulary.txt") end})
  table.insert(items, {title = "Ouvrir l'historique", fn = function() hs.execute("open -t " .. cfg.paths.data_dir .. "/history.jsonl") end})
  table.insert(items, {title = "Recharger", fn = function() hs.reload() end})
  return items
end

-------------------------------------------------------------------------------
-- Démarrage
-------------------------------------------------------------------------------

local function loadConfig()
  local out, ok = hs.execute(string.format("'%s' config --json 2>&1", DICTATE))
  if not ok then error("configuration invalide : " .. out) end
  return hs.json.decode(out)
end

function M.start()
  local ok, result = pcall(loadConfig)
  if not ok then
    notify("configuration", tostring(result))
    return M
  end
  cfg = result
  os.execute("mkdir -p '" .. cfg.paths.data_dir .. "'")

  for name, mode in pairs({dictate = "insert", dictate_and_enter = "enter"}) do
    local hk = cfg.hotkeys_parsed[name]
    local assigned = hs.hotkey.systemAssigned(hk.mods, hk.key)
    if assigned then
      notify("raccourci en conflit", cfg.hotkeys[name] .. " est déjà utilisé par macOS (Réglages ▸ Clavier ▸ Raccourcis).")
    end
    -- La fonction de répétition vide absorbe l'auto-répétition de la touche tenue.
    local key = hs.hotkey.bind(hk.mods, hk.key, function() startRecording(mode) end, M.stop, function() end)
    table.insert(hotkeys, key)
  end
  for _, mods in ipairs({{}, {"alt"}, {"alt", "shift"}, {"shift"}, {"cmd"}, {"ctrl"}}) do
    table.insert(cancelKeys, hs.hotkey.new(mods, "escape", M.cancel))
  end

  menu = hs.menubar.new()
  if menu then menu:setMenu(menuItems) end
  updateMenu()

  -- Charge les modèles en mémoire (attend les services au démarrage de session).
  M.warmupTask = hs.task.new(cfg.paths.python, function(code, out)
    if code ~= 0 then notify("services", "Préchauffage incomplet : " .. (out or "") .. "\nLancez bin/doctor.") end
    log.i("warmup : " .. (out or ""))
  end, {DICTATE, "warmup", "--wait", "180"})
  M.warmupTask:start()
  log.i("dictée prête (" .. cfg.hotkeys.dictate .. " / " .. cfg.hotkeys.dictate_and_enter .. ")")
  return M
end

-- Accès pour les tests (hs -c) et le doctor.
M.paste = paste
M._start = function(mode) startRecording(mode or "insert") end
M.state = function()
  return {recording = rec ~= nil, processing = processing ~= nil, queued = #queue,
          accessibility = hs.accessibilityState()}
end

return M
