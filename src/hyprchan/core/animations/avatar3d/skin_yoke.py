"""Restore the skin removed underneath the licensed base's original T-shirt.

The neck and arms end at three open boundary loops. Reusing them, including
their UVs and bone weights, keeps the shoulder coverage continuous in poses.
Only the second costume uses this repair; the hoodie remains unchanged.
"""
from collections import defaultdict
import numpy as np


def boundary_loops(attributes, indices):
    p, first, inverse = np.unique(attributes['POSITION'].round(5), axis=0,
                                   return_index=True, return_inverse=True)
    faces = inverse[indices].reshape(-1, 3)
    edges = np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1)
    edges, count = np.unique(edges,axis=0,return_counts=True)
    adjacent = defaultdict(list)
    for a,b in edges[count==1]: adjacent[a].append(b); adjacent[b].append(a)
    seen=set(); loops=[]
    for start in adjacent:
        if start in seen: continue
        previous=None; current=start; loop=[]
        while current not in seen:
            seen.add(current);loop.append(current)
            following=next((v for v in adjacent[current] if v!=previous),start)
            previous,current=current,following
        if current==start: loops.append(first[loop])
    return loops


def chains(loop, positions, start, end):
    """The two paths between vertices, ordered front then back."""
    i=list(loop).index(start);j=list(loop).index(end)
    def path(direction):
        result=[start];n=i
        while n!=j:
            n=(n+direction)%len(loop);result.append(loop[n])
        return result
    return sorted([path(1),path(-1)],key=lambda p:positions[p,2].mean(),reverse=True)


def triangulate(polygon, positions):
    """Ear clipping for these simple front/back shoulder contours in XY."""
    polygon=list(polygon);xy=np.asarray(positions)[:,:2]
    q=xy[polygon]
    if np.sum(q[:,0]*np.roll(q[:,1],-1)-q[:,1]*np.roll(q[:,0],-1))<0: polygon.reverse()
    faces=[]
    def cross(a,b): return a[0]*b[1]-a[1]*b[0]
    while len(polygon)>3:
        for i,b in enumerate(polygon):
            a,c=polygon[i-1],polygon[(i+1)%len(polygon)]
            ab,ac=xy[b]-xy[a],xy[c]-xy[a]
            area=cross(ab,ac)
            if area<=1e-12: continue
            others=[v for v in polygon if v not in (a,b,c)]
            delta=xy[others]-xy[a]
            u=(delta[:,0]*ac[1]-delta[:,1]*ac[0])/area
            v=(ab[0]*delta[:,1]-ab[1]*delta[:,0])/area
            if np.any((u>1e-7)&(v>1e-7)&(u+v<1-1e-7)): continue
            faces.append((a,b,c));polygon.pop(i);break
        else: raise ValueError('The base shoulder boundary could not be triangulated')
    faces.append(tuple(polygon))
    return faces


