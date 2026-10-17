"""Tailor the licensed base garment into a continuous, long-sleeved hoodie.

Keep the original sewn shoulder topology and skin constraints. Subdivision
provides enough vertices for cloth folds and soft elbow weight transitions.
"""
import numpy as np
from .materials import linear


def hoodie_shell(model):
    source = next(p for p in model.primitives if p['material']['name'].startswith('Tops_'))
    attrs = source['attributes']
    # Find the actual sewn sleeve openings. The base tee has angled hems;
    # stretching raw X coordinates would leave a diagonal hole under the cuff.
    welded, inverse = np.unique(np.round(attrs['POSITION'],6),axis=0,return_inverse=True)
    faces = inverse[source['indices']].reshape(-1,3)
    edges = np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1)
    edges, counts = np.unique(edges,axis=0,return_counts=True)
    boundary = welded[np.unique(edges[counts==1])]
    positions = attrs['POSITION'].tolist()
    triangles = source['indices'].reshape(-1, 3).tolist()
    skin = model.skins[source['skin']][0]
    weights = [{int(j): float(w) for j, w in zip(js, ws) if w > 0}
               for js, ws in zip(attrs['JOINTS_0'], attrs['WEIGHTS_0'])]
    for _ in range(2):
        edges = {}; divided = []
        def middle(a, b):
            key = tuple(sorted((a, b)))
            if key not in edges:
                edges[key] = len(positions)
                positions.append(((np.array(positions[a])+positions[b])/2).tolist())
                weights.append({j: (weights[a].get(j, 0)+weights[b].get(j, 0))/2
                                for j in weights[a].keys() | weights[b].keys()})
            return edges[key]
        for a, b, c in triangles:
            ab, bc, ca = middle(a,b), middle(b,c), middle(c,a)
            divided.extend([(a,ab,ca), (ab,b,bc), (ca,bc,c), (ab,bc,ca)])
        triangles = divided
    p = np.array(positions, dtype=np.float32)
    x, y, z = p.T.copy(); ax = np.abs(x)
    # Extend the actual sleeve opening instead of attaching separate cylinders.
    theta = np.arctan2(z+.0255,y-1.2742)
    sleeve_progress = np.zeros(len(p),dtype=np.float32)
    for side in (-1,1):
        hem = boundary[boundary[:,0]*side>.2]
        hem_angle = np.arctan2(hem[:,2]+.0255,hem[:,1]-1.2742)
        selected = x*side>.2
        end = np.interp(theta[selected],hem_angle,np.abs(hem[:,0]),period=2*np.pi)
        sleeve_progress[selected] = np.clip((ax[selected]-.2)/(end-.2),0,1)
        p[selected,0] = side*(.2+.335*sleeve_progress[selected])
    sleeve = np.clip((ax-.15)/.1, 0, 1)
    # A fitted torso and slimmer sleeves retain her silhouette under the fabric.
    torso = (1-sleeve)*np.clip((1.31-y)/.12,0,1)
    p[:,0] *= 1-.16*torso
    p[:,1] -= (y-1.2742)*sleeve*.16
    p[:,2] += (z+.0255)*(.04-.18*sleeve)
    # Lower the crew-neck opening beneath the hood's lining.
    neckline = np.clip((y-1.24)/.08,0,1)*np.exp(-(ax/.09)**4)
    p[:, 1] -= neckline*.055
    # Shallow diagonal tension folds running away from the underarm, plus a
    # little gathering around the elbow and cuff. These change real normals.
    front = np.clip((z-.035)/.05, 0, 1)*(1-sleeve)
    bust = np.exp(-((np.abs(p[:,0])-.054)/.056)**2-((y-1.176)/.071)**2)
    p[:,2] += front*.105*bust
    # Fullness belongs to the chest, not wider shoulders or a boxy waist.
    p[:,0] += np.sign(x)*front*.012*bust
    # The hoodie drapes beneath the bust instead of remaining a flat slab.
    p[:,2] -= front*.008*np.exp(-((y-1.075)/.025)**2)
    for center, amount in [(1.055,.0045), (1.12,.004), (1.205,.003)]:
        distance = y-(center+.67*ax)
        envelope = np.exp(-((ax-.115)/.07)**2)
        p[:, 2] += front*envelope*amount*(np.exp(-((distance+.009)/.012)**2)
                                              -np.exp(-(distance/.006)**2))
    length = np.abs(p[:, 0])
    gather = (np.exp(-((length-.36)/.065)**2)+np.exp(-((length-.50)/.035)**2))
    fold = np.sin(length*175+(y-1.274)*22)*.0035*gather*sleeve
    radius = np.maximum(np.hypot(y-1.2742,z+.0255), .001)
    p[:, 1] += fold*(y-1.2742)/radius
    p[:, 2] += fold*(z+.0255)/radius
    wrist = sleeve_progress**3
    p[:,1] = p[:,1]*(1-wrist)+(1.2742+.038*np.cos(theta))*wrist
    p[:,2] = p[:,2]*(1-wrist)+(-.0255+.038*np.sin(theta))*wrist
    # The extended sleeve reaches the wrist; assign its new section to the
    # actual arm bones with a soft elbow blend, keeping the sewn shoulder rig.
    for i in np.flatnonzero(length>.29):
        side = 'left' if p[i,0]>0 else 'right'
        upper = skin.index(model.bones[side+'UpperArm'])
        lower = skin.index(model.bones[side+'LowerArm'])
        blend = float(np.clip((length[i]-.29)/.09, 0, 1)); blend=blend*blend*(3-2*blend)
        weights[i] = {upper:1-blend, lower:blend}
    joints = np.zeros((len(p), 4), dtype=np.float32)
    packed_weights = np.zeros_like(joints)
    for i, values in enumerate(weights):
        values = sorted(values.items(), key=lambda item:item[1], reverse=True)[:4]
        total = sum(w for _,w in values)
        for n,(j,w) in enumerate(values): joints[i,n]=j; packed_weights[i,n]=w/total
    ix = np.asarray(triangles, dtype=np.uint32)
    normals = np.zeros_like(p)
    face = np.cross(p[ix[:,1]]-p[ix[:,0]], p[ix[:,2]]-p[ix[:,0]])
    for n in range(3): np.add.at(normals,ix[:,n],face)
    # Weld shading at UV/material seams without altering the skin topology.
    _, inverse = np.unique(np.round(p,6), axis=0, return_inverse=True)
    welded = np.zeros((inverse.max()+1,3), dtype=np.float32)
    np.add.at(welded,inverse,normals); normals=welded[inverse]
    normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-8)
    model.primitives.append({**source, 'targets': [], 'names': [], 'indices': ix.ravel(),
        'material': {'name':'Hoodie shell', 'doubleSided':True,
                     'pbrMetallicRoughness':{'baseColorFactor':[*linear([.955,.97,1]).tolist(),1]}},
        'attributes':{'POSITION':p, 'NORMAL':normals, 'TEXCOORD_0':np.zeros((len(p),2),dtype=np.float32),
                      'JOINTS_0':joints, 'WEIGHTS_0':packed_weights}})
