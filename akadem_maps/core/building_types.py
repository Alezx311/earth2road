"""Typical models by building type (HANDOFF 2026-10-06: churches, fuel stations, shops).

A footprint OSM types as a church, mosque, fuel canopy or large shop, but maps
with no 3D detail, is drawn with a recognizable typical form: a hipped nave with
a drum and onion dome, a bell tower or spire, a minaret, a raised canopy on
posts, tall single-storey retail halls. The form is extra building records with
the same fields as S3DB parts (``base``, ``roof_triangles``), so both adapters
draw it without new code.

Everything here is derived, never observed: each record carries
``typical = {kind, provenance: 'derived:typical_model', version}``. OSM wins:
mapped parts, ``roof:shape`` and tagged colours/heights are kept, and a model
that does not fit the footprint falls back to the plain block with a reason.

Coordinates are world X/Y/Z metres (Y up); footprints are (x, z) polygons.
"""
import math

from shapely.geometry import Point, Polygon, box
from shapely.affinity import rotate, translate

from . import local_dna, osm_buildings

VERSION = 1
PROVENANCE = 'derived:typical_model'
KINDS = ('church_orthodox', 'church_western', 'mosque', 'fuel_canopy', 'mall', 'retail')
WORSHIP_BUILDINGS = {'church', 'cathedral', 'chapel', 'mosque', 'temple', 'basilica'}
ORTHODOX = {'orthodox', 'russian_orthodox', 'ukrainian_orthodox', 'greek_orthodox', 'serbian_orthodox',
            'romanian_orthodox', 'bulgarian_orthodox', 'georgian_orthodox', 'ukrainian_greek_catholic',
            'old_believers'}
RETAIL_BUILDINGS = {'retail', 'supermarket'}
RETAIL_SHOPS = {'supermarket', 'department_store', 'doityourself', 'hardware', 'furniture', 'wholesale'}
RETAIL_MIN_AREA_M2 = 300.0
MALL_MIN_AREA_M2 = 1500.0
# Storey height of shop halls; default storeys when OSM gives none.
RETAIL_STOREY_M = 4.5
DEFAULT_LEVELS = {'retail': 1, 'mall': 3}
# Fuel canopy: deck underside and top (m above ground), post size.
CANOPY_BASE_M = 4.5
CANOPY_TOP_M = 5.3
POST_M = 0.4
# Bell tower only on a nave this large (smaller chapels keep one dome).
TOWER_MIN_AREA_M2 = 150.0
TOWER_MIN_WIDTH_M = 7.0
# Colours used only when OSM tags none (derived, see module docstring).
PALETTE = {
    'church_orthodox': {'wall': '#e9e5da', 'roof': '#4f7a5a', 'dome': '#c9a43a'},
    'church_western': {'wall': '#cfc6b4', 'roof': '#55595c', 'dome': '#55595c'},
    'mosque': {'wall': '#ece6d6', 'roof': '#b9b3a6', 'dome': '#3f7f6e'},
    'fuel_canopy': {'wall': '#e6e6e2', 'roof': '#e6e6e2'},
}
STYLE = {  # architecture, material
    'church_orthodox': ('historic', 'plaster'),
    'church_western': ('historic', 'stone'),
    'mosque': ('historic', 'plaster'),
    'fuel_canopy': ('modern', 'metal'),
}


def kind(tags, area_m2, region='experimental'):
    """Typical-model kind for an OSM building, or None.

    A Christian church without a denomination is Orthodox in the Ukraine region
    profile and Western elsewhere (an assumption; the record says it is derived).
    """
    building = tags.get('building')
    if tags.get('amenity') == 'fuel' and building in ('roof', 'canopy'):
        return 'fuel_canopy'
    if building in WORSHIP_BUILDINGS or tags.get('amenity') == 'place_of_worship':
        religion, denomination = tags.get('religion'), tags.get('denomination', '')
        if building == 'mosque' or religion == 'muslim':
            return 'mosque'
        if religion not in (None, 'christian') or building == 'temple':
            return None
        if denomination in ORTHODOX:
            return 'church_orthodox'
        if denomination:
            return 'church_western'
        return 'church_orthodox' if region == 'ukraine' else 'church_western'
    if tags.get('shop') == 'mall' or building == 'mall':
        return 'mall' if area_m2 >= MALL_MIN_AREA_M2 else 'retail'
    if (building in RETAIL_BUILDINGS or tags.get('shop') in RETAIL_SHOPS) and area_m2 >= RETAIL_MIN_AREA_M2:
        return 'retail'
    return None


