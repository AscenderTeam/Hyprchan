"""Layered cyan/yellow costume, fitted and skinned to the existing VRM garment.

Collar, ribbon folds, lace, piping and hardware are real meshes. Small pieces
are batched by material so detail does not require hundreds of draw calls.
The original hoodie builder remains independent and selectable.
"""
from collections import defaultdict
import numpy as np

from .materials import linear
from .wardrobe import add_hoodie
from .skin_yoke import restore_shoulders
from .costume_shell import fitted_bodice, front_position
from .neck_ribbon import NeckSurface

WHITE = [.96, .98, 1.0]
BLACK = [.055, .073, .105]
CYAN = [.02, .83, .88]
YELLOW = [1.0, .79, .08]
GOLD = [.98, .72, .19]


def garment_weights(model, skin, points, bone=None):
    """Use the same anatomical weights for the garment and its sewn layers.

    The base tee's shoulder aim bones stretch a connected sleeve. This outfit
    has separate sleeves, so those constraints must not pull on its bodice.
    """
    palette = model.skins[skin][0]
    joints = np.zeros((len(points),4),np.float32)
    weights = np.zeros_like(joints)
    if bone:
        joints[:,0] = palette.index(model.bones[bone]); weights[:,0] = 1
        return joints,weights
    for i,(x,y,z) in enumerate(points):
        if abs(x) > .165:
            side = 'left' if x>0 else 'right'
            names = [side+'UpperArm',side+'LowerArm']
            blend = np.clip((abs(x)-.29)/.09,0,1)
        else:
            names = ['chest','upperChest']
            blend = np.clip((y-1.10)/.13,0,1)
        blend = blend*blend*(3-2*blend)
        joints[i,:2] = [palette.index(model.bones[name]) for name in names]
        weights[i,:2] = [1-blend,blend]
    return joints,weights


def curve(points, count=64):
    points = np.asarray(points, float)
    padded = np.vstack([points[0], points, points[-1]])
    value = np.linspace(0, len(points)-1, count)
    segment = np.minimum(value.astype(int), len(points)-2)
    t = (value-segment)[:, None]
    a,b,c,d = (padded[segment+i] for i in range(4))
    return .5*((2*b)+(-a+c)*t+(2*a-5*b+4*c-d)*t*t+(-a+3*b-3*c+d)*t*t*t)


class Tailor:
    def __init__(self, model, shell):
        self.model, self.shell = model, shell
        self.attrs = shell['attributes']
        self.skin = shell['skin']
        self.joints = model.skins[self.skin][0]
        self.groups = defaultdict(list)

    def front(self, x, y, offset=.004):
        return front_position(x,y,offset)

    def weights(self, points, bone=None):
        if callable(bone):
            return bone(points)
        return garment_weights(self.model,self.skin,points,bone)

    def mesh(self, positions, faces, color, name='fabric', bone=None):
        p = np.asarray(positions,np.float32)
        faces = np.asarray(faces,np.uint32).reshape(-1,3)
        normals = np.zeros_like(p)
        n = np.cross(p[faces[:,1]]-p[faces[:,0]],p[faces[:,2]]-p[faces[:,0]])
        for corner in range(3): np.add.at(normals,faces[:,corner],n)
        # Merge coincident normals at closed tube seams and periodic surfaces.
        _,inverse = np.unique(np.round(p,7),axis=0,return_inverse=True)
        welded = np.zeros((inverse.max()+1,3),np.float32)
        np.add.at(welded,inverse,normals);normals=welded[inverse]
        normals /= np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-8)
        joints,weights = self.weights(p,bone)
        self.groups[name,tuple(color)].append((p,faces,normals,joints,weights))

    def grid(self, function, nu, nv, color, name='fabric', bone=None):
        p = [function(u,v) for u in np.linspace(0,1,nu) for v in np.linspace(0,1,nv)]
        faces=[]
        for row in range(nu-1):
            for col in range(nv-1):
                a=row*nv+col;b=a+nv
                faces.extend([(a,b,a+1),(a+1,b,b+1)])
        self.mesh(p,faces,color,name,bone)

    def tube(self, points, radius, color, name='piping', bone=None, sides=8):
        points=np.asarray(points,float)
        tangent=np.gradient(points,axis=0)
        tangent/=np.maximum(np.linalg.norm(tangent,axis=1,keepdims=True),1e-8)
        reference=np.tile([0.,0.,1.],(len(points),1))
        reference[abs(tangent[:,2])>.9]=[0,1,0]
        right=np.cross(tangent,reference);right/=np.linalg.norm(right,axis=1,keepdims=True)
        up=np.cross(tangent,right)
        p=[];faces=[]
        for i,point in enumerate(points):
            for j in range(sides):
                a=2*np.pi*j/sides
                p.append(point+radius*(np.cos(a)*right[i]+np.sin(a)*up[i]))
                if i:
                    a=(i-1)*sides+j;b=(i-1)*sides+(j+1)%sides;c=i*sides+j;d=i*sides+(j+1)%sides
                    faces.extend([(a,b,c),(b,d,c)])
        self.mesh(p,faces,color,name,bone)

    def seam(self, points, radius, color, offset=.006, name='piping'):
        path=curve(points)
        self.tube([self.front(x,y,offset) for x,y in path],radius,color,name)

    def button(self, x, y, radius, color, offset=.010, name='metal', bone=None):
        center=self.front(x,y,offset)
        self.grid(lambda u,v: center+np.array([radius*np.sin(np.pi*u)*np.cos(v*2*np.pi),
                   radius*np.sin(np.pi*u)*np.sin(v*2*np.pi),radius*.40*np.cos(np.pi*u)]),
                  10,25,color,name,bone)

    def finish(self):
        for (name,color),parts in self.groups.items():
            offsets=np.cumsum([0]+[len(p[0]) for p in parts[:-1]])
            position,normal,joints,weights = (np.concatenate([p[i] for p in parts]) for i in (0,2,3,4))
            self.model.primitives.append({'node':0,'skin':self.skin,'targets':[],'names':[],
                'indices':np.concatenate([p[1]+offset for p,offset in zip(parts,offsets)]).astype(np.uint32).ravel(),
                'material':{'name':'Costume '+name,'doubleSided':True,
                    'pbrMetallicRoughness':{'baseColorFactor':[*linear(color).tolist(),1]}},
                'attributes':{'POSITION':position,'NORMAL':normal,'JOINTS_0':joints,'WEIGHTS_0':weights,
                              'TEXCOORD_0':np.zeros((len(position),2),np.float32)}})


