#!/usr/bin/env python3
"""Reproducible generation/cache matrix and surface comparison; see docs/STREAMING.md."""
import argparse
import json
import math
import os
import platform
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from akadem_maps.context import read_json, write_json
from akadem_maps.streaming_probe import StageClock, acceptance, compare_surfaces, square


def sumo_ready(export, mid):
    """Separate SUMO process with the exported routes, 100 cars, 3 s warm-up."""
    import traci
    from akadem_maps.runtime import sumo_binary
    import random
    build = export / 'data/build' / mid
    routes = read_json(build / 'routes.json')
    if not routes:
        raise ValueError('No traffic routes: cannot declare traffic ready')
    label = 'streaming-probe'
    traci.start([str(sumo_binary('sumo')), '-n', str(build / 'network.net.xml'),
                 '--step-length', '.1', '--seed', '311', '--no-step-log', 'true',
                 '--duration-log.disable', 'true', '--time-to-teleport', '-1'], label=label)
    c = traci.getConnection(label)
    try:
        rng = random.Random(311)
        for i, edges in enumerate(routes):
            c.route.add(str(i), edges)
        for i in range(100):
            c.vehicle.add(f'probe{i}', str(rng.randrange(len(routes))), departPos='random_free', departSpeed='max')
        collisions = teleports = 0
        for _ in range(30):
            c.simulationStep()
            collisions += c.simulation.getCollidingVehiclesNumber()
            teleports += c.simulation.getStartingTeleportNumber()
        return {'vehicles': len(c.vehicle.getIDList()), 'pending': len(c.simulation.getPendingVehicles()),
                'collisions': collisions, 'teleports': teleports, 'warmup_simulated_s': 3.,
                'bridge_protocol_verified': False, 'demand': 'synthetic benchmark demand'}
    finally:
        c.close()


def run_case(job):
    from akadem_maps.world import build_world, validate_world
    from akadem_maps.adapters.godot.export import export_world
    out = Path(job['output'])
    started = time.perf_counter()
    report = {'status': 'running', 'mode': job['mode'], 'config': job['config'],
              'traffic': None, 'collision': None}
    with (out / 'events.jsonl').open('w', encoding='utf8', buffering=1) as events:
        timer = StageClock(lambda row: events.write(json.dumps(row) + '\n'))
        try:
            if job['mode'] == 'geometry':
                world, export = Path(job['world']), Path(job['export'])
                timer.emit('stage', stage='geometry_cache_validation')
                validate_world(world)
            else:
                world, export = out / 'world', out / 'godot'
                build_world(job['config'], world, cache=job.get('cache'), inputs=job.get('inputs'),
                            config_root=job.get('config_root', ROOT),
                            offline=job['mode'] == 'source', emit=timer.emit)
                timer.emit('stage', stage='godot_export_and_demand')
                export_world(world, export, offline=True)
            report.update(world=str(world), export=str(export))
            timer.emit('stage', stage='sumo_start_and_warmup')
            report['traffic'] = sumo_ready(export, job['config']['id'])
            if job.get('godot'):
                timer.emit('stage', stage='godot_process_and_spawn_collision')
                env = {**os.environ, 'E2R_PROBE_FOLDER': str(export / 'game/data' / job['config']['id'])}
                result = subprocess.run([job['godot'], '--headless', '--path', str(ROOT / 'game'),
                    '--script', 'res://scripts/probe_stream_start.gd'], env=env, capture_output=True, text=True, timeout=120)
                (out / 'godot.log').write_text(result.stdout + result.stderr, encoding='utf8')
                rows = [line.removeprefix('STREAM_START ') for line in result.stdout.splitlines() if line.startswith('STREAM_START ')]
                if result.returncode or not rows:
                    raise RuntimeError('Godot spawn probe failed; see godot.log')
                report['collision'] = json.loads(rows[-1])
            report['status'] = 'completed'
        except Exception as exc:
            report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
            traceback.print_exc()
        finally:
            report['stages_s'] = timer.finish()
            report['elapsed_s'] = time.perf_counter() - started
            report['acceptance'] = acceptance(report['elapsed_s'], report['collision'], report['traffic'], job['mode'])
            write_json(out / 'result.json', report)
    return 0 if report['status'] == 'completed' else 1