def with_context(tags, footprint, context):
    """Tags of a footprint plus the facts of tagged OSM objects around it.

    ``context`` is a list of (geometry, tags) in the footprint's plane: an
    ``amenity=fuel`` area or node makes a ``building=roof`` inside it a fuel
    canopy; a ``place_of_worship`` node inside an untyped footprint types it.
    """
    out = dict(tags)
    for geometry, extra in context:
        if extra.get('amenity') == 'fuel' and tags.get('building') in ('roof', 'canopy') and 'amenity' not in tags:
            if geometry.intersects(footprint.buffer(5.0)):
                out['amenity'] = 'fuel'
        elif extra.get('amenity') == 'place_of_worship' and tags.get('building') in ('yes', None) \
                and geometry.geom_type == 'Point' and footprint.contains(geometry):
            out['amenity'] = 'place_of_worship'
            for key in ('religion', 'denomination'):
                if key in extra and key not in out:
                    out[key] = extra[key]
    return out


def heights(kind_, tags, default_levels):
    """(levels, height, base) for a kind when OSM gives no height or levels; None keeps the default."""
    if kind_ in ('retail', 'mall') and 'building:levels' not in tags and 'height' not in tags:
        levels = DEFAULT_LEVELS[kind_]
        return levels, levels*RETAIL_STOREY_M, None
    if kind_ == 'fuel_canopy':
        base = osm_buildings.number(tags.get('min_height')) or CANOPY_BASE_M
        top = osm_buildings.number(tags.get('height')) or max(CANOPY_TOP_M, base+0.8)
        return 1, top, base
    return None


def _xz(b):
    return Polygon([(p[0], p[2]) for p in b['points']])


def _axes(poly):
    """Long axis of the minimum rotated rectangle: (unit vector, length, width)."""
    ring = list(poly.minimum_rotated_rectangle.exterior.coords)
    e0 = (ring[1][0]-ring[0][0], ring[1][1]-ring[0][1])
    e1 = (ring[2][0]-ring[1][0], ring[2][1]-ring[1][1])
    long_, short = (e0, e1) if math.hypot(*e0) >= math.hypot(*e1) else (e1, e0)
    length, width = math.hypot(*long_), math.hypot(*short)
    if length < 1e-6:
        return (1.0, 0.0), 0.0, 0.0
    ax = (long_[0]/length, long_[1]/length)
    if ax[0] < 0 or (abs(ax[0]) < 1e-9 and ax[1] < 0):
        ax = (-ax[0], -ax[1])            # points east (+x): the west end is -ax
    return ax, length, width


def _octagon(c, r):
    return Polygon([(c[0]+r*math.cos(math.pi/8+i*math.pi/4), c[1]+r*math.sin(math.pi/8+i*math.pi/4)) for i in range(8)])


def _square(c, side, ax):
    angle = math.degrees(math.atan2(ax[1], ax[0]))
    return translate(rotate(box(-side/2, -side/2, side/2, side/2), angle, origin=(0, 0)), c[0], c[1])


def _fit(poly, make, centre, size, smallest):
    """Largest shape make(centre, s), s from size down to smallest, inside the footprint."""
    s = size
    while s >= smallest:
        shape = make(centre, s)
        if poly.buffer(0.05).contains(shape):
            return shape
        s *= 0.85
    return None


def _style(kind_, colour, main):
    architecture, material = STYLE[kind_]
    return {'version': 1, 'architecture': architecture, 'material': material, 'color': colour,
            'roof': 'flat', 'provenance': {'architecture': PROVENANCE, 'material': PROVENANCE,
                                           'color': main.get('color_origin', PROVENANCE),
                                           'roof': PROVENANCE, 'levels': PROVENANCE},
            'influences': []}


