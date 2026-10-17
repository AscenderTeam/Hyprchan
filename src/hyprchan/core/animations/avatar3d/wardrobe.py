"""Hyprchan's white hoodie, turquoise lining, cords and sunshine chest emblem.

These meshes are generated in the base rig's bind space and use its actual bones.
The original texture images are left untouched.
"""
import numpy as np
from .materials import linear
from .cloth import hoodie_shell


def add_hoodie(model):
    model.hoodie_contact=True
    hoodie_shell(model)
    shell = model.primitives[-1]
    shell_attributes = shell['attributes']
    shell_indices = shell['indices'].reshape(-1,3)
    triangles = shell_attributes['POSITION'][shell_indices]
    front = (triangles[:,:,2].mean(1)>0) & (np.abs(triangles[:,:,0]).max(1)<.17)
    shell_indices = shell_indices[front]
    shell_triangles = triangles[front]
    triangles = shell_triangles
    def front_hit(x,y,surface):
        a,b,c=surface.transpose(1,0,2)
        denominator=(b[:,1]-c[:,1])*(a[:,0]-c[:,0])+(c[:,0]-b[:,0])*(a[:,1]-c[:,1])
        valid=np.abs(denominator)>1e-10
        denominator=np.where(valid,denominator,1)
        u=((b[:,1]-c[:,1])*(x-c[:,0])+(c[:,0]-b[:,0])*(y-c[:,1]))/denominator
        v=((c[:,1]-a[:,1])*(x-c[:,0])+(a[:,0]-c[:,0])*(y-c[:,1]))/denominator
        valid &= (u>=-.0001)&(v>=-.0001)&(u+v<=1.0001)
        z=u*a[:,2]+v*b[:,2]+(1-u-v)*c[:,2]
        hits=np.flatnonzero(valid)
        if not len(hits): return None
        index=hits[np.argmax(z[hits])]
        barycentric=np.clip([u[index],v[index],1-u[index]-v[index]],0,1)
        return index,barycentric/barycentric.sum()
    def front_z(x,y):
        hit=front_hit(x,y,triangles)
        return float(hit[1] @ triangles[hit[0],:,2]) if hit is not None else .12

    names = ['chest', 'upperChest', 'leftUpperArm', 'rightUpperArm', 'leftLowerArm', 'rightLowerArm', 'head']
    joints = [model.bones[name] for name in names]
    skin = len(model.skins)
    model.skins.append((joints, np.array([np.linalg.inv(model.bind_world[j]) for j in joints])))

    def mesh(vertices, indices, color, joint=0, name='Hoodie'):
        p = np.array(vertices, dtype=np.float32)
        ix = np.array(indices, dtype=np.uint32).reshape(-1, 3)
        normal = np.zeros_like(p)
        face = np.cross(p[ix[:, 1]] - p[ix[:, 0]], p[ix[:, 2]] - p[ix[:, 0]])
        for corner in range(3): np.add.at(normal, ix[:, corner], face)
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-8)
        weights = np.zeros((len(p), 4), dtype=np.float32); weights[:, 0] = 1
        joint_ids = np.zeros((len(p), 4), dtype=np.float32)
        if isinstance(joint, tuple):
            alpha = np.clip((np.abs(p[:, 0])-.28)/.09, 0, 1)
            alpha = alpha*alpha*(3-2*alpha)
            joint_ids[:, 0] = joint[0]; joint_ids[:, 1] = joint[1]
            weights[:, 0] = 1-alpha; weights[:, 1] = alpha
        else:
            joint_ids[:, 0] = joint
        mesh_skin = skin
        if name in {'Sunshine emblem', 'Hyprchan W'}:
            # Transfer the actual fabric surface, smooth normals and skinning.
            # Recomputing normals from the thin W strips creates fake creases;
            # binding only to the chest lets the print slide as the cloth bends.
            offset = .0025 if name == 'Hyprchan W' else .0015
            mesh_skin = shell['skin']
            weights.fill(0); joint_ids.fill(0)
            for i,(x,y,_) in enumerate(p):
                hit = front_hit(x,y,shell_triangles)
                if hit is None: raise ValueError('Printed emblem is outside the hoodie surface')
                triangle, barycentric = hit
                vertices = shell_indices[triangle]
                p[i,2] = barycentric @ shell_attributes['POSITION'][vertices,2] + offset
                normal[i] = barycentric @ shell_attributes['NORMAL'][vertices]
                normal[i] /= max(np.linalg.norm(normal[i]), 1e-8)
                influence = {}
                for vertex, blend in zip(vertices,barycentric):
                    for bone, weight in zip(shell_attributes['JOINTS_0'][vertex], shell_attributes['WEIGHTS_0'][vertex]):
                        if weight > 0:
                            bone = int(bone)
                            influence[bone] = influence.get(bone,0) + blend*weight
                strongest = sorted(influence.items(),key=lambda item:item[1],reverse=True)[:4]
                total = sum(weight for _,weight in strongest)
                for slot,(bone,weight) in enumerate(strongest):
                    joint_ids[i,slot] = bone
                    weights[i,slot] = weight/total
        model.primitives.append({'node': 0, 'skin': mesh_skin, 'targets': [], 'names': [],
            'indices': ix.ravel(), 'material': {'name': name, 'doubleSided': True,
                'pbrMetallicRoughness': {'baseColorFactor': [*linear(color).tolist(), 1]}},
            'attributes': {'POSITION': p, 'NORMAL': normal, 'TEXCOORD_0': np.zeros((len(p), 2)),
                           'JOINTS_0': joint_ids, 'WEIGHTS_0': weights}})

    def rings(centers, radii, color, joint=0, axis='y', name='Hoodie'):
        count = 48; vertices = []; indices = []
        for center, (a, b) in zip(centers, radii):
            for n in range(count):
                angle = 2 * np.pi * n / count
                delta = [a * np.cos(angle), 0, b * np.sin(angle)] if axis == 'y' else [0, a * np.cos(angle), b * np.sin(angle)]
                vertices.append(np.array(center) + delta)
        for row in range(len(centers) - 1):
            for n in range(count):
                a = row * count + n; b = row * count + (n + 1) % count
                c = a + count; d = b + count
                indices += [a, c, b, b, c, d]
        if axis == 'x' and centers[-1][0] > centers[0][0]:
            indices = np.array(indices).reshape(-1, 3)[:, ::-1].ravel()
        mesh(vertices, indices, color, joint, name)

    def tube(points, radius, color, joint=0, name='Hoodie cord'):
        points=np.asarray(points,float)
        extended=np.vstack([points[0],points,points[-1]])
        path=[]
        for i in range(1,len(extended)-2):
            p0,p1,p2,p3=extended[i-1:i+3]
            for t in np.linspace(0,1,10,endpoint=False):
                path.append(.5*((2*p1)+(-p0+p2)*t+(2*p0-5*p1+4*p2-p3)*t*t+(-p0+3*p1-3*p2+p3)*t*t*t))
        path.append(points[-1]); path=np.array(path)
        if name == 'Hoodie cord':
            for point in path: point[2]=max(point[2],front_z(point[0],point[1])+.004)
        vertices=[]; indices=[]; sides=12
        for i,center in enumerate(path):
            tangent=path[min(i+1,len(path)-1)]-path[max(0,i-1)]
            tangent/=max(np.linalg.norm(tangent),1e-8)
            right=np.cross(tangent,[0,0,1]);right/=max(np.linalg.norm(right),1e-8)
            up=np.cross(tangent,right)
            for n in range(sides):
                a=n*2*np.pi/sides
                vertices.append(center+radius*(right*np.cos(a)+up*np.sin(a)))
            if i:
                for n in range(sides):
                    a=(i-1)*sides+n;b=(i-1)*sides+(n+1)%sides;c=i*sides+n;d=i*sides+(n+1)%sides
                    indices.extend([a,b,c,b,d,c])
        mesh(vertices,indices,color,joint,name)

    white = [.93, .98, 1.0]; teal = [.035, .65, .69]
    # Ribbed cuffs continue the tailored sleeve, instead of shoulder spheres.
    for side, lower in [(1, 4), (-1, 5)]:
        rings([(side*x, 1.2742, -.0255) for x in (.516,.532,.545)],
              [(.042,.042),(.040,.040),(.034,.034)], teal, lower, 'x', 'Hoodie cuff')
    # Folded hood with a real, darker inner lining and a thin rolled lip.
    # The neckline dips toward the chest and rises behind the neck.
    ucount = 80
    def hood_band(profiles, color, name):
        nonlocal triangles
        vertices=[]; indices=[]
        for u in range(ucount):
            a=2*np.pi*u/ucount
            front=max(0,np.sin(a)); back=max(0,-np.sin(a))
            for rx,rz,dy in profiles:
                vertices.append([rx*.94*np.cos(a),1.324+dy-.035*front-.012*front**8+.010*back,
                                 -.027+rz*np.sin(a)])
        count=len(profiles)
        for u in range(ucount):
            for v in range(count-1):
                a=u*count+v;b=((u+1)%ucount)*count+v
                indices.extend([a,b,a+1,a+1,b,b+1])
        mesh(vertices,indices,color,1,name)
        added=np.asarray(vertices)[np.asarray(indices).reshape(-1,3)]
        triangles=np.concatenate([triangles,added])
    hood_band([(.124,.137,-.038),(.119,.130,-.012),(.102,.116,.010),(.092,.107,.013)],
              white,'Hoodie outer hood')
    hood_band([(.092,.107,.013),(.082,.098,.009),(.068,.073,-.014),(.060,.056,-.030)],
              [.07,.40,.45],'Hoodie hood lining')
    hood_band([(.096,.110,.012),(.093,.108,.015),(.090,.105,.013)],
              [.72,.85,.91],'Hoodie hood seam')
    # Cords have curved paths, eyelets, and metal aglets instead of flat lines.
    for side in (-1,1):
        points=[(side*x,y,max(z,front_z(side*x,y)+.006)) for x,y,z in
                 [(.046,1.285,.099),(.049,1.245,.096),(.052,1.20,.12),(.053,1.155,.12),(.049,1.115,.12)]]
        tube(points,.0025,[.12,.38,.43])
        x,y,z=points[-1]
        tube([(x,y-.011,z),(x,y,z)],.0033,[.95,.72,.22],name='Sunshine cord tip')
    # Solid orange background with the turquoise W, following the cloth surface.
    vertices = []; indices = []
    for row,radius in enumerate(np.linspace(0,.041,9)):
        for n in range(64):
            a=2*np.pi*n/64
            vertices.append([radius*np.cos(a),1.16+radius*np.sin(a),.151])
            if row:
                a=(row-1)*64+n;b=(row-1)*64+(n+1)%64;c=row*64+n;d=row*64+(n+1)%64
                indices.extend([a,c,b,b,c,d])
    mesh(vertices, indices, [1, .79, .06], name='Sunshine emblem')
    points=np.array([(-.024,1.177),(-.012,1.14),(0,1.16),(.012,1.14),(.024,1.177)])
    # A rounded stroke, including rounded joins and caps; tessellation keeps
    # every part of the printed letter on the curved chest fabric.
    path=[points[0]]
    for i in range(1,len(points)-1):
        before,corner,after=points[i-1:i+2]
        incoming=(corner-before)/np.linalg.norm(corner-before)
        outgoing=(after-corner)/np.linalg.norm(after-corner)
        entry=corner-incoming*.008; leave=corner+outgoing*.008
        start=path[-1]
        path.extend(start+(entry-start)*t for t in np.linspace(0,1,9)[1:])
        path.extend((1-t)**2*entry+2*(1-t)*t*corner+t*t*leave for t in np.linspace(0,1,11)[1:])
    start=path[-1]
    path.extend(start+(points[-1]-start)*t for t in np.linspace(0,1,12)[1:])
    path=np.array(path); vertices=[];indices=[];radius=.0043
    for i,point in enumerate(path):
        tangent=path[min(i+1,len(path)-1)]-path[max(0,i-1)]
        normal=np.array([-tangent[1],tangent[0]])/np.linalg.norm(tangent)*radius
        vertices.extend([(*point+normal,.153),(*point-normal,.153)])
        if i:
            a=2*(i-1);b=a+1;c=a+2;d=a+3
            indices.extend([a,b,c,c,b,d])
    for point in (path[0],path[-1]):
        center=len(vertices);vertices.append([*point,.153])
        for n in range(24):
            a=n*2*np.pi/24
            vertices.append([*(point+radius*np.array([np.cos(a),np.sin(a)])),.153])
        for n in range(24):indices.extend([center,center+1+n,center+1+(n+1)%24])
    mesh(vertices,indices,teal,name='Hyprchan W')
    # Small four-point sunshine clip echoes the warm gold emblem without changing
    # her turquoise/white design. It is attached to the head, not the camera.
    vertices = [(-.065, 1.52, .075)]
    for n in range(8):
        a = np.pi/2 + n*np.pi/4
        r = .012 if n%2 == 0 else .004
        vertices.append([-.065+r*np.cos(a), 1.52+r*np.sin(a), .071])
    mesh(vertices, [v for n in range(8) for v in (0, n+1, (n+1)%8+1)], [1, .8, .12], 6, 'Sunshine clip')
