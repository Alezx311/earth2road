-- Isolated, repeatable vehicle/road survey. All clocks are reset at phase changes.
local M = {}
local cfg, result, vehicle, case, record
local phase, age, total, number, frames = 'loading', 0, 0, 0, {}
local cameraPos, cameraTarget
local function save() jsonWriteFile('kyiv-qa-result.json', result, true) end
local function nextPhase(p) phase, age = p, 0; result.phase = p; save() end
local function xyz(v) return {v.x, v.y, v.z} end
local function view(pos, target)
  cameraPos,cameraTarget=pos,target
  if core_camera.getActiveCamName(0) ~= 'free' then commands.setFreeCamera() end
  local q = quatFromDir(target-pos, vec3(0,0,1))
  core_camera.setPosRot(0, pos.x,pos.y,pos.z,q.x,q.y,q.z,q.w)
end
local function shot(suffix)
  local name = case.name .. '-' .. suffix
  createScreenshot2({filename='screenshots/road-qa/'..name, writeJPG=false, superSampling=1})
  table.insert(record.shots, name)
end
local function telemetry(label)
  vehicle:queueLuaCommand([[local p=vec3(]]..serialize(case.point)..[[)
    local rays={}; for _,h in ipairs({0.3,2,15,100}) do
      local dist=obj:castRayStatic(p+vec3(0,0,h),vec3(0,0,-1),h+5)
      table.insert(rays,{height=h,distance=dist,error=h-dist}) end
    local dh=]]..tostring(case.dropHeight or 100)..[[
    local drop=obj:castRayStatic(p+vec3(0,0,dh),vec3(0,0,-1),dh+5)
    local w = {}; for _, v in pairs(wheels.wheels) do
    local centre = obj:getPosition() + (obj:getNodePosition(v.node1)+obj:getNodePosition(v.node2))*0.5
    table.insert(w, {name=v.name, contact=v.contactMaterialID1, force=v.downForceRaw, depth=v.contactDepth,
      centre=centre:toTable(), radius=v.radius}) end
    obj:queueGameEngineLua('extensions.kyivqa.receive(' .. serialize({caseName=']]..case.name..[[', label=']]..label..[[', wheels=w,
      rays=rays,spawnSurface=p.z+dh-drop,
      damage=beamstate.damage, upZ=obj:getDirectionVectorUp().z,
      position={obj:getPosition():toTable()}, speed=obj:getVelocity():length()}) .. ')')]])
end
function M.receive(data)
  if record and data.caseName == record.name then
    if data.label == 'drive_sample' then
      record.physicsTrace = record.physicsTrace or {}
      data.time = age
      table.insert(record.physicsTrace, data)
    else record[data.label] = data end
  end
end
function M.onInit()
  setExtensionUnloadMode(M, 'manual')
  cfg = jsonReadFile('kyiv-qa-input.json')
  result = {status='loading', cases={}, samples={}, frames={}, signalErrors={}, version=3}
  save()
end
local function beginCase()
  number = number + 1
  case = cfg.cases[number]
  if not case then nextPhase('finish'); return end
  record = {name=case.name, lane=case.lane, point=case.point, category=case.category, shots={}, trace={}}
  table.insert(result.cases, record)
  vehicle:queueLuaCommand("ai.setMode('disabled'); input.event('throttle',0,1); input.event('parkingbrake',1,1)")
  vehicle:reset()
  local p, d = vec3(case.point), vec3(case.direction)
  local q = quat(0,0,1,0) * quatFromDir(d,vec3(0,0,1))
  -- Deliberately no safeTeleport: it could conceal an obstruction by moving the car.
  view(p-d*12+vec3(0,0,8),p+vec3(0,0,1))
  record.rays = {}
  for _, h in ipairs({0.3, 2, 15, 100}) do
    local distance = castRayStatic(p+vec3(0,0,h),vec3(0,0,-1),h+5)
    table.insert(record.rays,{height=h, distance=distance, error=h-distance})
  end
  -- Ask vehicle physics: the GE raycast retains a spurious z=0 hit even with terrain.
  telemetry('probe')
  nextPhase('probe')