def terminate_tree(process):
    # Kill only the worker owned by this run and its netconvert/SUMO/Godot children.
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def launch(job, timeout):
    out = Path(job['output'])
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'job.json', job)
    started = time.perf_counter()
    with (out / 'worker.log').open('w', encoding='utf8') as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_case', str(out / 'job.json')],
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != 'nt')
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_tree(process)
            code = None
        except BaseException:
            terminate_tree(process)
            raise
    elapsed = time.perf_counter() - started
    if (out / 'result.json').exists():
        report = read_json(out / 'result.json')
    else:
        rows = []
        if (out / 'events.jsonl').exists():
            for line in (out / 'events.jsonl').read_text(encoding='utf8').splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # killed during a final write
        stages = [r for r in rows if r['event'] == 'stage']
        last = stages[-1] if stages else {'stage': 'setup', 'elapsed_s': 0}
        report = {'status': 'timeout' if code is None else 'failed', 'mode': job['mode'],
                  'last_stage': last['stage'],
                  'last_stage_lower_bound_s': (time.perf_counter() - last['monotonic_s']) if 'monotonic_s' in last else None,
                  'completed_stages_s': {r['stage']: stages[i + 1]['elapsed_s'] - r['elapsed_s']
                                         for i, r in enumerate(stages[:-1])},
                  'acceptance': acceptance(elapsed, None, None, job['mode'])}
    report['wall_s_including_process'] = elapsed
    report['acceptance']['pipeline_within_30s'] &= elapsed <= 30
    report['worker_exit'] = code
    write_json(out / 'result.json', report)
    return report


