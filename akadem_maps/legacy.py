"""Temporary compatibility commands. Existing maps are never overwritten implicitly."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from .context import read_json
from .world import build_world

def prepare_main():
    parser=argparse.ArgumentParser(description='Build an independent world; export and activate Godot explicitly.')
    parser.add_argument('--config',default='config/akadem.json',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--install',action='store_true',help='Also export for Godot and install into game/data (refuses an installed map without --replace)')
    parser.add_argument('--replace',action='store_true',help='With --install: back up and replace an installed map with the same id')
    parser.add_argument('--activate',action='store_true',help='With --install: write game/data/active_map')
    args=parser.parse_args()
    if (args.replace or args.activate) and not args.install:
        parser.error('--replace/--activate require --install')
    cfg=read_json(args.config)
    root=Path.cwd()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    world=args.output or root/'data/worlds'/cfg['id']/stamp
    if args.install and not args.replace and (root/'game/data'/cfg['id']).exists():
        parser.error(f"game/data/{cfg['id']} is already installed; add --replace (the old copy goes to .cache/replaced/)")
    build_world(cfg,world,config_root=root,cache=root/'data/raw',offline=args.offline)
    if not args.install:
        print(f'World: {world}\nGodot: akadem-maps export --target godot --world {world} --output <dir>, '
              f'then akadem-maps install --target godot --export <dir> [--replace] [--activate]')
        return
    from .adapters.godot.export import export_world
    from .adapters.godot.install import install_export
    export=world.parent/(world.name+'-godot')
    export_world(world,export,offline=args.offline)
    print(install_export(export,root,replace=args.replace,activate=args.activate))