def _part(main, shape, floor, base, height, kind_, role, style, roof=None, roof_height=None, roof_color=None):
    """One derived part; the roof solid is built here. Returns (record, fallback reason or None)."""
    ring = list(shape.exterior.coords)[:-1]
    if shape.exterior.is_ccw is False:
        ring.reverse()
    part = {'id': main['id'], 'points': [[round(x, 3), floor, round(z, 3)] for x, z in ring],
            'height': round(height, 3), 'height_source': PROVENANCE, 'levels': 1,
            'local_style': {**style, 'roof': roof or 'flat'},
            'typical': {'kind': kind_, 'role': role, 'provenance': PROVENANCE, 'version': VERSION},
            'style_key': str(main['id'])}
    for key in ('building_type', 'visual_family', 'visual_source'):
        if key in main:
            part[key] = main[key]
    if base > 0:
        part['base'] = round(base, 3)
    if roof_color:
        part['roof_color'] = roof_color
    reason = osm_buildings.shaped_roof(part, roof, roof_height) if roof else None
    if reason:
        part['local_style']['roof_fallback'] = reason
    return part, reason


def apply(b, kind_, tags, region='experimental'):
    """Give ``b`` its typical form. Returns (extra part records, fallback reason or None).

    ``b`` keeps its footprint; a church/mosque/canopy gets a derived ``local_style``
    (unless OSM tagged ``roof:shape``) so its roof is solved by the caller like any
    other styled roof. Shop halls only change height (see :func:`heights`).
    """
    b['typical'] = {'kind': kind_, 'provenance': PROVENANCE, 'version': VERSION}
    if kind_ in ('retail', 'mall'):
        return [], None
    observed = osm_buildings.observed(tags)
    palette = PALETTE[kind_]
    wall = local_dna.colour(observed['color']) if observed['color'] else None
    roof_tagged = local_dna.colour(observed['roof_color']) if observed['roof_color'] else None
    main_colour = wall or palette['wall']
    style = _style(kind_, main_colour, {'color_origin': 'osm' if wall else PROVENANCE})
    if observed['material']:
        style['material'], style['provenance']['material'] = observed['material'], 'osm'
    b['local_style'] = {**style}
    b['visual_family'] = local_dna.VISUAL_FAMILY[style['architecture']]
    b['visual_source'] = 'typical model by OSM building type; see typical/local_style.provenance'
    if not roof_tagged:
        b['roof_color'] = palette['roof']
    poly = _xz(b)
    floor = min(p[1] for p in b['points'])
    if not poly.is_valid or poly.area < 4:
        b['typical']['fallback'] = 'plain: invalid or tiny footprint'
        return [], b['typical']['fallback']
    if kind_ == 'fuel_canopy':
        return _canopy(b, poly, floor, style)
    ax, length, width = _axes(poly)
    if b.get('height_source') == 'assumed':
        # A church is not a two-storey box: walls from the nave width, plus the roof rise.
        b['height'] = round(max(7.0, min(14.0, 0.6*width)) + min(2.6, width*0.35), 3)
    b['local_style']['roof'] = 'flat' if kind_ == 'mosque' else 'hipped'
    total = float(b['height'])
    rise = 0.0 if kind_ == 'mosque' else min(2.6, width*0.35)
    eave = total - rise
    c = poly.representative_point() if not poly.contains(poly.centroid) else poly.centroid
    centre = (c.x, c.y)
    parts, reasons = [], []
    dome_colour = palette['dome']
    if kind_ in ('church_orthodox', 'mosque'):
        r = max(1.5, min(6.0, 0.22*width if kind_ == 'church_orthodox' else 0.3*width))
        drum = _fit(poly, _octagon, centre, r, 1.0)
        if drum is None:
            reasons.append('no dome: footprint too narrow at its centre')
        else:
            r = math.sqrt(drum.area/2.8284)        # octagon area = 2*sqrt(2)*r^2
            shape = 'onion' if kind_ == 'church_orthodox' else 'dome'
            dome_rise = r*(1.6 if shape == 'onion' else 1.0)
            drum_h = r*(1.4 if kind_ == 'church_orthodox' else 0.6)
            part, why = _part(b, drum, floor, eave, total+drum_h+dome_rise, kind_, 'dome', style,
                              shape, dome_rise, dome_colour)
            parts.append(part)
            if why:
                reasons.append('dome '+why)
    # The tower stays narrower than the nave; a chapel gets none (Bilychi shots 2026-10-08:
    # a nave-wide tower on a 9 m chapel read as a block of flats with a dome).
    side = max(2.5, min(7.0, 0.5*width))
    if kind_ in ('church_orthodox', 'church_western') and length >= 1.3*width \
            and poly.area >= TOWER_MIN_AREA_M2 and width >= TOWER_MIN_WIDTH_M:
        # Bell tower over the entrance at the west end of the long axis.
        offset = length/2 - side/2
        west = (centre[0]-ax[0]*offset, centre[1]-ax[1]*offset)
        tower = _fit(poly, lambda p, s: _square(p, s, ax), west, side, 2.5)
        if tower is None:
            reasons.append('no bell tower: west end does not fit a square')
        else:
            s = math.sqrt(tower.area)
            if kind_ == 'church_orthodox':
                part, why = _part(b, tower, floor, 0.0, total+s*1.2+s*1.1, kind_, 'bell_tower', style,
                                  'onion', s*1.1, dome_colour)
            else:
                part, why = _part(b, tower, floor, 0.0, total+s*1.2+s*2.5, kind_, 'bell_tower', style,
                                  'pyramidal', s*2.5, dome_colour)
            parts.append(part)
            if why:
                reasons.append('bell tower '+why)
    if kind_ == 'mosque':
        # Minaret at the corner farthest from the dome along the long axis.
        offset = max(0.0, length/2 - 2.0)
        spot = (centre[0]-ax[0]*offset, centre[1]-ax[1]*offset)
        minaret = _fit(poly, _octagon, spot, 1.3, 0.8)
        if minaret is None:
            reasons.append('no minaret: end of the long axis too narrow')
        else:
            part, why = _part(b, minaret, floor, 0.0, max(total*2.2, total+12.0), kind_, 'minaret', style,
                              'pyramidal', 3.0, dome_colour)
            parts.append(part)
            if why:
                reasons.append('minaret '+why)
    reason = '; '.join(reasons) or None
    if reason:
        b['typical']['fallback'] = reason
    return parts, reason