def benchmark(args):
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError('timeout must be positive and finite')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    spec = read_json(args.suite)
    results = []
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    from akadem_maps.context import sha256
    metadata = {'revision': revision, 'platform': platform.platform(), 'python': sys.version,
                'cpu': platform.processor(), 'logical_cpus': os.cpu_count(),
                'suite_sha256': sha256(args.suite), 'timeout_s': args.timeout,
                'probe_sha256': {name: sha256(ROOT / name) for name in
                    ('tools/streaming_probe.py', 'akadem_maps/streaming_probe.py',
                     'akadem_maps/core/prepare.py', 'game/scripts/world_stream.gd',
                     'game/scripts/probe_stream_start.gd')},
                'working_tree_dirty': bool(subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT,
                                          capture_output=True, text=True).stdout.strip()),
                'streaming_release': False}
    cases = [case for case in spec['cases'] if not args.only or case['config']['id'] in args.only]
    if not cases:
        raise ValueError('No matching cases')
    for case in cases:
        cfg = case['config']
        # validate map ids before they are used in filesystem names
        from akadem_maps.world import validate_config
        validate_config(dict(cfg))
        completed = None
        for mode in args.modes:
            path = output / (cfg['id'] + '-' + mode)
            job = {'output': str(path), 'config': cfg, 'mode': mode,
                   'config_root': str(Path(args.config_root).resolve()),
                   'godot': str(Path(args.godot).resolve()) if args.godot else None}
            if mode == 'cold':
                if any(cfg.get(k) for k in ('osm_file', 'package', 'geofabrik')) or case.get('inputs'):
                    raise ValueError('Cold cases must acquire fresh sources, without osm_file/package/geofabrik/inputs')
                job['cache'] = str(path / 'cache')
            elif mode == 'source':
                if case.get('inputs'):
                    job['inputs'] = str(Path(case['inputs']).resolve())
                elif args.source_run:
                    job['cache'] = str(Path(args.source_run).resolve() / (cfg['id'] + '-cold/cache'))
                elif args.source_cache:
                    job['cache'] = str(Path(args.source_cache).resolve())
                elif (output / (cfg['id'] + '-cold/cache')).exists():
                    job['cache'] = str(output / (cfg['id'] + '-cold/cache'))
                else:
                    raise ValueError('Source mode requires --source-cache, case inputs, or preceding cold run')
            else:
                if not completed and args.geometry_run:
                    ready = Path(args.geometry_run).resolve() / (cfg['id'] + '-source/result.json')
                    if ready.exists() and read_json(ready).get('status') == 'completed':
                        completed = read_json(ready)
                if not completed:
                    results.append({'id': cfg['id'], 'mode': mode, 'status': 'not_run',
                                    'reason': 'No completed geometry/export from preceding cache modes'})
                    continue
                if completed.get('config') != cfg:
                    raise ValueError('Cached geometry was built with a different case configuration')
                job.update(world=completed['world'], export=completed['export'])
            print(f"{cfg['id']} {mode}: started", flush=True)
            result = launch(job, args.timeout)
            result.update(id=cfg['id'], mode=mode, category=case.get('category'), size_m=case.get('size_m'))
            if result['status'] == 'completed':
                completed = result
            results.append(result)
            write_json(output / 'report.json', {**metadata, 'results': results})
            print(f"{cfg['id']} {mode}: {result['status']} {result['wall_s_including_process']:.2f}s", flush=True)
    write_json(output / 'report.json', {**metadata, 'results': results})
    return 0 if all(r['status'] == 'completed' for r in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    bench = sub.add_parser('benchmark')
    bench.add_argument('--suite', required=True)
    bench.add_argument('--output', required=True)
    bench.add_argument('--modes', nargs='+', choices=['cold', 'source', 'geometry'], default=['cold', 'source', 'geometry'])
    bench.add_argument('--source-cache')
    bench.add_argument('--source-run', help='Reuse each case cache from a preceding cold benchmark directory')
    bench.add_argument('--geometry-run', help='Reuse a completed source result from another benchmark')
    bench.add_argument('--only', nargs='+', help='Selected case ids')
    bench.add_argument('--config-root', default=str(ROOT))
    bench.add_argument('--godot')
    bench.add_argument('--timeout', type=float, default=300)
    case = sub.add_parser('_case')
    case.add_argument('job')
    seams = sub.add_parser('seams')
    seams.add_argument('--reference', required=True)
    seams.add_argument('--candidate', required=True)
    seams.add_argument('--bbox', nargs=4, type=float)
    seams.add_argument('--output', required=True)
    seams.add_argument('--step', type=float, default=2.)
    matrix = sub.add_parser('matrix', help='Write the 500/1000/2000 m city/suburb/rural suite')
    matrix.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == '_case':
        return run_case(read_json(args.job))
    if args.command == 'benchmark':
        return benchmark(args)
    if args.command == 'matrix':
        cases = []
        for category, lon, lat in [('city', 30.5235, 50.452), ('suburb', 30.351191, 50.462441),
                                   ('rural', 30.141, 50.375)]:
            for size in (500, 1000, 2000):
                cfg = {'id': f'{category}_{size}', 'name': f'Streaming probe {category} {size} m',
                       'bbox': square(lon, lat, size), 'center': [lon, lat], 'terrain_zoom': 12,
                       'region_profile': 'ukraine', 'source_kind': 'osm', 'seed': 311,
                       'road_geometry': {'mode': 'v2'}}
                cases.append({'category': category, 'size_m': size, 'config': cfg})
        if Path(args.output).exists():
            raise FileExistsError(args.output)
        write_json(args.output, {'cases': cases, 'category_note': 'Manually selected representative sites, not a global sample'})
        return 0
    result = compare_surfaces(args.reference, args.candidate, args.bbox, args.step)
    write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
