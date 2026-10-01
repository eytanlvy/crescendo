-- Aides pour tester l'insertion dans de vraies applications, pilotées depuis le terminal :
--   hs -c 'T = dofile(".../tests/manual/insertion.lua")'
--   hs -c 'T.pasteInto("Google Chrome", "texte", false)'
-- Les résultats sont lus ensuite (titre de fenêtre, fichier, presse-papiers).
local T = {}

T.log = {}

-- Active l'app, met un contenu « ancien » dans le presse-papiers, puis colle via la vraie fonction du module.
-- titlePattern : motif Lua du titre de la fenêtre cible (on ne colle jamais dans une autre fenêtre).
function T.focus(appName, titlePattern)
  local app = hs.application.get(appName)
  if not app then return nil, "app absente : " .. appName end
  for _, w in ipairs(app:allWindows()) do
    if w:title():find(titlePattern) then w:focus(); return w end
  end
  return nil, "fenêtre introuvable : " .. titlePattern
end

function T.pasteInto(appName, titlePattern, text, enter)
  local w, err = T.focus(appName, titlePattern)
  if not w then return err end
  hs.pasteboard.setContents("ANCIEN PRESSE-PAPIERS")
  hs.timer.doAfter(0.6, function()
    local fw = hs.window.focusedWindow()
    if not (fw and fw:title():find(titlePattern)) then
      T.log[#T.log + 1] = "ANNULÉ : fenêtre active inattendue " .. (fw and fw:title() or "?")
      return
    end
    T.log[#T.log + 1] = "collé dans " .. fw:title()
    dictation.paste(text, enter, function() end)
  end)
  return "programmé"
end

function T.title(appName)
  local app = hs.application.get(appName)
  local w = app and (app:focusedWindow() or app:mainWindow())
  return w and w:title() or "?"
end

function T.clipboard()
  return hs.pasteboard.getContents()
end

-- Maintient un raccourci (événements clavier synthétiques) pendant `seconds`.
function T.hold(mods, key, seconds)
  hs.eventtap.event.newKeyEvent(mods, key, true):post()
  -- auto-répétition simulée : vérifie que la répétition de Space ne casse rien
  local rep = hs.timer.doEvery(0.1, function()
    local e = hs.eventtap.event.newKeyEvent(mods, key, true)
    e:setProperty(hs.eventtap.event.properties.keyboardEventAutorepeat, 1)
    e:post()
  end)
  hs.timer.doAfter(seconds, function()
    rep:stop()
    hs.eventtap.event.newKeyEvent(mods, key, false):post()
    for _, m in ipairs(mods) do hs.eventtap.event.newKeyEvent(m, false):post() end
  end)
  return "maintenu " .. seconds .. " s"
end

function T.keys(mods, key)
  hs.eventtap.keyStroke(mods, key, 0)
  return "ok"
end

function T.type(text)
  hs.eventtap.keyStrokes(text)
  return "ok"
end

return T