def _canopy(b, poly, floor, style):
    """Raised deck (``b`` itself, base from :func:`heights`) on a grid of posts."""
    b['local_style']['roof'] = 'flat'
    base = float(b.get('base', CANOPY_BASE_M))
    ax, length, width = _axes(poly)
    c = poly.centroid
    along = max(2, min(4, round(length/9)+1))
    across = 2 if width > 8 else 1
    parts = []
    for i in range(along):
        fa = (i/(along-1) - 0.5) if along > 1 else 0.0
        for j in range(across):
            fr = (j/(across-1) - 0.5) if across > 1 else 0.0
            p = (c.x + ax[0]*fa*(length-3.0) - ax[1]*fr*(width-3.0),
                 c.y + ax[1]*fa*(length-3.0) + ax[0]*fr*(width-3.0))
            post = _square(p, POST_M, ax)
            if not poly.contains(post):
                continue
            part, _ = _part(b, post, floor, 0.0, base, 'fuel_canopy', 'post', {**style, 'material': 'metal'})
            parts.append(part)
    if not parts:
        b['typical']['fallback'] = 'no posts: footprint too narrow'
    return parts, b['typical'].get('fallback')


def blocked(tags, b, parents):
    """Reason OSM detail wins over a typical model, or None."""
    if b.get('_part') or b.get('_parent') is not None or 'building:part' in tags:
        return 'osm: building:part'
    if id(b) in parents:
        return 'osm: outline has building:part items'
    if tags.get('roof:shape'):
        return 'osm: roof:shape'
    return None


def context_objects(root, nodes, to_xy, tags):
    """(geometry, tags) of fuel stations and places of worship that are not buildings themselves."""
    out = []
    for node in root.iter('node'):
        t = tags(node)
        if t.get('amenity') in ('fuel', 'place_of_worship') and 'building' not in t:
            out.append((Point(to_xy(float(node.attrib['lon']), float(node.attrib['lat']))), t))
    for way in root.iter('way'):
        t = tags(way)
        if t.get('amenity') != 'fuel' or 'building' in t:
            continue
        refs = [nd.attrib['ref'] for nd in way.findall('nd')]
        if len(refs) >= 4 and refs[0] == refs[-1] and all(r in nodes for r in refs):
            poly = Polygon([to_xy(*nodes[r]) for r in refs]).buffer(0)
            if not poly.is_empty:
                out.append((poly, t))
    return out