def add_costume(model):
    # Keep the original hoodie independent; retain only its two hair pins.
    # This costume uses a continuous bodice and separately rigged sleeves.
    add_hoodie(model)
    restore_shoulders(model)
    source=next(p for p in model.primitives if p['material']['name']=='Hoodie shell')
    shell=fitted_bodice(source)
    shell['attributes']['JOINTS_0'],shell['attributes']['WEIGHTS_0'] = garment_weights(
        model,shell['skin'],shell['attributes']['POSITION'])
    keep={'Sunshine clip','Hyprland pin cord'}
    model.primitives=[p for p in model.primitives if not p['material']['name'].startswith(('Hoodie','Sunshine','Hyprchan W'))
                      or p['material']['name'] in keep]
    tailor=Tailor(model,shell)
    model.primitives.append({**shell,
        'material':{'name':'Costume bodice','doubleSided':True,
                    'pbrMetallicRoughness':{'baseColorFactor':[*linear(WHITE).tolist(),1]}}})
    model.costume='cyan_yellow'

    # Rounded sailor/Peter Pan collar: a sculpted upper surface, rolled edges,
    # opposing accent colors, and a second fine inset trim.
    inner=curve([(.035,1.315),(.040,1.289),(.032,1.259),(.020,1.234),(.004,1.220)],73)
    outer=curve([(.079,1.320),(.083,1.290),(.072,1.259),(.045,1.231),(.009,1.214)],73)
    # Camisole bridges the open neckline beneath the two collar leaves.
    def camisole(u,v):
        x=(v-.5)*.091
        y=1.265+.005*(abs(v-.5)*2)**2-u*.043
        return tailor.front(x,y,.006)
    tailor.grid(camisole,25,41,BLACK,'underlay')
    tailor.tube([camisole(0,v)+[0,0,.002] for v in np.linspace(0,1,65)],.0015,WHITE,'camisole edging')
    # Continue both lapels around the back of the neck instead of leaving
    # their upper ends as flat, visibly cut-off strips in the front portrait.
    def back_collar(u,v):
        angle=np.pi*u
        radius=.035*(1-v)+.079*v
        y=1.315+.005*v
        z=tailor.front(radius,y,.009+.006*np.sin(np.pi*v))[2]
        return [radius*np.cos(angle),y+.014*np.sin(angle),z-.103*np.sin(angle)]
    tailor.grid(back_collar,65,25,WHITE,'collar')
    for first,last,accent in [(0,.5,YELLOW),(.5,1,CYAN)]:
        for v,r,color in [(1,.0023,accent),(.86,.0008,BLACK),(.78,.0007,accent),(0,.0013,BLACK)]:
            tailor.tube([np.array(back_collar(u,v))+[0,.001,0] for u in np.linspace(first,last,41)],r,color,'collar trim')
    for side,accent in [(-1,CYAN),(1,YELLOW)]:
        def collar(u,v):
            index=min(72,int(round(u*72)))
            xy=inner[index]*(1-v)+outer[index]*v
            return tailor.front(side*xy[0],xy[1],.009+.006*np.sin(np.pi*v))
        tailor.grid(collar,73,41,WHITE,'collar')
        for v,r,color in [(1,.0023,accent),(.86,.0008,BLACK),(.78,.0007,accent),(0,.0013,BLACK)]:
            tailor.tube([collar(u,v)+[0,0,.003] for u in np.linspace(0,1,73)],r,color,'collar trim')
        # Two fine rows of embroidered stitches sit between the rolled trims.
        for u in np.linspace(.08,.88,22):
            tailor.tube([collar(u-.003,v)+[0,0,.002] for v in np.linspace(.87,.95,3)],
                        .00035,WHITE,'stitching',sides=6)

        # Fitted dark side inserts, princess seams and small functional lacing.
        def insert(u,v):
            y=1.235-u*.21
            middle=.126-.038*u
            half_width=.0105*np.sin(np.pi*u)**.40
            inside=middle-half_width;outside=middle+half_width
            return tailor.front(side*(inside+(outside-inside)*v),y,.007)
        tailor.grid(insert,49,9,BLACK,'side panels')
        for v in (0,1):
            tailor.tube([insert(u,v)+[0,0,.002] for u in np.linspace(0,1,49)],.0013,accent)
        for row in range(6):
            u=.13+row*.14
            for v in (.22,.78):
                p=insert(u,v)
                tailor.button(p[0],p[1],.0027,GOLD,offset=.010)
            if row<5:
                for v in (.22,.78):
                    points=[insert(u+(q*.14),v*(1-q)+(1-v)*q)+[0,0,.005] for q in np.linspace(0,1,9)]
                    tailor.tube(points,.0008,accent,'lacing')

        # Detached sleeve headers: rolled black edge, scalloped lace and
        # alternating accent bands follow the same upper/lower arm blend.
        def sleeve(x,angle,extra=0):
            fraction=np.clip((x-.185)/.35,0,1)
            fullness=np.sin(np.pi*fraction)
            gather=(np.exp(-((fraction-.45)/.2)**2)+np.exp(-((fraction-.88)/.12)**2))
            fold=.0028*np.sin(x*178+angle*2)*gather*np.sin(np.pi*fraction)
            ry=.054*(1-fraction)+.038*fraction+.005*fullness+fold
            rz=.051*(1-fraction)+.038*fraction+.003*fullness+fold
            return np.array([side*x,1.2742-.003*fullness+(ry+extra)*np.cos(angle),
                             -.0255+(rz+extra)*np.sin(angle)])
        tailor.grid(lambda u,v:sleeve(.188+.347*u,2*np.pi*v),89,65,WHITE,'sleeves')
        for start,end,color in [(.179,.198,BLACK),(.198,.205,accent),(.205,.209,BLACK),
                                (.499,.514,BLACK),(.514,.523,accent),(.523,.535,WHITE)]:
            tailor.grid(lambda u,v:sleeve(start+(end-start)*u,2*np.pi*v,.003),5,65,color,'sleeve bands')
        for i in range(24):
            theta=i*2*np.pi/24
            points=[sleeve(.181-.006*np.sin(np.pi*t),theta+t*2*np.pi/24,.004) for t in np.linspace(0,1,13)]
            tailor.tube(points,.0013,BLACK,'lace')
        for x0 in (.199,.514):
            tailor.tube([sleeve(x0,theta,.004) for theta in np.linspace(0,2*np.pi,65)],.001,GOLD,'metal')

    # A narrow raised placket, twin fine seams and alternating inset buttons.
    tailor.grid(lambda u,v:tailor.front((v-.5)*.022,1.212-u*.20,.004),57,7,WHITE,'placket')
    for side in (-1,1):tailor.seam([(side*.011,1.212),(side*.011,1.10),(side*.011,1.012)],.0007,BLACK)
    for index,y in enumerate([1.185,1.143,1.101,1.059]):
        tailor.button(0,y,.0062,GOLD)
        tailor.button(0,y,.0043,CYAN if index%2==0 else YELLOW,offset=.0125,name='enamel')
        for x in (-.0011,.0011):tailor.button(x,y,.00055,BLACK,offset=.015,name='button stitch')

    # Folded bow with a white inlaid stripe. Real domed folds cast a separate
    # shadow on the bodice; the trailing ribbons lie over the curved fabric.
    for side,accent in [(-1,CYAN),(1,YELLOW)]:
        def loop(u,v):
            width=.006+.011*(1-np.exp(-u*8))
            x=side*(.006+.054*u-.003*u**8*(v*2-1)**2)
            y=1.228+(v*2-1)*width+.004*u
            # Rounded, tucked outer ends and a pinched centre create a folded
            # ribbon silhouette instead of two flat semicircular wings.
            bulge=np.sin(np.pi*u)**.7
            fold=.010*np.cos((v-.5)*np.pi)+.010*np.cos(v*2*np.pi)*u
            return tailor.front(x,y,.025+.022*bulge+fold)
        tailor.grid(loop,41,17,BLACK,'bow')
        tailor.grid(lambda u,v:loop(u,.43+.14*v)+[0,0,.001],41,4,WHITE,'bow stripe')
        tailor.tube([loop(u,.95)+[0,0,.001] for u in np.linspace(0,1,41)],.0007,accent,'bow trim')
        def tail(u,v):
            x=side*(.009+.026*u)+(v-.5)*.021
            y=1.223-.079*u+.008*u**8*(1-abs(v*2-1))
            return tailor.front(x,y,.023+.008*np.sin(u*np.pi))
        tailor.grid(tail,33,9,BLACK,'bow')
        tailor.grid(lambda u,v:tail(u,.43+.14*v)+[0,0,.001],33,3,WHITE,'bow stripe')
        tailor.grid(lambda u,v:tail(.91+.09*u,v)+[0,0,.001],5,9,accent,'bow tips')
    tailor.button(0,1.227,.0105,GOLD,offset=.047)
    tailor.button(0,1.227,.0078,CYAN,offset=.050,name='enamel')
    w=curve([(-.0046,1.2295),(-.0024,1.2235),(0,1.227),(.0024,1.2235),(.0046,1.2295)],45)
    tailor.tube([tailor.front(x,y,.0545) for x,y in w],.0008,WHITE,'monogram')

    # A short linked watch-chain and star clasp on the collar, echoing the
    # sparkle hairpin. Alternating link planes give the chain real depth.
    chain=curve([(-.060,1.292),(-.055,1.272),(-.039,1.254),(-.026,1.254)],19)
    for index,(x,y) in enumerate(chain):
        angle=index%2*np.pi/3
        xy_tangent=chain[min(index+1,len(chain)-1)]-chain[max(index-1,0)]
        xy_tangent/=max(np.linalg.norm(xy_tangent),1e-8)
        a=np.array([*xy_tangent,0]); b=np.array([-a[1],a[0],0])*np.cos(angle)+[0,0,np.sin(angle)]
        center=tailor.front(x,y,.021)
        tailor.tube([center+.0024*np.cos(t)*a+.0015*np.sin(t)*b for t in np.linspace(0,2*np.pi,17)],
                    .00055,GOLD,'metal',sides=6)
    star=[]
    for i in range(8):
        angle=np.pi/2+i*np.pi/4; r=.006 if i%2==0 else .0025
        star.append(tailor.front(-.060+r*np.cos(angle),1.292+r*np.sin(angle),.023))
    center=tailor.front(-.060,1.292,.026)
    tailor.mesh([center,*star],[(0,i+1,(i+1)%8+1) for i in range(8)],GOLD,'metal')

    # Fit below the chin, with a small air gap and the skin's actual blended
    # influences. A fixed oval on the neck bone cut into the jaw in head poses.
    neck_surface=NeckSurface(model,tailor.skin)
    ring=[]
    for u in np.linspace(0,1,9):
        for angle in np.linspace(0,2*np.pi,97):
            ring.append([np.cos(angle),1.328+.011*u-.002*np.sin(angle),-.025+np.sin(angle)])
    ring=neck_surface.fit(ring).reshape(9,97,3)
    def neck(u,v):
        return ring[int(round(u*8)),int(round(v*96))]
    tailor.grid(neck,9,97,BLACK,'neck ribbon',neck_surface)
    for u,color in [(0,CYAN),(1,YELLOW)]:
        tailor.tube([neck(u,v) for v in np.linspace(0,1,97)],.00065,color,'neck edging',neck_surface)
    # Lower the charm with the ribbon; each part also follows the local skin.
    for center_y,radius in [(1.329,.0035),(1.318,.0055)]:
        points=[[radius*np.cos(t),center_y+radius*np.sin(t),.03] for t in np.linspace(0,2*np.pi,41)]
        tailor.tube(neck_surface.fit(points,.005),.001,GOLD,'neck charm',neck_surface)
    tailor.tube(neck_surface.fit([[-.004,1.310,.03],[0,1.305,.03],[.004,1.310,.03]],.005),
                .001,GOLD,'neck charm',neck_surface)
    tailor.finish()
