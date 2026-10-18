"""Skin-weight transfer for the collar's soft shoulder/back fold."""
import numpy as np


class CollarSkin:
    def __init__(self, model, skin):
        body=next(p for p in model.primitives if p['material']['name']=='Body_00_SKIN')
        attrs=body['attributes'];faces=body['indices'].reshape(-1,3)
        triangles=attrs['POSITION'][faces]
        keep=(triangles[:,:,1].max(1)>1.24)&(triangles[:,:,1].min(1)<1.345)
        keep&=(triangles[:,:,0].max(1)>-.15)&(triangles[:,:,0].min(1)<.15)
        self.triangles=triangles[keep].astype(float)
        source=model.skins[body['skin']][0];target=model.skins[skin][0]
        remap=np.array([target.index(joint) for joint in source])
        self.joints=remap[attrs['JOINTS_0'][faces[keep]].astype(int)]
        self.weights=attrs['WEIGHTS_0'][faces[keep]]

    def closest(self, points):
        """Closest triangle point: interior projection or clamped edge segment."""
        a,b,c=self.triangles.transpose(1,0,2);ab=b-a;ac=c-a
        d00=np.einsum('ij,ij->i',ab,ab);d01=np.einsum('ij,ij->i',ab,ac)
        d11=np.einsum('ij,ij->i',ac,ac);denom=d00*d11-d01*d01
        reciprocal=np.divide(1,denom,out=np.zeros_like(denom),where=denom>1e-16)
        output=[]
        for start in range(0,len(points),128):
            p=np.asarray(points[start:start+128],float);delta=p[:,None]-a
            d20=np.einsum('mij,ij->mi',delta,ab);d21=np.einsum('mij,ij->mi',delta,ac)
            v=(d11*d20-d01*d21)*reciprocal;w=(d00*d21-d01*d20)*reciprocal
            bary=np.stack([1-v-w,v,w],axis=-1)
            valid=(denom>1e-16)&(bary>=0).all(2)
            projected=a+v[:,:,None]*ab+w[:,:,None]*ac
            best=np.where(valid,((projected-p[:,None])**2).sum(2),np.inf)
            for i,j in [(0,1),(1,2),(2,0)]:
                origin=self.triangles[:,i];edge=self.triangles[:,j]-origin
                t=np.clip(np.einsum('mij,ij->mi',p[:,None]-origin,edge)/
                          np.maximum(np.einsum('ij,ij->i',edge,edge),1e-16),0,1)
                q=origin+t[:,:,None]*edge
                distance=((q-p[:,None])**2).sum(2);better=distance<best
                edge_bary=np.zeros_like(bary);edge_bary[:,:,i]=1-t;edge_bary[:,:,j]=t
                bary=np.where(better[:,:,None],edge_bary,bary);best=np.minimum(best,distance)
            face=best.argmin(1);row=np.arange(len(p))
            output.extend(zip(face,bary[row,face]))
        return output

    def blend(self, points, base):
        joints,weights=(a.copy() for a in base)
        # The collar is sewn to the bodice at the front; only its shoulder and
        # back region inherits the underlying neck/shoulder skin deformation.
        amount=np.clip((.040-points[:,2])/.035,0,1)*np.clip((points[:,1]-1.255)/.035,0,1)
        amount=amount*amount*(3-2*amount)
        active=np.flatnonzero(amount>0)
        for row,(triangle,bary) in zip(active,self.closest(points[active])):
            combined={int(j):float(w)*(1-amount[row]) for j,w in zip(joints[row],weights[row]) if w>0}
            for j,w in zip(self.joints[triangle].ravel(),(self.weights[triangle]*bary[:,None]).ravel()):
                combined[j]=combined.get(j,0)+float(w)*amount[row]
            top=sorted(combined.items(),key=lambda item:item[1],reverse=True)[:4]
            joints[row]=0;weights[row]=0
            for slot,(j,w) in enumerate(top):joints[row,slot]=j;weights[row,slot]=w
        weights/=weights.sum(1,keepdims=True)
        return joints,weights
