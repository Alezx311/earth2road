"""Audited width defaults and monotone vertical interpolation for road preparation."""
import math
import xml.etree.ElementTree as ET

LANE_WIDTHS = {'motorway': 3.5, 'trunk': 3.5, 'primary': 3.5,
               'secondary': 3.25, 'tertiary': 3.25, 'residential': 3.25,
               'unclassified': 3.25, 'living_street': 3.25}


def write_types(base, overrides, output):
    root = ET.parse(base).getroot()
    types = {t.get('id'): t for t in root.findall('type')}
    for t in ET.parse(overrides).getroot().findall('type'):
        if t.get('id') in types:
            old=types[t.get('id')]
            # allow/disallow are mutually exclusive, not fields to merge together.
            if 'disallow' in t.attrib: old.attrib.pop('allow',None)
            if 'allow' in t.attrib: old.attrib.pop('disallow',None)
            old.attrib.update(t.attrib)
        else:
            root.append(t); types[t.get('id')]=t
    for kind,width in LANE_WIDTHS.items():
        for suffix in ('','_link'):
            t=types.get('highway.'+kind+suffix)
            if t is not None: t.set('width',str(width))
    ET.ElementTree(root).write(output,encoding='utf-8',xml_declaration=True)
    return {'provenance':'assumed', 'lane_width_m':LANE_WIDTHS,
            'precedence':'Explicit OSM width and lane count retained by netconvert; service defaults unchanged.'}


def profile_z(points, i, t):
    """Monotone cubic Hermite interpolation: smooth grades, no invented peaks."""
    a,b=points[i],points[i+1]
    h=math.dist(a[:2],b[:2])
    if h < 1e-9: return a[2]
    slope=(b[2]-a[2])/h
    def tangent(j):
        if j == 0 or j == len(points)-1: return slope
        p,q,r=points[j-1:j+2]
        h0,h1=math.dist(p[:2],q[:2]),math.dist(q[:2],r[:2])
        if min(h0,h1) < 1e-9: return 0.
        d0,d1=(q[2]-p[2])/h0,(r[2]-q[2])/h1
        if d0*d1 <= 0: return 0.
        w0,w1=2*h1+h0,h1+2*h0
        return (w0+w1)/(w0/d0+w1/d1)
    m0,m1=tangent(i),tangent(i+1)
    return (2*t**3-3*t*t+1)*a[2]+(t**3-2*t*t+t)*h*m0+(-2*t**3+3*t*t)*b[2]+(t**3-t*t)*h*m1
