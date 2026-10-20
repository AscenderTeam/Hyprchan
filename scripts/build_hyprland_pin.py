#!/usr/bin/env python3
"""Extract a cord centreline from the official mark; build-time fontTools only."""
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from fontTools.pens.recordingPen import RecordingPen
from fontTools.svgLib.path import parse_path

ASSETS=Path(__file__).resolve().parents[1]/'src/hyprchan/assets/avatar3d'


def cross(a,b):
    return a[0]*b[1]-a[1]*b[0]


def resample(points, count):
    distance=np.r_[0,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    sample=np.linspace(0,distance[-1],count)
    return np.column_stack([np.interp(sample,distance,points[:,axis]) for axis in (0,1)])


def main():
    document=ET.parse(ASSETS/'hyprland-mark.svg')
    path=next(e for e in document.iter() if e.tag.endswith('path'))
    pen=RecordingPen();parse_path(path.get('d'),pen)
    points=[]
    for operation,values in pen.value:
        if operation in {'moveTo','lineTo'}:points.append(np.asarray(values[0],float))
        elif operation=='curveTo':
            p=points[-1];a,b,c=np.asarray(values)
            count=max(2,math.ceil((np.linalg.norm(a-p)+np.linalg.norm(b-a)+np.linalg.norm(c-b))/3))
            for t in np.linspace(0,1,count+1)[1:]:points.append((1-t)**3*p+3*(1-t)**2*t*a+3*(1-t)*t*t*b+t**3*c)
        elif operation!='closePath':raise ValueError(operation)
    cleaned=[]
    for point in points:
        if not cleaned or np.linalg.norm(point-cleaned[-1])>.05:cleaned.append(point)
    if np.linalg.norm(cleaned[0]-cleaned[-1])<.05:cleaned.pop()
    points=np.asarray(cleaned)
    # Remove nearly collinear exporter segments, retaining the actual outline.
    while True:
        keep=[]
        for i,q in enumerate(points):
            p,r=points[i-1],points[(i+1)%len(points)]
            if abs(cross(q-p,r-q))>1e-5:keep.append(q)
        if len(keep)==len(points):break
        points=np.asarray(keep)
    low,high=points.min(0),points.max(0)
    points=(points-(low+high)/2)/(high[1]-low[1]);points[:,1]*=-1
    area=sum(cross(a,b) for a,b in zip(points,np.roll(points,-1,axis=0)))/2
    if area<0:points=points[::-1];area=-area
    # The two long vertical end caps separate the inner and outer U-shaped
    # boundaries. Average equal arc-length samples, preserving the official
    # curve instead of substituting a generic teardrop.
    a,b=sorted(np.argsort(np.linalg.norm(np.roll(points,-1,axis=0)-points,axis=1))[-2:])
    assert all(abs(points[i,0]-points[(i+1)%len(points),0])<1e-6 for i in (a,b))
    inner=points[a+1:b+1]
    outer=np.concatenate([points[b+1:],points[:a+1]])[::-1]
    center=(resample(inner,1001)+resample(outer,1001))/2
    # Rounded 5 mm cord tips need room for the logo's open top. Trim only the
    # very narrow ends so their hemispherical caps never join across the gap.
    start=np.flatnonzero(abs(center[:500,0])>=.12)[0]
    end=1000-np.flatnonzero(abs(center[500:][::-1,0])>=.12)[0]
    center=resample(center[start:end+1],241)
    output={'source':'hyprland-mark.svg','heightNormalized':1,'outline':points.round(7).tolist(),
            'centerline':center.round(7).tolist()}
    (ASSETS/'hyprland-pin.json').write_text(json.dumps(output,separators=(',',':'))+'\n')
    print({'outlineVertices':len(points),'cordSamples':len(center),'normalizedArea':round(area,6)})


if __name__=='__main__':main()
