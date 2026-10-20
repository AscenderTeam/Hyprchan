"""Refine long hair once so contact bends cannot cut across the cloth in a chord."""
import numpy as np


def refine_hair(model, edge_length=.009):
    for primitive in model.primitives:
        if 'HAIR' not in primitive['material']['name']: continue
        attributes=primitive['attributes']
        if primitive['targets']: raise ValueError('Hair contact refinement needs unmorphed hair')
        values={name:list(data) for name,data in attributes.items() if name not in {'JOINTS_0','WEIGHTS_0'}}
        influences=[{int(j):float(w) for j,w in zip(js,ws) if w>0}
                    for js,ws in zip(attributes['JOINTS_0'],attributes['WEIGHTS_0'])]
        faces=primitive['indices'].reshape(-1,3)
        def point(indices):
            index=len(values['POSITION'])
            for channel,data in values.items(): data.append(np.mean([data[i] for i in indices],axis=0))
            weights={}
            for i in indices:
                for bone,weight in influences[i].items(): weights[bone]=weights.get(bone,0)+weight/len(indices)
            influences.append(weights)
            return index
        for _ in range(5):
            positions=np.asarray(values['POSITION'])
            edges=np.unique(np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1),axis=0)
            long=((np.linalg.norm(positions[edges[:,0]]-positions[edges[:,1]],axis=1)>edge_length)
                  & (positions[edges,1].min(axis=1)<1.46))
            edges=edges[long]
            if not len(edges): break
            mids={tuple(edge):point(edge) for edge in edges}
            divided=[]
            for face in faces:
                m=[mids.get(tuple(sorted((face[i],face[(i+1)%3])))) for i in range(3)]
                count=sum(value is not None for value in m)
                if count==0: divided.append(face)
                elif count==3:
                    a,b,c=face;ab,bc,ca=m
                    divided.extend([(a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)])
                elif count==1:
                    k=next(i for i in range(3) if m[i] is not None)
                    a,b,c=(face[(k+i)%3] for i in range(3));ab=m[k]
                    divided.extend([(a,ab,c),(ab,b,c)])
                else:
                    k=next(i for i in range(3) if m[i] is not None and m[(i+2)%3] is not None)
                    a,b,c=(face[(k+i)%3] for i in range(3));ab,ca=m[k],m[(k+2)%3]
                    divided.extend([(a,ab,ca),(ab,b,c),(ab,c,ca)])
            faces=np.asarray(divided,dtype=np.uint32)
        weights=np.zeros((len(influences),4),dtype=np.float32); joints=np.zeros_like(weights)
        for i,values_ in enumerate(influences):
            strongest=sorted(values_.items(),key=lambda item:item[1],reverse=True)[:4]
            total=sum(weight for _,weight in strongest)
            for slot,(bone,weight) in enumerate(strongest): joints[i,slot]=bone;weights[i,slot]=weight/total
        updated={name:np.asarray(data,dtype=np.float32) for name,data in values.items()}
        updated['NORMAL']/=np.maximum(np.linalg.norm(updated['NORMAL'],axis=1,keepdims=True),1e-8)
        updated.update(JOINTS_0=joints,WEIGHTS_0=weights)
        primitive['attributes']=updated
        primitive['indices']=faces.ravel()
