-- Isolated presentation capture and bounded runtime evidence; never loaded in normal play.
local M = {}
local cfg, car, start, direction
local phase, age, total, frame, waitFrames = 'loading', 0, 0, 0, 0
local result = {status='loading', trace={}, physics={}, signalErrors={}}
local function save() jsonWriteFile('earth2road-result.json', result, true) end
local function change(p) phase, age = p, 0; result.phase=p; save() end
local function xyz(v) return {v.x,v.y,v.z} end
local function camera(pos, target)
  local q=quatFromDir(target-pos,vec3(0,0,1))
  core_camera.setPosRot(0,pos.x,pos.y,pos.z,q.x,q.y,q.z,q.w)
end
local function telemetry()
  car:queueLuaCommand([[local wheelsOut={}
    for _,w in pairs(wheels.wheels) do
      table.insert(wheelsOut,{name=w.name,contact=w.contactMaterialID1,force=w.downForceRaw,depth=w.contactDepth})
    end
    obj:queueGameEngineLua('extensions.earth2roadpromo.receive('..serialize({damage=beamstate.damage,
      speed=obj:getVelocity():length(),upZ=obj:getDirectionVectorUp().z,wheels=wheelsOut})..')')]])
end
function M.receive(data) table.insert(result.physics,data) end
function M.onInit()
  setExtensionUnloadMode(M,'manual')
  cfg=jsonReadFile('earth2road-input.json')
  save()
end
function M.onUpdate(dtReal)
  total,age=total+dtReal,age+dtReal
  if total > 1200 then result.status='timeout'; save(); shutdown(1); return end
  if phase=='loading' then
    if not getMissionFilename():find(cfg.level,1,true) or worldReadyState<2 then return end
    result.level=getMissionFilename()
    result.version=beamng_versionb
    result.loadSeconds=total
    pcall(function() extensions.ui_visibility.setCef(false) end)
    commands.setFreeCamera()
    local nodes=map.getMap().nodes
    result.navNodes=tableSize(nodes); result.navLinks=0
    for _,n in pairs(nodes) do result.navLinks=result.navLinks+tableSize(n.links) end
    if core_trafficSignals then
      local signals=core_trafficSignals.getSignals(); result.signalCount=#signals
      for _,s in ipairs(signals) do if not s.road then table.insert(result.signalErrors,s.name) end end
    end
    result.samples={}
    for _,p in ipairs(cfg.samples) do
      local hit=castRayStatic(vec3(p)+vec3(0,0,.3),vec3(0,0,-1),5.3)
      table.insert(result.samples,{point=p,error=.3-hit})
    end
    core_vehicles.replaceVehicle('etk800',{})
    change('vehicle')
  elseif phase=='vehicle' and age>8 then
    car=getPlayerVehicle(0)
    if not car then return end
    for i=be:getObjectCount()-1,0,-1 do
      local other=be:getObject(i)
      if other and other:getID()~=car:getID() then other:delete() end
    end
    start=vec3(cfg.path[1]); direction=(vec3(cfg.path[2])-start):normalized()
    local q=quat(0,0,1,0)*quatFromDir(direction,vec3(0,0,1))
    car:setPositionRotation(start.x,start.y,start.z+.65,q.x,q.y,q.z,q.w)
    car:queueLuaCommand("ai.setMode('disabled'); input.event('parkingbrake',1,1)")
    camera(start-direction*10+vec3(0,0,4),start+direction*10+vec3(0,0,1))
    gameplay_traffic.setupTraffic(5,{simpleVehs=true})
    change('settle')
  elseif phase=='settle' and age>18 then
    telemetry()
    result.spawnPosition=xyz(car:getPosition())
    result.vehicleCount=be:getObjectCount()
    result.trafficCount=tableSize(gameplay_traffic.getTrafficData())
    result.trafficStart={}
    for id,_ in pairs(gameplay_traffic.getTrafficData()) do
      local obj=be:getObjectByID(id)
      if obj then result.trafficStart[tostring(id)]=xyz(obj:getPosition()) end
    end
    createScreenshot2({filename='screenshots/earth2road-spawn',writeJPG=false,superSampling=1})
    local script={}
    for _,p in ipairs(cfg.path) do table.insert(script,{x=p[1],y=p[2],z=p[3],r=1.7,v=8}) end
    car:queueLuaCommand("input.event('parkingbrake',0,1)")
    car:queueLuaCommand('ai.driveUsingPath('..serialize({script=script,routeSpeed=8,routeSpeedMode='limit',aggression=.3,avoidCars='on'})..')')
    change('rolling')
  elseif phase=='rolling' and age>2 then
    be:setPhysicsRunning(false)
    change('step')
  elseif phase=='step' then
    if frame>=(cfg.frames or 360) then be:setPhysicsRunning(true); change('finish'); return end
    -- Frame-stepped capture for an accelerated preview. These are engine step units,
    -- not a claim that a movie frame represents 1/30 second of simulation.
    be:physicsStep(frame%3==0 and 66 or 67)
    waitFrames=0
    change('camera')
  elseif phase=='camera' then
    waitFrames=waitFrames+1
    local p=car:getPosition()
    local d=car:getDirectionVector(); d.z=0; d:normalize()
    camera(p-d*9+vec3(0,0,3.4),p+d*14+vec3(0,0,1.1))
    if waitFrames>=4 then
      createScreenshot2({filename=string.format('screenshots/promo/frame_%04d',frame),writeJPG=true,superSampling=1})
      if frame%30==0 then
        table.insert(result.trace,{frame=frame,position=xyz(p),speed=car:getVelocity():length()})
        telemetry()
      end
      change('saved')
    end
  elseif phase=='saved' then
    if FS:fileExists(string.format('/screenshots/promo/frame_%04d.jpg',frame)) then
      frame=frame+1
      change('step')
    end
  elseif phase=='finish' and age>5 then
    result.finishPosition=xyz(car:getPosition())
    result.distance=(car:getPosition()-vec3(result.spawnPosition)):length()
    result.trafficTravel={}
    for id,p in pairs(result.trafficStart) do
      local obj=be:getObjectByID(tonumber(id))
      if obj then result.trafficTravel[id]=(obj:getPosition()-vec3(p)):length() end
    end
    telemetry()
    camera(vec3(cfg.overview.pos),vec3(cfg.overview.look))
    change('overview')
  elseif phase=='overview' and age>4 then
    createScreenshot2({filename='screenshots/earth2road-overview',writeJPG=false,superSampling=1})
    result.frames=frame
    result.status='complete'
    save()
    phase='done'; age=0
  elseif phase=='done' and age>3 then shutdown(0) end
end
return M
