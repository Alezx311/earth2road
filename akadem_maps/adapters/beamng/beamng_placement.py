"""Read-only building conflicts: user explicitly chose to preserve footprints."""
from shapely.geometry import Polygon
from shapely.ops import unary_union
from akadem_maps.adapters.beamng.beamng_geometry import beam_point


def building_conflicts(building, pavement):
    points=[beam_point(p) for p in building['points']]
    footprint=Polygon([p[:2] for p in points])
    if not footprint.is_valid:
        footprint=footprint.buffer(0)
    floor=min(p[2] for p in points)
    bottom=floor+float(building.get('base',0))
    top=floor+float(building['height'])
    cuts=[]
    for i in pavement.tree.query(footprint,predicate='intersects'):
        hit=footprint.intersection(pavement.polygons[i])
        if hit.area<1e-5:
            continue
        q=hit.representative_point()
        z=pavement.z(i,q.x,q.y)
        if bottom-3.5<z<top:
            cuts.append(pavement.polygons[i])
    return footprint, unary_union(cuts), floor


def audit_building(building, pavement, audit):
    footprint,cuts,floor=building_conflicts(building,pavement)
    if cuts.is_empty:
        return [building]
    overlap=footprint.intersection(cuts).area
    if overlap<.01:
        return [building]
    fraction=overlap/max(footprint.area,1e-6)
    audit.append({'kind':'building','source':building['id'], 'action':'deferred',
                  'position':list(footprint.centroid.coords)[0], 'overlap_m2':round(overlap,3),
                  'fraction':round(fraction,5), 'reason':'user requested unchanged building footprints'})
    return [building]


# Compatibility with export jobs started before the audit-only user decision.
corrected_building = audit_building
