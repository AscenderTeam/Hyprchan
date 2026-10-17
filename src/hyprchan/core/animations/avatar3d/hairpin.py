"""The Hyprland mark made from thick, rounded cord, bound to the VRM head."""
import json
from pathlib import Path

import numpy as np


def add_hyprland_pin(model, mesh, front_hit):
    source=Path(__file__).resolve().parents[3]/'assets/avatar3d/hyprland-pin.json'
    data=json.loads(source.read_text())
    line=np.asarray(data['centerline'],dtype=np.float64)*.032
    tangent=np.gradient(line,axis=0)
    tangent/=np.linalg.norm(tangent,axis=1,keepdims=True)
    distance=np.r_[0,np.cumsum(np.linalg.norm(np.diff(line,axis=0),axis=1))]
    radius=.0025

    hair=np.concatenate([p['attributes']['POSITION'][p['indices'].reshape(-1,3)]
                         for p in model.primitives if 'HAIR' in p['material']['name']])

    def surface(x,y):
        hit=front_hit(x,y,hair)
        if hit is None:raise ValueError('Hyprland pin mount is outside the hair surface')
        return float(hit[1] @ hair[hit[0],:,2])

    # The original gold sparkle stays on the viewer's left.
    x,y=.065,1.52
    z=surface(x,y)
    dx=(surface(x+.004,y)-surface(x-.004,y))/.008
    dy=(surface(x,y+.004)-surface(x,y-.004))/.008
    normal=np.array([-dx,-dy,1]);normal/=np.linalg.norm(normal)
    right=np.array([1,0,dx]);right/=np.linalg.norm(right)
    up=np.cross(normal,right)
    angle=np.radians(12)
    basis=np.column_stack([right*np.cos(angle)+up*np.sin(angle),
                           -right*np.sin(angle)+up*np.cos(angle),normal])
    anchor=np.array([x,y,z])+normal*(radius+.002)

    # Circular cross-section, hemispherical ends and UVs along/across the
    # cord. Real curved normals provide the soft highlight and cast shadow.
    rings=[]
    for angle in np.linspace(-np.pi/2,0,6)[:-1]:
        rings.append((line[0]+tangent[0]*radius*np.sin(angle),tangent[0],
                      radius*np.cos(angle),radius*np.sin(angle)))
    rings.extend((p,t,radius,s) for p,t,s in zip(line,tangent,distance))
    for angle in np.linspace(0,np.pi/2,6)[1:]:
        rings.append((line[-1]+tangent[-1]*radius*np.sin(angle),tangent[-1],
                      radius*np.cos(angle),distance[-1]+radius*np.sin(angle)))
    positions=[];uv=[];indices=[]
    sides=20
    for p,t,r,s in rings:
        perpendicular=np.array([-t[1],t[0]])
        for j in range(sides+1):
            a=2*np.pi*j/sides
            local=np.r_[p+perpendicular*r*np.cos(a),r*np.sin(a)]
            positions.append(local@basis.T+anchor)
            uv.append([s/.0018,j/sides])
    stride=sides+1
    for row in range(len(rings)-1):
        for j in range(sides):
            a=row*stride+j;b=a+1;c=a+stride;d=c+1
            indices.extend([a,b,c,b,d,c])
    primitive=mesh(positions,indices,[1,1,1],6,'Hyprland pin cord')
    primitive['attributes']['TEXCOORD_0']=np.asarray(uv,dtype=np.float32)
    # The duplicated UV seam must have identical smooth normals.
    normals=primitive['attributes']['NORMAL'].reshape(-1,stride,3)
    seam=normals[:,0]+normals[:,-1]
    seam/=np.maximum(np.linalg.norm(seam,axis=1,keepdims=True),1e-8)
    normals[:,0]=seam;normals[:,-1]=seam
