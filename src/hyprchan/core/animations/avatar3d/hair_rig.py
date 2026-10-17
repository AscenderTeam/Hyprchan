"""Length-preserving contact for the bundled VRM's long hair joint chains."""
import numpy as np


def solve_hair(model, local, world, update):
    from .model import from_to
    reference=[matrix[:3,3].copy() for matrix in world]
    # Garment volume in bind coordinates; the chest and hood follow their own
    # rig pivots. These include the tailored bust rather than the base tee.
    shapes=[('chest',(0,1.10,.005),(.14,.20,.115)),
            ('chest',(.052,1.177,.073),(.087,.085,.133)),
            ('chest',(-.052,1.177,.073),(.087,.085,.133)),
            ('upperChest',(0,1.31,-.030),(.123,.057,.143))]
    centers=[]; rotations=[]; radii=[]
    for bone,center,radius in shapes:
        index=model.bones[bone]
        transform=world[index]@model.inverse_bind_world[index]
        centers.append((transform@[*center,1])[:3]);rotations.append(transform[:3,:3]);radii.append(radius)
    centers=np.asarray(centers);rotations=np.asarray(rotations);radii=np.asarray(radii)
    capsules=[]
    for side in ('left','right'):
        points=[world[model.bones[side+name]][:3,3] for name in ('UpperArm','LowerArm','Hand')]
        capsules.extend([(points[0],points[1],.065),(points[1],points[2],.05)])
        palm=world[model.bones[side+'MiddleProximal']][:3,3]
        distal=model.bones[side+'MiddleDistal']
        children=model.nodes[distal].get('children',[])
        tip=(world[children[0]][:3,3] if children else
             2*world[distal][:3,3]-world[model.bones[side+'MiddleIntermediate']][:3,3])
        capsules.extend([(points[2],palm,.065),(palm,tip,.060)])
        thumb=world[model.bones[side+'ThumbDistal']][:3,3]
        capsules.append((points[2],thumb,.040))
    starts=np.array([a for a,_,_ in capsules]);ends=np.array([b for _,b,_ in capsules])
    segments=ends-starts;lengths=np.einsum('ij,ij->i',segments,segments)
    arm_radii=np.array([r for _,_,r in capsules])
    for spring in model.document['extensions']['VRMC_springBone']['springs']:
        joints=spring['joints']
        if spring.get('name')!='Hair' or len(joints)<4: continue
        for joint,child in zip(joints,joints[1:]):
            index,tail_index=joint['node'],child['node']
            origin=world[index][:3,3].copy();tail=world[tail_index][:3,3].copy()
            original=tail-origin;length=np.linalg.norm(original)
            # Restore each segment toward its authored direction after contact,
            # rather than propagating one collision bend through the whole tail.
            tail=origin+(reference[tail_index]-reference[index])
            hit=max(.024,float(joint.get('hitRadius',0)))+.010
            for _ in range(8):
                collided=False
                delta=np.einsum('kji,kj->ki',rotations,tail-centers)
                scale=np.linalg.norm(delta/(radii+hit),axis=1)
                nearest=int(np.argmin(scale))
                if scale[nearest]<1:
                    collided=True
                    corrected=delta[nearest]/max(scale[nearest],1e-5)
                    tail=centers[nearest]+rotations[nearest]@corrected
                t=np.clip(np.einsum('ij,ij->i',tail-starts,segments)/lengths,0,1)
                center=starts+segments*t[:,None];delta=tail-center
                distance=np.linalg.norm(delta,axis=1)
                nearest=int(np.argmin(distance-(arm_radii+hit)))
                if distance[nearest]<arm_radii[nearest]+hit:
                    collided=True
                    tail=center[nearest]+delta[nearest]/max(distance[nearest],1e-5)*(arm_radii[nearest]+hit)
                if not collided: break
                offset=tail-origin
                tail=origin+offset/max(np.linalg.norm(offset),1e-8)*length
            turn=from_to(original,tail-origin)
            parent=world[model.parents[index]][:3,:3]
            local[index][:3,:3]=parent.T@turn@parent@local[index][:3,:3]
            update(index)
