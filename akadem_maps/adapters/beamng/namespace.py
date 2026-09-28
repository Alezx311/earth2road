"""Scope generated global resources per level, including DAE material symbols."""
import json
import re

def namespace_level(level, level_id, objects, signals):
    token=re.compile(r'\b(?:kyiv_[A-Za-z0-9_]+|Kyiv[A-Za-z0-9_]+)\b')
    def replace(match):
        name=match.group(0)
        return name if name==level_id or name.startswith(level_id+'_') else level_id+'__'+name
    def text(value):
        return token.sub(replace,value)
    # Own text assets only. Shared BeamNG paths never match generated kyiv names.
    for path in sorted(level.rglob('*')):
        if path.is_file() and path.suffix in ('.json','.dae'):
            path.write_text(text(path.read_text(encoding='utf8')),encoding='utf8')
    for path in sorted(level.rglob('*')):
        if not path.is_file():
            continue
        name=text(path.name)
        if name!=path.name:
            path.rename(path.with_name(name))
    return json.loads(text(json.dumps(objects))),json.loads(text(json.dumps(signals)))
