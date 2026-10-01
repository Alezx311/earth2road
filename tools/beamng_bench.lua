-- Load/FPS benchmark loaded only in an isolated bench user directory (tools/beamng_bench.py).
-- Writes kyiv-bench-result.json as soon as the level is ready (the driver times that),
-- then visits fixed free-camera views: settle, screenshot, measure frame times.
-- No traffic and no AI, so variants of the same map compare like for like.
local M = {}
local elapsed, phase, view, viewStart = 0, 'waiting', 0, 0
local cfg, frames = nil, {}
local result = {status = 'waiting', views = {}}

local function save()
  jsonWriteFile('kyiv-bench-result.json', result, true)
end

local function countClass(name)
  local objects = scenetree.findClassObjects(name)
  return objects and #objects or 0
end

local function setView(v)
  local pos = vec3(v.pos[1], v.pos[2], v.pos[3])
  local target = vec3(v.look[1], v.look[2], v.look[3])
  local q = quatFromDir(target - pos, vec3(0, 0, 1))
  core_camera.setPosRot(0, pos.x, pos.y, pos.z, q.x, q.y, q.z, q.w)
end

function M.onInit()
  setExtensionUnloadMode(M, 'manual')
  cfg = jsonReadFile('kyiv-bench-input.json')
  result.status = 'extension_loaded'
  save()
end

function M.onUpdate(dtReal)
  elapsed = elapsed + dtReal
  if elapsed > (cfg.timeout or 900) then
    result.status = 'timeout'
    result.phase = phase
    save()
    shutdown(1)
    return
  end
  if phase == 'waiting' then
    if not getMissionFilename():find(cfg.level, 1, true) or worldReadyState < 2 then return end
    result.status = 'level_loaded'
    result.level = getMissionFilename()
    result.objects = #scenetree.getAllObjects()
    result.counts = {tsStatic = countClass('TSStatic'), decalRoad = countClass('DecalRoad'),
                     terrain = countClass('TerrainBlock'), forest = countClass('Forest')}
    save()
    commands.setFreeCamera()
    pcall(function() extensions.ui_visibility.setCef(false) end)
    pcall(function() local tod = scenetree.tod; if tod then tod.play = false end end)
    phase, elapsed = 'settle', 0
  elseif phase == 'settle' and elapsed > (cfg.settleSeconds or 8) then
    phase, view = 'view', 1
    setView(cfg.views[view])
    viewStart, frames = elapsed, {}
  elseif phase == 'view' then
    local v = cfg.views[view]
    local t = elapsed - viewStart
    if t > cfg.streamSeconds and not v.shot then
      createScreenshot2({filename = 'screenshots/bench-' .. v.name, writeJPG = false, superSampling = 1})
      v.shot = true
    elseif v.shot and t > cfg.streamSeconds + 0.5 then
      table.insert(frames, dtReal)
    end
    if t > cfg.streamSeconds + 0.5 + cfg.measureSeconds then
      local total = 0
      for _, dt in ipairs(frames) do total = total + dt end
      local sorted = {}
      for i, dt in ipairs(frames) do sorted[i] = dt end
      table.sort(sorted)
      result.views[v.name] = {frames = #frames, fps = #frames / math.max(total, 1e-6),
                              worstFrameMs = 1000 * (sorted[#sorted] or 0),
                              p95FrameMs = 1000 * (sorted[math.max(1, math.floor(#sorted * 0.95))] or 0)}
      save()
      view = view + 1
      if view > #cfg.views then
        result.status = 'complete'
        save()
        phase = 'done'
        shutdown(0)
      else
        setView(cfg.views[view])
        viewStart, frames = elapsed, {}
      end
    end
  end
end

return M
