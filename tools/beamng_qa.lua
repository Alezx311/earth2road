-- Runtime smoke test loaded only in the isolated QA user directory.
-- Checks that the level loads, that the navigation graph and traffic signals bind,
-- that the road surface is where the exporter says it is, and captures screenshots.
local M = {}
local elapsed, phase = 0, 0
local result = {status = 'waiting', samples = {}, frames = {}, signalErrors = {}, shots = {}}
local samples, level, views, timeoutLimit = nil, nil, nil, 300

local function save()
  jsonWriteFile('kyiv-qa-result.json', result, true)
end

local function countClass(name)
  local objects = scenetree.findClassObjects(name)
  return objects and #objects or 0
end

function M.onInit()
  setExtensionUnloadMode(M, 'manual')
  local cfg = jsonReadFile('kyiv-qa-input.json')
  samples, level, views = cfg.samples, cfg.level, cfg.views or {}
  timeoutLimit = tonumber(cfg.timeout) or 300
  result.status = 'extension_loaded'
  save()
end

function M.onUpdate(dtReal)
  elapsed = elapsed + dtReal
  if elapsed > timeoutLimit then
    result.status = 'timeout'
    result.phase = phase
    result.timeout = timeoutLimit
    save()
    shutdown(1)
    return
  end
  if not getMissionFilename():find(level, 1, true) or worldReadyState < 2 then return end

  if phase == 0 then
    phase, elapsed = 1, 0
    result.status = 'level_loaded'
    result.level = getMissionFilename()
    result.objects = #scenetree.getAllObjects()
    result.counts = {
      tsStatic = countClass('TSStatic'),
      decalRoad = countClass('DecalRoad'),
      forest = countClass('Forest'),
      waypoint = countClass('BeamNGWaypoint'),
    }
    local ok, items = pcall(function()
      local forest = scenetree.findClassObjects('Forest')
      return #scenetree.findObject(forest[1]):getData():getItems()
    end)
    result.counts.forestItems = ok and items or -1
    local mapData = map.getMap()
    result.navNodes = tableSize(mapData.nodes)
    local links = 0
    for _, node in pairs(mapData.nodes) do links = links + tableSize(node.links) end
    result.navLinks = links
    for _, p in ipairs(samples) do
      local hit = castRayStatic(vec3(p[1], p[2], p[3] + 2), vec3(0, 0, -1), 6)
      table.insert(result.samples, {point = p, distance = hit, error = math.abs(hit - 2)})
    end
    if core_trafficSignals then
      local signals = core_trafficSignals.getSignals()
      result.signalCount = #signals
      for _, s in ipairs(signals) do
        if not s.road then table.insert(result.signalErrors, s.name) end
      end
    end
    save()
    core_vehicles.spawnNewVehicle('etk800', {})
  elseif phase == 1 and elapsed > 12 then
    phase = 2
    result.vehicleSpawned = be:getObjectCount() > 0
    gameplay_traffic.setupTraffic(6, {simpleVehs = false})
    save()
  elseif phase == 2 and elapsed > 26 then
    phase = 3
    commands.setFreeCamera()
    -- -level leaves the main menu drawn over the world; hide it so the shots show the map
    pcall(function() extensions.ui_visibility.setCef(false) end)
  elseif phase >= 3 and phase < 3 + #views and elapsed > 28 + (phase - 3) * 6 then
    local v = views[phase - 2]
    local pos = vec3(v.pos[1], v.pos[2], v.pos[3])
    local target = vec3(v.look[1], v.look[2], v.look[3])
    local q = quatFromDir(target - pos, vec3(0, 0, 1))
    core_camera.setPosRot(0, pos.x, pos.y, pos.z, q.x, q.y, q.z, q.w)
    createScreenshot2({filename = 'screenshots/kyiv-' .. v.name, writeJPG = false, superSampling = 1})
    table.insert(result.shots, v.name)
    phase = phase + 1
  elseif phase == 3 + #views then
    table.insert(result.frames, dtReal)
    if elapsed > 34 + #views * 6 + 30 then
      result.status = 'complete'
      result.vehicleCount = be:getObjectCount()
      local okTraffic, count = pcall(function() return tableSize(gameplay_traffic.getTrafficData()) end)
      result.trafficCount = okTraffic and count or -1
      result.signalTimer = core_trafficSignals and core_trafficSignals.getTimer()
      save()
      phase = phase + 1
    end
  elseif phase == 4 + #views then
    shutdown(0)
  end
end

return M
