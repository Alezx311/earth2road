"""Collect unmodified game screenshots and render a local road-survey report."""
import argparse
import html
import json
import math
from pathlib import Path
import shutil
import statistics
from beamng_network import profile_height
from PIL import Image, ImageDraw, ImageFont


def report(profile, output):
    profile=Path(profile)/'current'
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    result=json.loads((profile/'kyiv-qa-result.json').read_text(encoding='utf8'))
    cfg=json.loads((profile/'kyiv-qa-input.json').read_text(encoding='utf8'))
    shutil.copy2(profile/'kyiv-qa-result.json',output/'result.json')
    shutil.copy2(profile/'kyiv-qa-input.json',output/'input.json')
    cases=result.get('cases') or []
    images=output/'images'; images.mkdir(exist_ok=True)
    cards=[]; overview=[]; failures=[]
    planned={c['name']:c for c in cfg['cases']}
    for case in cases:
        expected=planned.get(case['name'],{})
        physical_rays=case.get('probe',{}).get('rays') or case.get('rays') or []
        ray=(physical_rays or [{}])[0]
        wheels=case.get('settled',{}).get('wheels') or []
        contacts=sum((w.get('force') or 0)>10 for w in wheels)
        distance=case.get('distance',0)
        issues=[]
        if abs(ray.get('error',999))>.02: issues.append('колізія >2 см')
        if contacts<3: issues.append('контакт <3 коліс')
        minimum=10 if result.get('version',2)>=3 else 3
        if distance<minimum: issues.append(f'проїзд <{minimum} м')
        if case.get('driveSkipped'): issues.append('проїзд пропущений')
        if not case.get('settled') or not case.get('driven'): issues.append('немає телеметрії')
        if case.get('driven',{}).get('damage',0)-case.get('settled',{}).get('damage',0)>1:
            issues.append('нові пошкодження авто')
        # A normal settle costs <600; a fall from a wrong spawn height costs >10 000.
        if case.get('settled',{}).get('damage',0)>1000:
            issues.append('пошкодження під час посадки')
        expected_rays=expected.get('expectedRays',[])
        wheel_errors=[]
        if result.get('version',2)>=3 and expected.get('path'):
            for wheel in wheels:
                centre=wheel.get('centre')
                if centre is not None and wheel.get('radius') is not None:
                    wheel_errors.append(centre[2]-wheel['radius']-profile_height(expected['path'],*centre[:2]))
            if len(wheel_errors)!=4 or max(map(abs,wheel_errors),default=999)>.20:
                issues.append('колеса не на дорожній поверхні')
        ignored_zero_rays=[]
        for i, wanted in enumerate(expected_rays):
            rays=physical_rays
            if i>=len(rays) or wanted is None or abs(rays[i]['error']-wanted)>.02:
                # Both ray APIs return the graphics z=0 plane after native terrain
                # has removed it from vehicle collision. Actual wheel support is
                # mandatory evidence before treating this ray as non-physical.
                if (result.get('terrains') and i<len(rays) and wheel_errors and
                        max(map(abs,wheel_errors))<=.20 and contacts>=3 and
                        abs(case['point'][2]+rays[i]['error'])<.001):
                    ignored_zero_rays.append(i+1)
                else:
                    issues.append(f'промінь {i+1} не збігається з геометрією')
        if not wheel_errors and abs(case.get('spawnSurface',case.get('topHit',case['point'][2]))-case['point'][2])>.08:
            issues.append('спавн на сторонній поверхні')
        case['wheel_height_errors']=wheel_errors
        case['nonphysical_zero_rays']=ignored_zero_rays
        shots=[]
        for name in case.get('shots',[]):
            source=profile/'screenshots/road-qa'/f'{name}.png'
            if not source.exists():
                issues.append('немає кадру '+name)
                continue
            shutil.copy2(source,images/source.name)
            shots.append(f'<a href="images/{source.name}"><img loading="lazy" src="images/{source.name}" alt="{html.escape(name)}"></a>')
            if name.endswith('-overview'): overview.append((name,source))
        if len(shots)!=3: issues.append('неповний набір кадрів')
        if issues: failures.append({'name':case['name'],'issues':issues})
        cards.append(f'<article id="{case["name"]}"><h2>{html.escape(case["name"])}</h2>'
                     f'<p>Смуга {html.escape(case["lane"])} · похибка {ray.get("error",999):.3f} м · '
                     f'контакт {contacts}/4 · проїзд {distance:.1f} м</p>'
                     f'<p>{html.escape(", ".join(issues) or "Автоматичні пороги пройдено; кадри потребують візуального огляду.")}</p>'
                     f'<div class="shots">{"".join(shots)}</div></article>')
    frames=result.get('frames') or []
    def metrics(frames):
        return {'median_ms':round(statistics.median(frames)*1000,2),
                'p95_ms':round(sorted(frames)[min(len(frames)-1,int(len(frames)*.95))]*1000,2)} if frames else {}
    if result.get('caseVehicleCount') not in (None,1):
        failures.append({'name':'scene','issues':[f'сторонні авто в сцені: {result["caseVehicleCount"]}']})
    missing=sorted(set(planned)-{c['name'] for c in cases})
    failures.extend({'name':name,'issues':['сценарій не виконаний']} for name in missing)
    summary={'status':result['status'],'passed':result['status']=='complete' and not failures,
             'cases':len(cases),'planned_cases':len(cfg['cases']),
             'screenshots':sum(len(c.get('shots',[])) for c in cases),
             'nav_nodes':result.get('navNodes'),'nav_links':result.get('navLinks'),
             'signal_errors':len(result.get('signalErrors') or []),
             'survey_frames':metrics(frames),'failures':failures}
    if result.get('soak'):
        s=result['soak'];summary['soak']={k:s.get(k) for k in ('movingSeconds','elapsed','distance','stalls')}
        summary['soak']['frames']=metrics(s['frames'])
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    if cases:
        xs=[c['point'][0] for c in cases];ys=[c['point'][1] for c in cases]
        scale=650/max(max(xs)-min(xs),max(ys)-min(ys),1)
        dots=[]
        for i,c in enumerate(cases):
            x=30+(c['point'][0]-min(xs))*scale;y=680-(c['point'][1]-min(ys))*scale
            dots.append(f'<a href="#{c["name"]}"><circle cx="{x}" cy="{y}" r="8"/><text x="{x+10}" y="{y+4}">{i:02d}</text><title>{html.escape(c["name"])}</title></a>')
        svg=f'<svg viewBox="0 0 720 720" aria-label="Контрольні точки, північ угорі">{"".join(dots)}</svg>'
    else: svg=''
    content='<!doctype html><html lang="uk"><meta charset="utf-8"><title>Академ — аудит доріг</title>'
    content+='<style>body{font:16px system-ui;background:#141921;color:#e4ebf3;margin:28px}h1,h2{color:#93d6ff}article{border-top:1px solid #465365;padding:20px 0}.shots{display:flex;gap:8px}.shots a{width:33%}img{width:100%}svg{max-width:650px;background:#222b37}circle{fill:#71c4ee}text{fill:white;font:12px sans-serif}pre{white-space:pre-wrap}a{color:#93d6ff}</style>'
    content+='<h1>Академмістечко — перевірка доріг</h1><p>Оригінальні кадри BeamNG. Числові пороги не замінюють візуальний огляд. Північ на схемі вгорі.</p>'
    content+=f'<pre>{html.escape(json.dumps({k:v for k,v in summary.items() if k!="failures"},ensure_ascii=False,indent=2))}</pre>'+svg+''.join(cards)
    (output/'index.html').write_text(content,encoding='utf8')
    if overview:
        sheet=Image.new('RGB',(1280,205*math.ceil(len(overview)/4)),(20,25,33));draw=ImageDraw.Draw(sheet)
        for i,(name,path) in enumerate(overview):
            with Image.open(path) as im:
                im.thumbnail((320,180));sheet.paste(im,((i%4)*320,(i//4)*205))
            draw.text(((i%4)*320+4,(i//4)*205+182),name,fill='white')
        sheet.save(output/'contact-sheet.jpg',quality=90)
    print(json.dumps({k:v for k,v in summary.items() if k!='failures'},ensure_ascii=False))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('profile',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();report(a.profile,a.output)
