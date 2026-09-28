"""Stable CLI and JSONL event protocol for a future GUI."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import traceback
from . import __version__
from .context import read_json

class Events:
    def __init__(self, destination):
        self.stream = sys.stdout if destination == '-' else open(destination, 'a', encoding='utf8') if destination else None
        self.owned = bool(destination and destination != '-')
    def emit(self, event, **data):
        record={'event':event,'time':datetime.now(timezone.utc).isoformat(),**data}
        if self.stream:
            self.stream.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
            self.stream.flush()
        print(f'[{event}] '+json.dumps(data,ensure_ascii=False), file=sys.stderr,flush=True)
    def close(self):
        if self.owned:
            self.stream.close()

def doctor():
    from .runtime import sumo_binary
    checks={name:importlib.util.find_spec(name) is not None for name in ('numpy','shapely','PIL','pyproj','sumolib','osmium','requests')}
    try:
        checks['netconvert']=str(sumo_binary('netconvert'))
    except FileNotFoundError:
        checks['netconvert']=False
    return {'version':__version__,'python':sys.version.split()[0],'checks':checks,'ok':all(checks.values()),'install':'pip install ".[generator]" (from a checkout)'}

def parser():
    p=argparse.ArgumentParser(prog='terra-drive')
    p.add_argument('--version',action='version',version=__version__)
    sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('doctor')
    b=sub.add_parser('build')
    source=b.add_mutually_exclusive_group(required=True)
    source.add_argument('--config',type=Path)
    source.add_argument('--bbox',nargs=4,type=float,metavar=('WEST','SOUTH','EAST','NORTH'))
    b.add_argument('--id'); b.add_argument('--name'); b.add_argument('--output',type=Path,required=True)
    b.add_argument('--region-profile',choices=('ukraine','experimental'))
    b.add_argument('--seed',type=int)
    b.add_argument('--cache',type=Path,help='Directory containing raw OSM and terrain inputs')
    b.add_argument('--inputs',type=Path,help='Prepared input bundle with manifest.json')
    b.add_argument('--offline',action='store_true')
    e=sub.add_parser('export')
    e.add_argument('--target',choices=('godot','beamng'),required=True)
    e.add_argument('--world',type=Path,required=True);e.add_argument('--output',type=Path,required=True)
    e.add_argument('--overrides',type=Path);e.add_argument('--offline',action='store_true')
    e.add_argument('--level-id')
    i=sub.add_parser('install',help='Copy a Godot export into a game checkout (explicit, never implicit)')
    i.add_argument('--target',choices=('godot',),required=True)
    i.add_argument('--export',type=Path,required=True);i.add_argument('--root',type=Path,default=Path.cwd())
    i.add_argument('--replace',action='store_true',help='Back up an installed map with the same id, then replace it')
    i.add_argument('--activate',action='store_true',help='Also write game/data/active_map')
    c=sub.add_parser('capture',help='Record World Editor changes of an installed level for the next export')
    c.add_argument('--target',choices=('beamng',),required=True)
    c.add_argument('--level',type=Path,required=True,help='Saved level folder, e.g. <BeamNG user>/levels/<level_id>')
    c.add_argument('--export',type=Path,required=True,help='Export folder the level came from (reads reports/kyiv-baseline.json)')
    c.add_argument('--output',type=Path,required=True)
    v=sub.add_parser('validate')
    v.add_argument('--target',choices=('world','beamng'),required=True);v.add_argument('--input',type=Path,required=True)
    for cmd in (d,b,e,i,c,v):
        cmd.add_argument('--events',help='JSONL file or - for stdout; human log goes to stderr')
    return p

def main(argv=None):
    args=parser().parse_args(argv)
    events=Events(args.events)
    def cancel(_sig,_frame):
        raise KeyboardInterrupt
    previous=signal.signal(signal.SIGTERM,cancel)
    try:
        events.emit('stage',stage=args.command,progress=0)
        with redirect_stdout(sys.stderr):
            if args.command=='doctor':
                result=doctor()
                events.emit('result',**result)
                return 0 if result['ok'] else 1
            if args.command=='build':
                from .world import build_world
                cfg=read_json(args.config) if args.config else {'id':args.id,'name':args.name,'bbox':args.bbox}
                for name in ('id','name','seed','region_profile'):
                    if getattr(args,name) is not None:
                        cfg[name]=getattr(args,name)
                config_root=args.config.resolve().parent if args.config else Path.cwd()
                if config_root.name=='config':
                    config_root=config_root.parent
                build_world(cfg,args.output,config_root=config_root,cache=args.cache,inputs=args.inputs,offline=args.offline,emit=events.emit)
                return 0
            if args.command=='export':
                if args.target=='godot':
                    from .adapters.godot.export import export_world
                    result=export_world(args.world,args.output,offline=args.offline)
                else:
                    from .adapters.beamng.export import export_world
                    result=export_world(args.world,args.output,overrides=args.overrides,level_id=args.level_id)
            elif args.command=='capture':
                from .adapters.beamng.export_beamng import capture_edits
                if args.output.exists():
                    raise FileExistsError(f'Output already exists: {args.output}')
                count=capture_edits(args.level,args.output,args.export/'reports/kyiv-baseline.json')
                result={'output':str(args.output.resolve()),'changed_objects':count}
            elif args.command=='install':
                from .adapters.godot.install import install_export
                result=install_export(args.export,args.root,replace=args.replace,activate=args.activate)
            else:
                if args.target=='world':
                    from .world import validate_world
                    result=validate_world(args.input)
                else:
                    from .adapters.beamng.export import validate_export
                    result=validate_export(args.input)
        events.emit('result',**result)
        return 0
    except KeyboardInterrupt:
        events.emit('error',code='cancelled',message='Build cancelled; no partial output published')
        return 130
    except Exception as exc:
        if os.environ.get('AKADEM_MAPS_TRACEBACK'):
            traceback.print_exc()
        events.emit('error',code=type(exc).__name__,message=str(exc))
        return 1
    finally:
        signal.signal(signal.SIGTERM,previous)
        events.close()
