"""Fit and audit attachments in KSP coordinates using the exported meshes."""

from functools import lru_cache
from math import asin, atan2, cos, sin

from models import cross, minus, unit
from parts import ART
from vendor.mu import Mu

STOCK_CHUTE = "Squad/Parts/Utility/parachuteMk2-R"
# Mk2-R base plate corners in stock KSP 1.12.5. The cap exits toward local -Z.
CHUTE_BACK = tuple((x, y, 0.07529) for x in (-0.2137, 0.2137) for y in (-0.3969, 0.3976))
CORER_BACK = tuple((x, y, 0.10) for x in (-0.175, 0.175) for y in (-0.13, 0.21))


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def scale(v, factor):
    return tuple(x * factor for x in v)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def rotate(q, v):
    """Apply a quaternion in wxyz order."""
    w, x, y, z = q
    u = cross((x, y, z), v)
    return add(v, scale(add(scale(u, w), cross((x, y, z), u)), 2))


def world_direction(rotation, vector):
    return rotate(unit((rotation[3], *rotation[:3])), vector)


def world_point(position, rotation, vector):
    return add(position, world_direction(rotation, vector))


def local_direction(rotation, vector):
    return world_direction((*scale(rotation[:3], -1), rotation[3]), vector)


@lru_cache
def mesh_triangles(path, names, discard_root_pose=False):
    """Unwrap exported meshes, including nested stock model transforms, into Unity XYZ."""
    triangles = []

    def visit(obj, ancestors):
        transforms = ancestors if discard_root_pose and obj is root else (obj.transform, *ancestors)
        mesh = getattr(obj, "shared_mesh", None)
        if mesh is not None and obj.transform.name in names:
            vertices = []
            for vertex in mesh.verts:
                for step in transforms:
                    local = tuple(v * factor for v, factor in zip(vertex, step.localScale))
                    vertex = add(rotate(unit(step.localRotation), local), step.localPosition)
                vertices.append((vertex[0], vertex[2], vertex[1]))
            triangles.extend(tuple(vertices[i] for i in face) for group in mesh.submeshes for face in group)
        for child in obj.children:
            visit(child, transforms)

    root = Mu().read(path).obj
    visit(root, ())
    if not triangles:
        raise ValueError(f"{path.name} lacks {', '.join(names)} geometry")
    return tuple(triangles)


def surface_offset(shell, point, outward):
    """Signed distance from a mount sample to the outer skin along its outward axis."""
    distance = 8
    origin = add(point, scale(outward, distance))
    closest = float("inf")
    for a, b, c in shell:
        ab, ac = minus(b, a), minus(c, a)
        h = cross(outward, ac)
        divisor = dot(ab, h)
        if abs(divisor) < 1e-9:
            continue
        relative = minus(origin, a)
        u = dot(relative, h) / divisor
        if not -1e-8 <= u <= 1 + 1e-8:
            continue
        q = cross(relative, ab)
        v = dot(outward, q) / divisor
        if v < -1e-8 or u + v > 1 + 1e-8:
            continue
        hit = -dot(ac, q) / divisor
        if 0 <= hit < closest:
            closest = hit
    return distance - closest


def surface_pose(parent, child, height, azimuth):
    shell = mesh_triangles(ART / (parent + ".mu"), ("Exterior",))
    radial = (cos(azimuth), 0, sin(azimuth))
    center = (0, height, 0)
    if child == "parachuteRadial":
        back = CHUTE_BACK
        # A long foot spans a curved shell. Match the slope across its length.
        heights = [surface_offset(shell, (0, height + dy, 0), radial) for dy in (-0.33, 0.33)]
        slope = (heights[1] - heights[0]) / 0.66
    else:
        back = CORER_BACK
        slope = 0
    outward = unit((radial[0], -slope, radial[2]))
    yaw, pitch = atan2(-outward[0], -outward[2]) / 2, asin(outward[1]) / 2
    rotation = (cos(yaw) * sin(pitch), sin(yaw) * cos(pitch), -sin(yaw) * sin(pitch), cos(yaw) * cos(pitch))
    center = add(center, scale(radial, surface_offset(shell, center, radial)))
    inset = min(surface_offset(shell, world_point(center, rotation, p), outward) for p in back)
    if inset == -float("inf"):
        raise ValueError(f"{child} footprint runs off {parent} shell")
    return add(center, scale(outward, inset - 0.006)), rotation


def mount_samples(kind, model_path=None):
    """Use the base and outward cover from the installed part for placement checks."""
    if kind == "parachuteRadial":
        if model_path:
            base = {v for face in mesh_triangles(model_path, ("base",)) for v in face}
            back = max(v[2] for v in base)
            pad = tuple(v for v in base if back - v[2] < 1e-5)
            cap = tuple({v for face in mesh_triangles(model_path, ("cap",)) for v in face})
            return pad, cap
        return CHUTE_BACK, ((0, 0, -0.13), (0, -0.27, -0.10), (0, 0.19, -0.10))
    vertices = {v for face in mesh_triangles(model_path, ("Exterior",)) for v in face}
    back = max(v[2] for v in vertices)
    return tuple(v for v in vertices if back - v[2] < 1e-5), tuple(v for v in vertices if v[2] < -0.09)
