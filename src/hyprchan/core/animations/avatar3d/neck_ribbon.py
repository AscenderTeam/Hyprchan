"""Fit the costume's neck ribbon to the skin, including its bone influences."""
import numpy as np


class NeckSurface:
    def __init__(self, model, skin):
        body = next(p for p in model.primitives if p['material']['name'] == 'Body_00_SKIN')
        attrs = body['attributes']
        faces = body['indices'].reshape(-1, 3)
        triangles = attrs['POSITION'][faces]
        keep = (triangles[:, :, 1].min(1) < 1.36) & (triangles[:, :, 1].max(1) > 1.29)
        self.triangles = triangles[keep].astype(float)
        faces = faces[keep]
        source = model.skins[body['skin']][0]
        target = model.skins[skin][0]
        remap = np.array([target.index(joint) for joint in source])
        self.joints = remap[attrs['JOINTS_0'][faces].astype(int)]
        self.weights = attrs['WEIGHTS_0'][faces]

    def sample(self, points):
        """Horizontal rays from the neck axis; return surface and barycentrics."""
        points = np.asarray(points, float)
        origin = np.zeros_like(points)
        origin[:, 1] = points[:, 1]
        origin[:, 2] = -.025
        direction = points - origin
        direction /= np.linalg.norm(direction, axis=1, keepdims=True)
        a, b, c = self.triangles.transpose(1, 0, 2)
        edge1, edge2 = b-a, c-a
        h = np.cross(direction[:, None], edge2)
        determinant = np.einsum('mij,ij->mi', h, edge1)
        reciprocal = np.divide(1, determinant, out=np.zeros_like(determinant),
                               where=abs(determinant) > 1e-10)
        s = origin[:, None]-a
        u = np.einsum('mij,mij->mi', s, h)*reciprocal
        q = np.cross(s, edge1)
        v = np.einsum('mj,mij->mi', direction, q)*reciprocal
        distance = np.einsum('ij,mij->mi', edge2, q)*reciprocal
        hit = (abs(determinant) > 1e-10) & (u >= -1e-7) & (v >= -1e-7) & (u+v <= 1+1e-7) & (distance > 0)
        distance = np.where(hit, distance, np.inf)
        triangle = distance.argmin(1)
        row = np.arange(len(points))
        depth = distance[row, triangle]
        if not np.isfinite(depth).all():
            raise ValueError('Neck ribbon sample missed the skin surface')
        barycentric = np.column_stack([1-u[row, triangle]-v[row, triangle],
                                       u[row, triangle], v[row, triangle]])
        barycentric = np.maximum(barycentric, 0)
        barycentric /= barycentric.sum(1, keepdims=True)
        return origin+direction*depth[:, None], direction, triangle, barycentric

    def fit(self, points, clearance=.003):
        surface, outward, _, _ = self.sample(points)
        return surface + outward*clearance

    def __call__(self, points):
        """Transfer interpolated influences, rather than binding to neck alone."""
        _, _, triangles, barycentric = self.sample(points)
        joints = np.zeros((len(points), 4), np.float32)
        weights = np.zeros_like(joints)
        for row, (triangle, bary) in enumerate(zip(triangles, barycentric)):
            combined = {}
            for joint, weight in zip(self.joints[triangle].ravel(),
                                     (self.weights[triangle]*bary[:, None]).ravel()):
                combined[joint] = combined.get(joint, 0) + weight
            top = sorted(combined.items(), key=lambda item: item[1], reverse=True)[:4]
            for slot, (joint, weight) in enumerate(top):
                joints[row, slot], weights[row, slot] = joint, weight
        weights /= weights.sum(1, keepdims=True)
        return joints, weights
