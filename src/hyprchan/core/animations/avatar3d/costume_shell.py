"""Continuous fitted bodice for the atelier costume, without cut-off sleeves."""
import numpy as np


def width(y):
    return (.098+.040*np.exp(-((y-1.185)/.105)**2)
            +.013*np.exp(-((y-1.26)/.048)**2))


def surface(y,theta):
    radius=width(y)
    x=radius*np.sin(theta)
    facing=np.cos(theta)
    front_radius=.094+.010*np.exp(-((y-1.16)/.10)**2)-.023*np.exp(-((y-1.30)/.035)**2)
    back_radius=.054+.006*np.exp(-((y-1.19)/.10)**2)
    z=-.022+np.where(facing>=0,front_radius,back_radius)*facing
    # A blouse bridges the sternum instead of tracing two inflated spheres.
    # The broader upper slope and lower, softly rounded fullness connect to
    # the rib cage; the old 16.5 cm displacement overwhelmed the torso.
    fullness=.86+.14*np.exp(-((abs(x)-.050)/.041)**2)
    vertical=np.where(y>1.174,.074,.058)
    z+=.068*np.exp(-((y-1.174)/vertical)**2)*fullness*np.maximum(facing,0)**1.2
    # Shallow sewn tension folds, continuous through the normals and lighting.
    for height in (1.055,1.115):
        d=y-height-.36*abs(x)
        z+=.0016*np.exp(-((abs(x)-.105)/.027)**2)*np.maximum(facing,0)*(
            np.exp(-((d+.008)/.011)**2)-np.exp(-(d/.007)**2))
    return x,y,z


def front_position(x,y,offset=0):
    # Continue a smooth cloth surface beyond the armhole for the overhanging
    # collar. Ray-casting onto the open base shirt made it jump between the
    # front, back and absent triangles, producing the torn-looking patches.
    theta=np.arcsin(np.clip(x/width(y),-.92,.92))
    return np.array([x,y,surface(y,theta)[2]+offset])


def fitted_bodice(source):
    vertical,around=81,129
    u,theta=np.meshgrid(np.linspace(0,1,vertical),np.linspace(0,2*np.pi,around),indexing='ij')
    # The front neckline rises into the collar straps and dips at the centre.
    # A horizontal tube opening made the collar read as a flat shoulder bib.
    front=np.maximum(np.cos(theta),0)
    top=1.281+.018*np.exp(-((abs(np.sin(theta))-.70)/.23)**2)*front
    top-=.019*np.exp(-(np.sin(theta)/.29)**2)*front
    y=.995+u*(top-.995)
    x,y,z=surface(y,theta)
    p=np.column_stack([x.ravel(),y.ravel(),z.ravel()]).astype(np.float32)
    triangles=[]
    for i in range(vertical-1):
        for j in range(around-1):
            a=i*around+j;b=a+around
            triangles.extend([(a,a+1,b),(a+1,b+1,b)])
    indices=np.asarray(triangles,np.uint32)
    normals=np.zeros_like(p)
    face=np.cross(p[indices[:,1]]-p[indices[:,0]],p[indices[:,2]]-p[indices[:,0]])
    for i in range(3):np.add.at(normals,indices[:,i],face)
    for i in range(vertical):
        a=i*around;b=a+around-1
        normals[a]=normals[b]=normals[a]+normals[b]
    normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-8)
    return {**source,'indices':indices.ravel(),'targets':[],'names':[],
            'attributes':{'POSITION':p,'NORMAL':normals,'TEXCOORD_0':np.zeros((len(p),2),np.float32)}}