def restore_shoulders(model):
    body=next(p for p in model.primitives if p['material']['name']=='Body_00_SKIN')
    original=body['attributes']; positions=original['POSITION']
    loops=[loop for loop in boundary_loops(original,body['indices'])
           if 1.23<positions[loop,1].mean()<1.32 and abs(positions[loop,0].mean())<.15]
    if len(loops)!=3: raise ValueError('Expected the base neck and two sleeve openings')
    left,neck,right=sorted(loops,key=lambda loop:positions[loop,0].mean())
    neck_paths=chains(neck,positions,neck[np.argmin(positions[neck,0])],neck[np.argmax(positions[neck,0])])
    arm_paths=[]
    for loop in (left,right):
        arm_paths.append(chains(loop,positions,loop[np.argmin(abs(positions[loop,0]))],
                               loop[np.argmax(abs(positions[loop,0]))]))
    attrs={key:list(value.copy()) for key,value in original.items()}
    influences=[{int(j):float(w) for j,w in zip(js,ws) if w>0}
                for js,ws in zip(original['JOINTS_0'],original['WEIGHTS_0'])]
    palette=model.skins[body['skin']][0]
    def add(point, uv, influence, normal):
        index=len(attrs['POSITION'])
        attrs['POSITION'].append(np.asarray(point,float));attrs['TEXCOORD_0'].append(np.asarray(uv,float))
        attrs['NORMAL'].append(np.asarray(normal,float));influences.append(influence)
        return index
    faces=[]
    for back in (False,True):
        n=neck_paths[int(back)];l=arm_paths[0][int(back)];r=arm_paths[1][int(back)]
        bottom=[]
        for x in np.linspace(.134,-.134,9):
            # This is the clavicle/shoulder yoke, tucked inside the bodice.
            # A convex chest cap would protrude through the collar above the
            # garment's bust shaping; the lower edge is hidden by the blouse.
            z=-.055 if back else .018
            bottom.append(add([x,1.205,z],original['TEXCOORD_0'][n[len(n)//2]],
                              {palette.index(model.bones['upperChest']):1},[0,0,-1 if back else 1]))
        polygon=[*n,*r,*bottom,*reversed(l)]
        triangles=triangulate(polygon,attrs['POSITION'])
        if back: triangles=[(a,c,b) for a,b,c in triangles]
        faces.extend(triangles)
    # Add interior vertices without splitting the authored boundary edges:
    # this prevents T-junction cracks between the old and new skin in motion.
    # Interpolate influence dictionaries, never numeric bone IDs.
    for _ in range(2):
        subdivided=[]
        for a,b,c in faces:
            influence={j:sum(influences[v].get(j,0) for v in (a,b,c))/3
                       for j in influences[a].keys()|influences[b].keys()|influences[c].keys()}
            center=add(sum(attrs['POSITION'][v] for v in (a,b,c))/3,
                       sum(attrs['TEXCOORD_0'][v] for v in (a,b,c))/3,influence,
                       sum(attrs['NORMAL'][v] for v in (a,b,c))/3)
            subdivided.extend([(a,b,center),(b,c,center),(c,a,center)])
        faces=subdivided
    # Keep the complete bridge. Cutting it at a horizontal neckline broke the
    # oblique shoulder loops, leaving steps and cracks when the arms moved.
    # Start with the authored boundary normals and the restored surface's
    # interior normals, then blend their shading across the welded clavicle.
    p=np.asarray(attrs['POSITION'],np.float32);ix=np.asarray(faces,np.uint32)
    normal=np.zeros_like(p)
    face_normal=np.cross(p[ix[:,1]]-p[ix[:,0]],p[ix[:,2]]-p[ix[:,0]])
    for corner in range(3): np.add.at(normal,ix[:,corner],face_normal)
    for i in range(len(positions),len(p)):
        if np.linalg.norm(normal[i])>1e-8: attrs['NORMAL'][i]=normal[i]/np.linalg.norm(normal[i])
    joints=np.zeros((len(p),4),np.float32);weights=np.zeros_like(joints)
    for i,influence in enumerate(influences):
        items=sorted(influence.items(),key=lambda item:item[1],reverse=True)[:4]
        total=sum(w for _,w in items)
        for slot,(joint,weight) in enumerate(items):joints[i,slot]=joint;weights[i,slot]=weight/total
    body['attributes']={key:np.asarray(value,np.float32) for key,value in attrs.items()
                        if key not in {'JOINTS_0','WEIGHTS_0'}}
    body['attributes'].update(JOINTS_0=joints,WEIGHTS_0=weights)
    body['indices']=np.concatenate([body['indices'],ix.ravel()])
    smooth_clavicle(body)
    model.restored_shoulder_faces=ix


def smooth_clavicle(body):
    """Round the welded shoulder bridge into the existing neck and deltoids.

    The source's shirt openings have angular cut edges. Merely filling their
    holes retains those steps in the silhouette; relax the connected surface
    together, with a fade into unchanged neck, upper arms and lower torso.
    """
    a=body['attributes']
    _,first,inverse=np.unique(a['POSITION'].round(5),axis=0,return_index=True,return_inverse=True)
    p=a['POSITION'][first].astype(float)
    faces=inverse[body['indices']].reshape(-1,3)
    edges=np.unique(np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1),axis=0)
    source=np.concatenate([edges[:,0],edges[:,1]])
    target=np.concatenate([edges[:,1],edges[:,0]])
    count=np.bincount(source,minlength=len(p)).clip(1)
    def ease(t):
        t=np.clip(t,0,1)
        return t*t*(3-2*t)
    mask=(ease((p[:,1]-1.255)/.025)*ease((1.345-p[:,1])/.025)
          *ease((.20-abs(p[:,0]))/.04))
    original=p.copy()
    for _ in range(12):
        average=np.zeros_like(p)
        np.add.at(average,source,p[target])
        p+=(average/count[:,None]-p)*(mask*.35)[:,None]
        displacement=p-original
        distance=np.linalg.norm(displacement,axis=1,keepdims=True)
        p=original+displacement*np.minimum(1,.005/np.maximum(distance,1e-8))
    a['POSITION']=p[inverse].astype(np.float32)
    normal=np.zeros_like(p)
    n=np.cross(p[faces[:,1]]-p[faces[:,0]],p[faces[:,2]]-p[faces[:,0]])
    for corner in range(3):np.add.at(normal,faces[:,corner],n)
    normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-8)
    a['NORMAL']=a['NORMAL']*(1-mask[inverse,None])+normal[inverse]*mask[inverse,None]
    # Broad clavicle shading, with a continuous blend into the original neck
    # and round deltoids. Tiny triangulation differences should not paint
    # angular wedges across exposed skin in an illustrated portrait.
    p=a['POSITION']
    blend=(ease((1.325-p[:,1])/.035)*ease((p[:,1]-1.245)/.025)
           *ease((.12-abs(p[:,0]))/.04))
    direction=np.where(p[:,2]>-.02,1.,-1.)
    soft=np.column_stack([p[:,0]*3,np.full(len(p),.25),direction])
    soft/=np.linalg.norm(soft,axis=1,keepdims=True)
    a['NORMAL']=a['NORMAL']*(1-blend[:,None])+soft*blend[:,None]
    a['NORMAL']/=np.maximum(np.linalg.norm(a['NORMAL'],axis=1,keepdims=True),1e-8)
    a['NORMAL']=a['NORMAL'].astype(np.float32)
