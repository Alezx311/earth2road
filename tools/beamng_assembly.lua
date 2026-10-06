-- Isolated presentation replay. Original geometry is restored before final frames.
local M = {}
local cfg, parts, frame, phase, age, total, waits = nil, {}, 0, 'loading', 0, 0, 0
local result = {status='loading', missing={}, stages={}}
local windows = {roads={3.2,9.5,5}, transitions={9,11.5,4}, core={11.2,12,4},
                 walks={12.4,16.8,2}, marks={16.5,18.4,0.6}, buildings={18.2,20.2,12}, props={19.4,21,7}}
local function save() jsonWriteFile('earth2road-assembly-result.json',result,true) end
local function change(p) phase=p; age=0 end
local function ease(x) x=math.max(0,math.min(1,x)); return x*x*(3-2*x) end
local function camera(t)
  if cfg.views then
    local view=cfg.views[math.min(#cfg.views,math.floor(t)+1)]
    local pos,target=vec3(view.pos),vec3(view.look)
    local q=quatFromDir(target-pos,vec3(0,0,1))
    core_camera.setPosRot(0,pos.x,pos.y,pos.z,q.x,q.y,q.z,q.w)
    return
  end
  local c=vec3(cfg.center)
  local heading=math.rad(cfg.heading or -65)
  local distance=cfg.distance or 150
  if t>=21 then heading=heading+math.rad(12)*ease((t-21)/4) end
  if cfg.kind=='street' then c.x=c.x+((t>=21) and 35*ease((t-21)/4) or 0) end
  local pos=c+vec3(math.cos(heading)*distance,math.sin(heading)*distance,(cfg.height or 100))
  local q=quatFromDir(c-pos,vec3(0,0,1))
  core_camera.setPosRot(0,pos.x,pos.y,pos.z,q.x,q.y,q.z,q.w)
end
local function place(t)
  for _,p in ipairs(parts) do
    local w=windows[p.stage]
    local wave
    if cfg.kind=='street' then wave=math.max(0,math.min(1,(p.center[1]-cfg.center[1]+cfg.radius)/(2*cfg.radius)))
    else wave=math.min(1,(vec3(p.center[1],p.center[2],0)-vec3(cfg.center[1],cfg.center[2],0)):length()/cfg.radius) end
    local at=w[1]+wave*(w[2]-w[1])
    local progress=t<3 and 1 or ease((t-at)/0.65)
    if progress==0 then p.object:setHidden(true)
    else
      p.object:setPosition(vec3(p.position)+vec3(0,0,w[3]*(1-progress)))
      p.object:setHidden(false)
    end
  end
  -- Forests are engine batches: show them once scenery is complete.
  for _,name in ipairs(scenetree.findClassObjects('Forest')) do
    local obj=scenetree.findObject(name)
    if obj then obj:setHidden(#parts>0 and t>=3 and t<20.5) end
  end
end
function M.onInit()
  setExtensionUnloadMode(M,'manual')
  cfg=jsonReadFile('earth2road-assembly.json'); save()
end
function M.onUpdate(dt)
  total=total+dt; age=age+dt
  if total>1700 then result.status='timeout'; save(); shutdown(1); return end
  if phase=='loading' then
    if not getMissionFilename():find(cfg.level,1,true) or worldReadyState<2 then return end
    commands.setFreeCamera()
    pcall(function() extensions.ui_visibility.setCef(false) end)
    be:setPhysicsRunning(false)
    for i=be:getObjectCount()-1,0,-1 do local v=be:getObject(i); if v then v:delete() end end
    for _,p in ipairs(cfg.parts) do
      p.object=scenetree.findObject(p.name)
      if p.object then table.insert(parts,p) else table.insert(result.missing,p.name) end
    end
    result.version=beamng_versionb; result.objects=#parts
    if #result.missing>0 then result.status='missing_objects'; save(); shutdown(1); return end
    result.status='capturing'; save()
    camera(0); place(0); change('warmup')
  elseif phase=='warmup' and age>12 then change('pose')
  elseif phase=='pose' then
    local count=cfg.sample_times and #cfg.sample_times or cfg.frames
    if frame>=count then
      place(25); result.frames=frame; result.status='complete'; save(); change('done'); return
    end
    local t=cfg.sample_times and cfg.sample_times[frame+1] or frame/cfg.fps
    camera(t); place(t); waits=0; change('render')
  elseif phase=='render' then
    waits=waits+1
    if waits>=4 and (not cfg.views or age>3) then
      createScreenshot2({filename=string.format('screenshots/assembly/frame_%04d',frame),writeJPG=true,superSampling=1})
      change('saved')
    end
  elseif phase=='saved' then
    if FS:fileExists(string.format('/screenshots/assembly/frame_%04d.jpg',frame)) then
      frame=frame+1
      if frame%75==0 then result.frame=frame; save() end
      change('pose')
    end
  elseif phase=='done' and age>3 then shutdown(0) end
end
return M
