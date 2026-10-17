"""Small eye-proportion changes that retain the authored lids and expressions."""
import numpy as np


def eye_shape(points):
    p=np.asarray(points,dtype=np.float64)
    side=np.where(p[:,0]<0,-1.,1.)
    x=np.abs(p[:,0])-.043
    y=p[:,1]-1.444
    front=np.clip((p[:,2]-.015)/.025,0,1)
    front=front*front*(3-2*front)
    bridge=np.clip(np.abs(p[:,0])/.020,0,1)
    bridge=bridge*bridge*(3-2*bridge)
    influence=np.exp(-(x/.044)**4-(y/.036)**4)*front*bridge
    result=p.copy()
    result[:,0]+=side*x*.10*influence
    result[:,1]+=y*.16*influence
    return result


def eye_normals(points,normals):
    # Inverse-transpose of the local warp keeps the skin/eyelid lighting soft.
    delta=np.eye(3)*.00002
    jacobian=np.stack([(eye_shape(points+d)-eye_shape(points-d))/.00004 for d in delta],axis=-1)
    result=np.linalg.solve(jacobian.transpose(0,2,1),np.asarray(normals)[...,None])[...,0]
    result/=np.maximum(np.linalg.norm(result,axis=1,keepdims=True),1e-8)
    return result.astype(np.float32)


def shape_eyes(model):
    for primitive in model.primitives:
        name=primitive['material']['name']
        if not (name=='Face_00_SKIN' or name.startswith(('Eye','FaceEyeline','FaceBrow'))):
            continue
        attributes=primitive['attributes']
        points=attributes['POSITION'];normals=attributes['NORMAL']
        shaped=eye_shape(points).astype(np.float32)
        smooth=eye_normals(points,normals)
        targets=[]
        for original in primitive['targets']:
            target=dict(original)
            posed=points+original.get('POSITION',0)
            if 'POSITION' in original:
                target['POSITION']=(eye_shape(posed)-shaped).astype(np.float32)
            if 'NORMAL' in original:
                target['NORMAL']=eye_normals(posed,normals+original['NORMAL'])-smooth
            targets.append(target)
        attributes['POSITION']=shaped
        attributes['NORMAL']=smooth
        primitive['targets']=targets