end
local function update(dt)
  total, age = total+dt, age+dt
  if total > (cfg.timeout or 1800) then result.status='timeout'; save(); shutdown(1); return end
  if phase == 'loading' then
    if not getMissionFilename():find(cfg.level,1,true) or worldReadyState < 2 then return end
    pcall(function() extensions.ui_visibility.setCef(false) end)
    result.loadingSeconds = total
    nextPhase('ready')
  elseif phase == 'ready' and age > 8 then
    result.level=getMissionFilename()
    result.terrains=scenetree.findClassObjects('TerrainBlock')
    result.planes=scenetree.findClassObjects('GroundPlane')
    local nodes=map.getMap().nodes
    result.navNodes=tableSize(nodes); result.navLinks=0
    for _, n in pairs(nodes) do result.navLinks=result.navLinks+tableSize(n.links) end
    if core_trafficSignals then
      local signals=core_trafficSignals.getSignals(); result.signalCount=#signals
      for _, s in ipairs(signals) do if not s.road then table.insert(result.signalErrors,s.name) end end
    end
    for _, p in ipairs(cfg.samples or {}) do
      local hit=castRayStatic(vec3(p[1],p[2],p[3]+0.3),vec3(0,0,-1),5.3)
      table.insert(result.samples,{point=p, error=0.3-hit})
    end
    -- Replace the default pickup; otherwise the exact spawn test drops onto it.
    core_vehicles.replaceVehicle('etk800', {})
    nextPhase('vehicle')
  elseif phase == 'vehicle' and age > 6 then
    vehicle=getPlayerVehicle(0)
    if not vehicle then return end
    result.vehicle=vehicle:getID()
    -- replaceVehicle may spawn beside the default pickup instead of replacing it;
    -- a parked leftover at the exact spawn would turn case 000 into a car crash.
    result.removedVehicles={}
    for i=be:getObjectCount()-1,0,-1 do
      local other=be:getObject(i)
      if other and other:getID()~=vehicle:getID() then
        table.insert(result.removedVehicles,other:getJBeamFilename())
        other:delete()
      end
    end
    nextPhase('cleanup')
  elseif phase == 'cleanup' and age > 1 then
    result.caseVehicleCount=be:getObjectCount()
    beginCase()
  elseif phase == 'probe' and record.probe then
    local p,d=vec3(case.point),vec3(case.direction)
    local q=quat(0,0,1,0)*quatFromDir(d,vec3(0,0,1))
    record.spawnSurface=record.probe.spawnSurface
    -- Place on the lane profile: the top ray can stop at the non-physical z=0 plane,
    -- and dropping from there onto roads 8-20 m lower wrecked the car before the drive.
    -- A real foreign surface above still fails the ray check in the report.
    vehicle:setPositionRotation(p.x,p.y,p.z+0.65,q.x,q.y,q.z,q.w)
    view(p-d*14+vec3(0,0,8),p+vec3(0,0,1))
    nextPhase('settle')
  elseif phase == 'settle' and age > 4 then
    record.settledPosition=xyz(vehicle:getPosition())
    record.settledVelocity=vehicle:getVelocity():length()
    telemetry('settled')
    shot('overview')
    nextPhase('overview_saved')
  elseif phase == 'overview_saved' and age > .5 then
    local p,d=vec3(case.point),vec3(case.direction)
    view(p+vec3(0,0,1.6),p+d*35+vec3(0,0,1.4))
    nextPhase('driver')
  elseif phase == 'driver' and age > 2 then
    shot('driver')
    nextPhase('driver_saved')
  elseif phase == 'driver_saved' and age > .5 then
    record.start=xyz(vehicle:getPosition())
    local script={}
    for _, p in ipairs(case.path or {}) do
      table.insert(script,{x=p[1],y=p[2],z=p[3],r=math.max(1.5,case.width/2),v=6})
    end
    vehicle:queueLuaCommand("input.event('parkingbrake',0,1); input.event('throttle',0,1)")
    if #script>1 then
      vehicle:queueLuaCommand('ai.driveUsingPath('..serialize({script=script,routeSpeed=6,routeSpeedMode='limit',aggression=.3,avoidCars='off'})..')')
    else
      record.driveSkipped='no continuing lane path'
    end
    view(vec3(case.point)-vec3(case.direction)*14+vec3(0,0,9),vec3(case.point)+vec3(case.direction)*25)
    nextPhase('drive')
  elseif phase == 'drive' then
    table.insert(frames,dt)
    if #record.trace == 0 or age-record.trace[#record.trace].time > .5 then
      table.insert(record.trace,{time=age,position=xyz(vehicle:getPosition()),speed=vehicle:getVelocity():length()})
      telemetry('drive_sample')
      if case.target_xy then
        local p=vehicle:getPosition()
        local d=math.sqrt((p.x-case.target_xy[1])^2+(p.y-case.target_xy[2])^2)
        record.targetDistanceMin=math.min(record.targetDistanceMin or math.huge,d)
        record.crossedTarget=record.targetDistanceMin <= (case.required_target_radius or 8)
      end
    end
    if age > (cfg.driveSeconds or 5) then
      record.finish=xyz(vehicle:getPosition()); record.distance=(vehicle:getPosition()-vec3(record.start)):length()
      telemetry('driven')
      vehicle:queueLuaCommand("ai.setMode('disabled'); input.event('throttle',0,1); input.event('parkingbrake',1,1)")
      nextPhase('after')
    end
  elseif phase == 'after' and age > 1 then
    shot('after'); nextPhase('after_saved')
  elseif phase == 'after_saved' and age > .5 then
    beginCase()
  elseif phase == 'finish' then
    result.frames=frames
    if (cfg.soakSeconds or 0) > 0 then
      -- Scripted point-survey paths use a private vehicle map without an edge
      -- index. Switching straight to random AI leaves that map installed and
      -- graphpath.getNodesFromEdgeId crashes. Restore the real map first.
      vehicle:queueLuaCommand("ai.setMode('disabled'); mapmgr.clearCustomMap(); mapmgr.requestMap()")
      nextPhase('soak_prepare')
    else
      result.status='complete'; save(); shutdown(0)
    end
  elseif phase == 'soak_prepare' and age > 3 then
      result.soak={movingSeconds=0,elapsed=0,distance=0,trace={},stalls=0,frames={}}
      -- Pool of trafficAmount vehicles, trafficActive of them simulated near the player.
      local amount=cfg.trafficAmount or 6
      result.soak.traffic={amount=amount,active=cfg.trafficActive or amount,simple=cfg.simpleTraffic or false}
      gameplay_traffic.setupTraffic(amount,{activeAmount=cfg.trafficActive or amount,simpleVehs=cfg.simpleTraffic or false})
      vehicle:queueLuaCommand("input.event('throttle',0,1); input.event('parkingbrake',0,1); ai.setMode('random'); ai.driveInLane('on'); ai.setSpeed(12); ai.setSpeedMode('limit')")
      commands.setGameCamera()
      cameraPos,cameraTarget=nil,nil
      core_camera.setByName(0,'orbit',false)
      nextPhase('soak')
  elseif phase == 'soak' then
    local s=result.soak
    s.elapsed=age
    table.insert(s.frames,dt)
    if vehicle:getVelocity():length()>1 then s.movingSeconds=s.movingSeconds+dt end
    if #s.trace==0 or age-s.trace[#s.trace].time>1 then
      local p=vehicle:getPosition()
      if #s.trace>0 then s.distance=s.distance+(p-vec3(s.trace[#s.trace].position)):length() end
      -- Traffic flow: how many active traffic vehicles move, and their mean speed.
      local moving,active,speedSum,snapshot=0,0,0,{}
      local takeSnapshot=#s.trace%30==0
      for id,v in pairs(gameplay_traffic.getTrafficData() or {}) do
        local o=getObjectByID(id)
        if o and o:getActive() then
          active=active+1; speedSum=speedSum+(v.speed or 0)
          if (v.speed or 0)>2 then moving=moving+1 end
          if takeSnapshot then
            table.insert(snapshot,{id=id,position=xyz(o:getPosition()),speed=v.speed,state=v.state,
              damage=v.damage,isAi=v.isAi})
          end
        end
      end
      if takeSnapshot then
        s.snapshots=s.snapshots or {}
        table.insert(s.snapshots,{time=age,vehicles=snapshot})
      end
      table.insert(s.trace,{time=age,position=xyz(p),speed=vehicle:getVelocity():length(),
        traffic=gameplay_traffic.getTrafficAmount(true),trafficTotal=gameplay_traffic.getTrafficAmount(),
        trafficActive=active,trafficMoving=moving,trafficMeanSpeed=active>0 and speedSum/active or 0})
      if #s.trace%10==0 then save() end
    end
    if s.movingSeconds>=cfg.soakSeconds then
      result.vehicleCount=be:getObjectCount();result.status='complete';save();shutdown(0)
    elseif age>cfg.soakSeconds*2 then
      result.status='soak_incomplete';save();shutdown(1)
    end
  end
end
function M.onUpdate(dt)
  local ok, err = xpcall(function()
    update(dt)
    if cameraPos then view(cameraPos,cameraTarget) end
  end, debug.traceback)
  if not ok then result.status='error'; result.error=tostring(err); save(); shutdown(1) end
end
return M
