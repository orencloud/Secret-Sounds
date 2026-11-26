"""Track loop-ring identity using an edit-mesh BVH built once per targeting stage."""

from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils
import bmesh


class RingPicker:
    def __init__(self, obj):
        self.mesh = bmesh.from_edit_mesh(obj.data)
        self.mesh.faces.index_update()
        self.mesh.faces.ensure_lookup_table()
        self.tree = BVHTree.FromBMesh(self.mesh)
        self.mesh.edges.index_update()
        self.inverse = obj.matrix_world.inverted_safe()
        self.world = obj.matrix_world.copy()
        self.rings = {}

    def ring(self, seed):
        if seed.index in self.rings:
            return self.rings[seed.index]
        found = {seed.index}
        agenda = [seed]
        while agenda:
            edge = agenda.pop()
            for face in edge.link_faces:
                if len(face.verts) != 4 or face.hide:
                    continue
                sides = tuple(loop.edge for loop in face.loops)
                opposite = sides[(sides.index(edge) + 2) % 4]
                if opposite.index not in found:
                    found.add(opposite.index)
                    agenda.append(opposite)
        key = min(found)
        self.rings.update(dict.fromkeys(found, key))
        return key

    def pick(self, area, region, xy):
        rv3d = area.spaces.active.region_3d
        xy = Vector((xy[0] - region.x, xy[1] - region.y))
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, xy)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, xy)
        _, _, index, _ = self.tree.ray_cast(self.inverse @ origin, self.inverse.to_3x3() @ direction)
        if index is None or index >= len(self.mesh.faces):
            return None
        face = self.mesh.faces[index]
        if face.hide:
            return None
        best, distance = None, float("inf")
        for edge in face.edges:
            if edge.hide or not any(len(adjacent.verts) == 4 and not adjacent.hide for adjacent in edge.link_faces):
                continue
            a, b = (view3d_utils.location_3d_to_region_2d(region, rv3d, self.world @ vertex.co) for vertex in edge.verts)
            if a is None or b is None:
                continue
            ab = b - a
            t = max(0, min(1, (xy - a).dot(ab) / max(1e-9, ab.length_squared)))
            score = (xy - a - t * ab).length_squared
            if score < distance:
                best, distance = edge, score
        return self.ring(best) if best is not None else None
