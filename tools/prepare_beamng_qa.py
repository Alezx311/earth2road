"""Stage a generated mod in an isolated user directory; never touch normal saves.

BeamNG uses <userpath>/current as the live profile root, so mods, settings and the
QA input file are staged there. Pass -userpath without embedded quotes: quoting the
value inside the argument makes the game abort with 0x03000004
(Failed to create user directory). The extension is started with -onLevelLoad_ext,
not -lua: -lua runs about 1.5 s before the mod manager mounts mods/unpacked, so
extensions.load would report the extension as unavailable. -windowed crashes
0.39.4 in its own parseArgs (setFullScreen is nil), so runs are fullscreen.
"""
import argparse
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def views(index, manifest):
    """Free-camera vantage points for the screenshots: spawn, a signalled junction,
    the widest road and an overview of the whole export."""
    from beamng_geometry import beam_point
    spawn=beam_point(index['spawn']['position'])
    result=[{'name':'spawn','pos':[spawn[0]+26,spawn[1]-34,spawn[2]+22],'look':spawn}]
    lanes={v['id']:v for v in index['lanes']}
    for signal in index.get('signals',[])[:1]:
        p=beam_point(signal['position'])
        result.append({'name':'signal','pos':[p[0]+18,p[1]-22,p[2]+12],'look':p})
    widest=max(lanes.values(), key=lambda v:(v['width'], len(v['points'])))
    p=beam_point(widest['points'][len(widest['points'])//2])
    result.append({'name':'street','pos':[p[0]+8,p[1]-14,p[2]+6],'look':p})
    x0,y0,x1,y1=manifest['bounds']
    centre=[(x0+x1)/2,(y0+y1)/2,spawn[2]]
    span=max(x1-x0,y1-y0)
    pull=min(2500, max(700, span*0.12))
    alt=min(1800, max(520, span*0.08))
    result.append({'name':'overview','pos':[centre[0],centre[1]-pull,spawn[2]+alt],'look':centre})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('build',type=Path)
    p.add_argument('--userpath',type=Path,required=True)
    p.add_argument('--survey',type=Path,help='Road audit JSON with deterministic vehicle cases')
    p.add_argument('--case-limit',type=int)
    p.add_argument('--drive-seconds',type=float,default=5)
    p.add_argument('--match-current',action='store_true',help='Keep survey XY views, update lane height/path from current snapshot')
    p.add_argument('--soak-seconds',type=float,default=0,help='Moving time with six AI after the point survey')
    p.add_argument('--traffic-amount',type=int,default=6,help='Soak traffic pool size')
    p.add_argument('--traffic-active',type=int,help='Soak traffic simulated at once (default: whole pool)')
    p.add_argument('--simple-traffic',action='store_true',help='Soak with simplified traffic vehicles')
    p.add_argument('--soak-at',help='Case name to run last, so the soak starts there')
    p.add_argument('--resolution',default='1280 720')
    p.add_argument('--world',type=Path,help='World folder of a public export (earth2road export output)')
    args=p.parse_args()
    public=(args.build/'artifact.json').exists()
    if public:
        # earth2road export: test the final ZIP itself; manifest sits in reports/.
        if not args.world: raise SystemExit('--world is required for an earth2road export')
        artifact=json.loads((args.build/'artifact.json').read_text(encoding='utf8'))
        level=args.build/'mod/levels'/artifact['level_id']
        manifest=json.loads((args.build/'reports/kyiv-manifest.json').read_text(encoding='utf8'))
        data_dir=args.world
    else:
        level=next((args.build/'levels').iterdir())
        manifest=json.loads((level/'kyiv-manifest.json').read_text(encoding='utf8'))
        data_dir=ROOT/'game/data'/manifest['map']
    user=args.userpath.resolve()
    if user.exists(): raise SystemExit('Use a fresh isolated user directory')
    profile=user/'current'
    profile.mkdir(parents=True)
    target=profile/'mods/unpacked/kyiv_qa'
    if public:
        target.mkdir(parents=True)
        shutil.copy2(args.build/artifact['zip'],profile/'mods'/artifact['zip'])
    else:
        shutil.copytree(args.build,target)
    lua=target/'lua/ge/extensions/kyivqa.lua'; lua.parent.mkdir(parents=True)
    shutil.copy2(ROOT/'tools'/('beamng_road_qa.lua' if args.survey else 'beamng_qa.lua'),lua)
    index=json.loads((data_dir/'index.json').read_text(encoding='utf8'))
    from beamng_geometry import beam_point
    samples=[beam_point(index['spawn']['position'])]
    for lane in index['lanes'][::max(1,len(index['lanes'])//300)]:
        samples.append(beam_point(lane['points'][len(lane['points'])//2]))
    tiles=int(manifest.get('counts',{}).get('tiles') or 0)
    timeout=300 if tiles < 50 else 900 if tiles < 200 else 1800
    data = {'level':level.name,'samples':samples,'views':views(index,manifest),'timeout':timeout}
    dz=manifest.get('vertical_offset',0)
    data['samples']=[[p[0],p[1],p[2]+dz] for p in samples]
    for view in data['views']:
        view['pos'][2]+=dz
        view['look']=list(view['look']);view['look'][2]+=dz
    if args.survey:
        survey=json.loads(args.survey.read_text(encoding='utf8'))
        cases=survey['cases'][:args.case_limit]
        if args.soak_at:
            last=[c for c in cases if c['name']==args.soak_at]
            if not last: raise SystemExit(f'No case {args.soak_at}')
            cases=[c for c in cases if c['name']!=args.soak_at]+last
        data.update(cases=cases, driveSeconds=args.drive_seconds)
        lane_lookup={lane['id']:lane for lane in index['lanes']}
        from beamng_road_audit import SurfaceIndex
        surface=SurfaceIndex(json.loads(p.read_text(encoding='utf8'))
                             for p in sorted((data_dir/'tiles').glob('*.json')))
        for case in data['cases']:
            # Seam traversals are generated from the current world and span several lanes.
            if args.match_current and case.get('category') != 'seam_traversal':
                from beamng_network import profile_height
                lane=lane_lookup.get(case['lane'])
                if lane is None:
                    raise ValueError(f'Survey lane disappeared: {case["lane"]}')
                points=[beam_point(p) for p in lane['points']]
                case['point'][2]=profile_height(points,*case['point'][:2])
                nearest=min(range(len(points)),key=lambda n:sum((points[n][k]-case['point'][k])**2 for k in (0,1)))
                case['path']=[case['point'].copy()]+[list(p) for p in points[nearest+1:]]
            hits=surface.heights(*case['point'][:2])
            above=[z-case['point'][2] for z,_ in hits if z-case['point'][2]>3]
            case['dropHeight']=min([100]+[z-.5 for z in above])
            case['expectedRays']=[max((z-case['point'][2] for z,_ in hits
                                      if -5 <= z-case['point'][2] < h),default=None)
                                  for h in (.3,2,15,100)]
            case['point'][2]+=dz
            for pt in case['path']: pt[2]+=dz
        data['soakSeconds']=args.soak_seconds
        data.update(trafficAmount=args.traffic_amount,trafficActive=args.traffic_active or args.traffic_amount,
                    simpleTraffic=args.simple_traffic)
        data['timeout']=max(timeout, len(data['cases'])*(args.drive_seconds+12)+1200+args.soak_seconds*2)
    (profile/'kyiv-qa-input.json').write_text(json.dumps(data),encoding='utf8')
    settings=profile/'settings';settings.mkdir()
    (settings/'settings.json').write_text(json.dumps({'GraphicDisplayResolutions':args.resolution,
        'GraphicFullscreen':False,'GraphicOverallQuality':'Normal','AudioMasterVol':0,
        'fpsLimitBackgroundEnabled':False,'PostFXMotionBlurEnabled':False}),encoding='utf8')
    print(user)
    print(f'-userpath {user} -level {level.name} -onLevelLoad_ext kyivqa -nosteam')

if __name__=='__main__': main()
