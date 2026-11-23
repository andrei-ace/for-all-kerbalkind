"""Parametric Blender-space meshes and KSP scene nodes. Z is the vehicle axis."""

import math
import struct
import zlib
from itertools import pairwise
from math import cos, pi, sin, sqrt, tau

from parts import (
    AIRLOCK_LENGTH,
    AIRLOCK_SIDE,
    DOCK_DEPTH,
    SERVO_DEPTH,
    STATION_SEATS,
    ART,
    CAPSULES,
    CREWED_LANDERS,
    END_DOCK_SEAT,
    FRAMES,
    HAB_ANTENNA,
    HAB_BELL_CLEARANCE,
    HAB_BELL_X,
    HAB_BELL_Z,
    HAB_LADDER,
    HAB_PORT_X,
    HAB_PORT_Y,
    HAB_PORTS,
    HAB_SOLAR,
    JACKS,
    PAD_DEPTH,
    REAR_DOCK_SEAT,
    REVIEW_CARRIER_SEAT,
    REVIEW_DOCK_HEIGHT,
    ROOF_DOCK_SEAT,
    STAIR_CLIP,
    STAIR_DURATION,
    STAIR_FOLD,
    STAIR_GROUP,
    STAIR_TREAD_COUNT,
)
from vendor import mu

# Each tile is an original surface finish, with a two-pixel UV gutter.
PAINT = {
    "ivory": (217, 217, 202),
    "ink": (40, 47, 52),
    "alloy": (165, 177, 180),
    "steel": (92, 105, 109),
    "sage": (134, 149, 130),
    "olive": (83, 104, 91),
    "gold": (199, 142, 57),
    "foil": (225, 183, 94),
    "glass": (45, 101, 127),
    "red": (178, 74, 54),
    "solar": (55, 78, 115),
    "nozzle": (62, 55, 54),
    "copper": (156, 113, 78),
    "white": (234, 233, 223),
    "gasket": (51, 55, 59),
    "warning": (210, 155, 54),
}


def write_atlas():
    size, tile = 256, 64
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            name = tuple(PAINT)[(3 - y // tile) * 4 + x // tile]
            u, v = x % tile, y % tile
            shade = ((x * 41 ^ y * 73) % 9 - 4) * 0.55
            if name in ("gold", "foil"):
                shade += 8 * sin(u * 0.26 + 1.7 * sin(v * 0.21)) + 6 * cos(v * 0.31 + u * 0.12)
            elif name == "solar":
                shade += 38 if u % 16 == 0 or v % 8 == 0 else 2 * sin(v)
            elif name == "glass":
                shade += 26 * (1 - v / tile) + (11 if 47 < u + v < 52 else 0)
            elif name == "warning":
                shade -= 95 if (u + v) % 32 < 11 else 0
            else:
                shade += 4 * cos(v / tile * pi)
                if u in (3, 60) or v in (3, 60):
                    shade -= 15
                if u in (7, 56) and v in (7, 56):
                    shade -= 50
            pixels.extend(max(0, min(255, round(c + shade))) for c in PAINT[name])

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">2I5B", size, size, 8, 2, 0, 0, 0)
    (ART / "livery.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels, 9))
        + chunk(b"IEND", b"")
    )


def minus(a, b):
    return tuple(x - y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(v):
    length = math.sqrt(sum(x * x for x in v))
    return tuple(x / length for x in v)


def point(radius, angle, z):
    return (radius * cos(angle), radius * sin(angle), z)


def profile_radius(profile, z):
    for (lower, inner), (upper, outer) in pairwise(profile):
        if lower <= z <= upper:
            return inner + (outer - inner) * (z - lower) / (upper - lower)
    raise ValueError(f"{z} falls outside the hull profile")


class Surface:
    def __init__(self):
        self.mesh = mu.MuMesh()
        self.mesh.submeshes = [[]]

    def face(self, vertices, finish):
        normal = unit(cross(minus(vertices[1], vertices[0]), minus(vertices[2], vertices[0])))
        start = len(self.mesh.verts)
        self.mesh.verts.extend(vertices)
        self.mesh.normals.extend([normal] * len(vertices))
        index = tuple(PAINT).index(finish)
        for u, v in ((0.045, 0.045), (0.955, 0.045), (0.955, 0.955), (0.045, 0.955))[: len(vertices)]:
            self.mesh.uvs.append(((index % 4 + u) / 4, (index // 4 + v) / 4))
        for i in range(1, len(vertices) - 1):
            self.mesh.submeshes[0].append((start, start + i, start + i + 1))

    def lathe(self, profile, finish, segments=32, xy=(0, 0), stripe=None, angle=0, orient=None, caps=True):
        """Ordered (height, radius) stations. Reversing a profile exposes its inner skin."""
        rings = [
            [
                (xy[0] + r * cos(angle + tau * i / segments), xy[1] + r * sin(angle + tau * i / segments), z)
                for i in range(segments)
            ]
            for z, r in profile
        ]
        if orient:
            rings = [[orient(*vertex) for vertex in ring] for ring in rings]
        for n, (lower, upper) in enumerate(pairwise(rings)):
            for i in range(segments):
                j = (i + 1) % segments
                paint = stripe(n, i) if stripe else finish
                self.face((lower[i], lower[j], upper[j], upper[i]), paint)
        if caps:
            for i in range(1, segments - 1):
                self.face((rings[0][0], rings[0][i + 1], rings[0][i]), finish)
                self.face((rings[-1][0], rings[-1][i], rings[-1][i + 1]), finish)

    def box(self, centre, size, finish, angle=0):
        vertices = []
        for z in (-0.5, 0.5):
            for x, y in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
                dx, dy = x * size[0], y * size[1]
                vertices.append(
                    (
                        centre[0] + dx * cos(angle) - dy * sin(angle),
                        centre[1] + dx * sin(angle) + dy * cos(angle),
                        centre[2] + z * size[2],
                    )
                )
        for face in ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.face([vertices[i] for i in face], finish)

    def beam(self, a, b, radius, finish, sides=6):
        axis = unit(minus(b, a))
        u = unit(cross(axis, (1, 0, 0) if abs(axis[0]) < 0.8 else (0, 1, 0)))
        v = cross(axis, u)
        offsets = [
            tuple(radius * (u[j] * cos(tau * i / sides) + v[j] * sin(tau * i / sides)) for j in range(3))
            for i in range(sides)
        ]
        for i, d in enumerate(offsets):
            e = offsets[(i + 1) % sides]
            self.face(
                [tuple(p[j] + s[j] for j in range(3)) for p, s in ((a, d), (a, e), (b, e), (b, d))], finish
            )


def node(name, position=(0, 0, 0), rotation=(1, 0, 0, 0), tag="Untagged", layer=0):
    obj = mu.MuObject(name)
    obj.transform = mu.MuTransform()
    obj.transform.name = name
    obj.transform.localPosition = position
    obj.transform.localRotation = rotation
    obj.transform.localScale = (1, 1, 1)
    obj.tag_and_layer = mu.MuTagLayer()
    obj.tag_and_layer.tag, obj.tag_and_layer.layer = tag, layer
    return obj


def box_collider(root, name, centre, size, trigger=False, rotation=(1, 0, 0, 0), tag=None):
    obj = node(name, centre, rotation, tag=tag or (name if trigger else "Untagged"), layer=21 if trigger else 0)
    obj.collider = mu.MuColliderBox(True)
    obj.collider.isTrigger = int(trigger)
    obj.collider.center = (0, 0, 0)
    obj.collider.size = size
    root.children.append(obj)


def hull_collider(root, profile, segments=12, orient=None):
    hull = Surface()
    hull.lathe(profile, "steel", segments, orient=orient)
    obj = node("Hull")
    obj.collider = mu.MuColliderMesh(True)
    obj.collider.isTrigger = 0
    obj.collider.convex = 1
    obj.collider.mesh = hull.mesh
    root.children.append(obj)


def engine_layout(count, radius):
    if count == 1:
        return [(0, 0)]
    rings = {4: [(4, 0.56)], 5: [(1, 0), (4, 0.62)], 8: [(8, 0.67)], 30: [(6, 0.29), (24, 0.78)]}
    return [
        (radius * d * cos(tau * i / n + pi / 4), radius * d * sin(tau * i / n + pi / 4))
        for n, d in rings[count]
        for i in range(n)
    ]


def engines(surface, root, part, z, height, bell_radius, layout=None):
    # KSP engine exhaust follows Unity +Z, which is Blender +Y.
    exhaust_rotation = (math.sqrt(0.5), -math.sqrt(0.5), 0, 0)
    for x, y in layout or engine_layout(part.engines, part.radius):
        r = bell_radius
        if part.role == "cradle":
            # Close the inner throat behind the rim. The bell has no disk across its exit.
            surface.lathe(
                [
                    (z + 0.17, r * 0.44),
                    (z + 0.02, r * 0.85),
                    (z, r * 0.91),
                    (z, r),
                    (z + 0.06, r * 0.97),
                    (z + height * 0.76, r * 0.55),
                    (z + height, r * 0.44),
                ],
                "nozzle",
                20,
                (x, y),
                stripe=lambda band, _: "alloy" if band == 3 else "nozzle",
            )
            root.children.append(node("thrustTransform", (x, y, z), exhaust_rotation))
            continue
        surface.lathe(
            [
                (z, r),
                (z + height * 0.38, r * 0.67),
                (z + height * 0.74, r * 0.34),
                (z + height * 0.91, r * 0.48),
                (z + height, r * 0.42),
            ],
            "nozzle",
            16,
            (x, y),
        )
        for t in (0.12, 0.24, 0.36):
            rr = r * (1 - t * 0.82)
            surface.lathe(
                [(z + height * t, rr * 1.035), (z + height * (t + 0.025), rr * 1.015)], "copper", 16, (x, y)
            )
        # A recessed dark throat reads from below, including on the 30-nozzle stage.
        surface.lathe([(z - 0.001, r * 0.84), (z + 0.003, r * 0.83)], "ink", 16, (x, y))
        root.children.append(node("thrustTransform", (x, y, z), exhaust_rotation))


def booster_dimensions(p):
    lower = -p.height / 2
    bell_radius = p.radius * {1: 0.58, 4: 0.29, 5: 0.255, 8: 0.22, 30: 0.095}[p.engines]
    bell_height = min(p.height * 0.22, bell_radius * 2.3)
    return lower, bell_radius, bell_height, lower + bell_height * 0.88


def fin_skirt(p):
    lower, _, _, top = booster_dimensions(p)
    return [(lower + (0.23 if p.role == "saturn" else 0.075), p.radius * 0.895), (top, p.radius * 0.93)]


def n1_paint(stage, sector=None):
    if stage in ("famN1A", "famN1B") or (stage == "famN1V" and sector is not None and 4 <= sector < 12):
        return "gasket"
    return "white"


def split_shroud(root, p, lower, upper):
    service = p.role == "service"
    base = max(0.60, p.radius * 0.57) if service else p.radius * 0.97
    rim = p.radius * (0.76 if service else 0.93)
    wall = 0.022
    paint = n1_paint(p.id) if p.role == "n1" else "ivory"
    shell = Surface()
    shell.lathe(
        [(lower, base - wall), (lower, base), (upper, rim), (upper, rim - wall), (lower, base - wall)],
        paint,
        stripe=lambda band, i: (
            n1_paint(p.id, i) if p.role == "n1"
            else "ink" if p.role == "saturn" and band == 1 and i // 4 % 2 == 0
            else paint
        ),
        caps=False,
    )
    add_skin(root, shell, "interstage")


def control_fin(surface, root, grid):
    # The mounting saddle is fixed. Stock ModuleControlSurface pivots the blade
    # around the span axis, as on the AV-R8.
    surface.box((0, 0, 0), (0.068, 0.146, 0.17 if grid else 0.39), "steel")
    surface.beam((-0.10, 0, 0), (0.01, 0, 0), 0.053, "alloy")
    blade = Surface()
    if grid:
        for x in (-0.09, -0.60):
            blade.box((x, 0, 0), (0.037, 0.10, 0.26), "alloy")
        for z in (-0.113, 0.0, 0.113):
            blade.box((-0.345, 0, z), (0.51, 0.095, 0.029), "gasket")
        for x in (-0.22, -0.345, -0.47):
            blade.box((x, 0, 0), (0.016, 0.081, 0.21), "steel")
    else:
        outline = [(-0.075, 0.25), (-0.70, -0.04), (-0.70, -0.26), (-0.075, -0.32)]
        near = [(x, -0.030 if i in (0, 3) else -0.018, z) for i, (x, z) in enumerate(outline)]
        far = [(x, -y, z) for x, y, z in near]
        blade.face(near, "ink")
        blade.face(far[::-1], "ink")
        for i in range(len(outline)):
            j = (i + 1) % len(outline)
            blade.face((near[j], near[i], far[i], far[j]), "alloy")
        blade.box((-0.667, 0, -0.205), (0.069, 0.040, 0.097), "ivory")
    pivot = node("obj_ctrlSrf")
    add_skin(pivot, blade, "Exterior blade")
    root.children.append(pivot)
    box_collider(root, "Saddle", (0, 0, 0), (0.068, 0.146, 0.17 if grid else 0.39))
    box_collider(pivot, "Blade", (-0.33, 0, 0 if grid else -0.09), (0.50, 0.052, 0.26))


def booster(surface, root, p, motor=None):
    lo, bell_r, engine_h, skirt = booster_dimensions(p)
    hi, r, rt = p.height / 2, p.radius, p.top_radius
    soviet = p.role == "n1"
    paint = n1_paint(p.id) if soviet else "ivory"
    shoulder = hi - p.height * (0.16 if soviet else 0.24)
    profile = [
        (skirt, r * 0.93),
        (skirt + 0.09, r),
        (shoulder, r + (rt - r) * (0.82 if soviet else 0.12)),
        (hi, rt),
    ]

    if soviet:
        surface.lathe(profile, paint, stripe=lambda _, i: n1_paint(p.id, i))
    else:
        # Black roll marks cross the white tank barrels and break at the tank collars.
        barrel = sorted({*(z for z, _ in profile), skirt + 0.18 * (hi - skirt), skirt + 0.61 * (hi - skirt)})
        surface.lathe(
            [(z, profile_radius(profile, z)) for z in barrel],
            paint,
            stripe=lambda band, i: "ink" if band in (0, 1, 4) and i // 4 % 2 == 0 else paint,
        )
    for frac in (0.01, 0.045, 0.29, 0.72, 0.91, 0.97):
        z = skirt + (hi - skirt) * frac
        stations = [(height, profile_radius(profile, height) + 0.012) for height in (z, z + 0.023)]
        surface.lathe(stations, "steel" if soviet else "alloy")
    if soviet:
        truss_bottom, truss_top = hi - 0.34, hi - 0.035
        b = profile_radius(profile, truss_bottom) + 0.026
        t = profile_radius(profile, truss_top) + 0.026
        for i in range(20):
            a, next_a = tau * i / 20, tau * (i + 1) / 20
            surface.beam(point(b, a, truss_bottom), point(t, next_a, truss_top), 0.033, "ink")
            surface.beam(point(b, next_a, truss_bottom), point(t, a, truss_top), 0.028, "alloy")
        for i in range(4):
            a = i * pi / 2
            lower, upper = skirt + p.height * 0.1, shoulder - 0.05
            surface.beam(
                point(profile_radius(profile, lower), a, lower),
                point(profile_radius(profile, upper), a, upper),
                0.047,
                "alloy",
                sides=4,
            )
    else:
        for i in range(32):
            a = tau * i / 32
            surface.beam(
                point(r + 0.005, a, skirt + 0.10),
                point(r + (rt - r) * 0.015, a, skirt + 0.48),
                0.025,
                "steel",
            )
        for a in (0, pi):
            surface.beam(point(r, a, skirt + 0.28), point(profile[2][1], a, shoulder - 0.03), 0.055, "alloy")
        if p.id == "famSaturnIC" and not motor:
            for i in range(4):
                a = pi / 4 + i * pi / 2
                # Four low fins flank the outboard engine fairings.
                v = [
                    point(r * 0.96, a - 0.045, skirt + 0.10),
                    point(r * 1.20, a, lo + 0.29),
                    point(r * 0.97, a + 0.045, skirt + 0.10),
                    point(r * 0.95, a, skirt + 1.05),
                ]
                for face in ((0, 1, 3), (1, 2, 3), (2, 0, 3), (0, 2, 1)):
                    surface.face([v[j] for j in face], "alloy")
    engine_skin, engine_root = motor if motor else (surface, root)
    if motor:
        # The removable cluster carries its own mounting flange.
        if p.id in ("famSaturnIC", "famN1A"):
            def tail_paint(_, i):
                return paint if soviet else "ink" if i // 4 % 2 == 0 else paint

            engine_skin.lathe(
                fin_skirt(p), paint, stripe=tail_paint
            )
        else:
            engine_skin.lathe([(skirt - 0.08, r * 0.88), (skirt, r * 0.93)], "steel")
            split_shroud(engine_root, p, lo, skirt)
        joint(root, "engineMount", (0, 0, skirt), downward=True)
        joint(engine_root, "tankMount", (0, 0, skirt))
        engine_h = skirt - lo - 0.08
    # A split cluster uses the same axial gimbal orientation as stock engines.
    axial = (math.sqrt(0.5), -math.sqrt(0.5), 0, 0)
    mount = node("gimbal", (0, 0, lo + engine_h), axial if motor else (1, 0, 0, 0))
    engine_root.children.append(mount)
    engines(engine_skin, mount, p, lo, engine_h, bell_r)
    for jet in mount.children:
        x, y, z = jet.transform.localPosition
        offset = z - lo - engine_h
        jet.transform.localPosition = (x, -offset, y) if motor else (x, y, offset)
        if motor:
            jet.transform.localRotation = (1, 0, 0, 0)
    if motor:
        hull_collider(engine_root, [(lo, r * 0.88), (skirt, r * 0.93)])
        hull_collider(root, profile)
    else:
        hull_collider(root, [(lo, max(bell_r, r * 0.74)), (skirt, r), (hi, rt)])


def collar(surface, root, p):
    z = p.height / 2
    r = min(0.625, p.top_radius)
    surface.lathe([(z - 0.13, r), (z - 0.085, r * 1.04), (z - 0.05, r * 0.94), (z, r * 0.94)], "alloy", 24)
    surface.lathe([(z + 0.001, r * 0.73), (z + 0.004, r * 0.72)], "ink", 24)
    for i in range(3):
        a = tau * i / 3
        surface.box(point(r * 0.84, a, z - 0.008), (0.14, 0.075, 0.038), "gold", a)
    root.children.append(node("dockingNode", (0, 0, z), (math.sqrt(0.5), math.sqrt(0.5), 0, 0)))


def cabin_hatch(surface, root, hatch_radius, hatch_z):
    # Hatch normal faces the -Y side, matching the stock upright pod convention.
    y = -hatch_radius
    surface.box((0, y + 0.025, hatch_z), (0.61, 0.13, 0.73), "gasket")
    surface.box((0, y - 0.045, hatch_z), (0.54, 0.035, 0.65), "alloy")
    surface.box((0, y - 0.07, hatch_z + 0.18), (0.31, 0.025, 0.15), "glass")
    surface.box((0.18, y - 0.095, hatch_z - 0.07), (0.035, 0.045, 0.15), "warning")
    for i in range(4):
        z = hatch_z - 0.42 - i * 0.14
        surface.beam((-0.16, y - 0.055, z), (0.16, y - 0.055, z), 0.022, "alloy")
    box_collider(root, "Airlock", (0, y - 0.21, hatch_z + 0.02), (0.60, 0.40, 0.68), True)
    box_collider(root, "Ladder", (0, y - 0.22, hatch_z - 0.39), (0.52, 0.35, 1.16), True)


def apollo_hatch(surface, root, profile):
    # Follow the 40 actual hull facets, including the change in radius up the cone.
    def shell(arc, height, relief):
        radius = profile_radius(profile, height)
        angle = -pi / 2 + arc / radius
        facet = tau / 40
        radius *= cos(facet / 2) / cos(angle % facet - facet / 2)
        return point(radius + relief, angle, height)

    def panel(rows, relief, finish, centre=0):
        for (low, half_low), (high, half_high) in pairwise(rows):
            for i in range(12):
                a, b = (i - 6) / 6, (i - 5) / 6
                surface.face((shell(centre + a * half_low, low, relief),
                              shell(centre + b * half_low, low, relief),
                              shell(centre + b * half_high, high, relief),
                              shell(centre + a * half_high, high, relief)), finish)

    panel(((-0.32, .23), (-0.25, .31), (.23, .31), (.30, .23)), .008, "gasket")
    panel(((-0.30, .22), (-0.24, .29), (.22, .29), (.28, .22)), .015, "alloy")
    panel(((.05, .14), (.075, .16), (.19, .16), (.21, .14)), .020, "ink")
    panel(((.065, .125), (.085, .144), (.18, .144), (.195, .125)), .024, "glass")
    panel(((-.157, .020), (-.057, .020)), .030, "warning", centre=.19)
    for height in (-.37, -.46, -.55):
        a, b = (shell(x, height, .046) for x in (-.145, .145))
        surface.beam(a, b, .012, "alloy")
        for arc, end in ((-.145, a), (.145, b)):
            surface.beam(shell(arc, height, 0), end, .014, "steel")

    slope = (profile_radius(profile, .1) - profile_radius(profile, -.1)) / .2
    angle = math.atan(slope)
    orientation = (cos(angle / 2), sin(angle / 2), 0, 0)
    for name, height, stand_off, size in (("Airlock", .005, .18, (.58, .36, .67)),
                                         ("Ladder", -.40, .15, (.43, .30, .51))):
        _, y, z = shell(0, height, 0)
        centre = (0, y - stand_off * cos(angle), z - stand_off * sin(angle))
        box_collider(root, name, centre, size, True, rotation=orientation)


def rcs_fittings(surface, root, height, hatch_radius):
    # The stock RCS module uses the local up vector (+Z in Blender).
    for i in range(4):
        a = i * pi / 2 + pi / 4
        pos = point(hatch_radius * 0.89, a, -height * 0.16)
        surface.box(pos, (0.19, 0.14, 0.17), "steel", a)
        for direction in ((cos(a), sin(a), 0), (0, 0, 1), (0, 0, -1)):
            x, y, z = direction
            rot = (
                (0, 1, 0, 0)
                if z == -1
                else (math.sqrt((1 + z) / 2), -y / math.sqrt(2 * (1 + z)), x / math.sqrt(2 * (1 + z)), 0)
            )
            root.children.append(node("rcsJet", pos, rot))


def cabin(surface, root, p):
    r, lo, hi = p.radius, -p.height / 2, p.height / 2
    if p.role == "cm":
        profile = [
            (lo, r * 0.87),
            (lo + 0.10, r),
            (lo + 0.22, r * 0.995),
            (hi - 0.16, p.top_radius),
            (hi, p.top_radius * 0.88),
        ]
        surface.lathe(
            profile,
            "alloy",
            40,
            stripe=lambda band, i: "ivory" if band == 2 and i % 10 in (4, 5) else "alloy",
        )
        surface.lathe([(lo - 0.002, r * 0.86), (lo + 0.085, r * 0.99)], "nozzle")
        surface.lathe([(lo + 0.083, r * 0.992), (lo + 0.127, r * 1.008)], "copper", 40)
        for a in (pi * 0.12, pi * 0.88):
            for width, bottom, top, border, paint in (
                (0.23, 0.12, 0.40, 0.026, "ink"),
                (0.17, 0.16, 0.36, 0.038, "glass"),
            ):
                surface.face(
                    [
                        point(profile_radius(profile, z) + border, a + side * width * taper, z)
                        for z, side, taper in (
                            (bottom, -1, 1),
                            (bottom, 1, 1),
                            (top, 1, 0.73),
                            (top, -1, 0.73),
                        )
                    ],
                    paint,
                )
        hatch_r = r * 0.79
    elif p.role in ("lok", "lk"):
        paint = "sage" if p.role == "lk" else "olive"
        profile = [
            (lo, r * 0.53),
            (lo + 0.16, r * 0.78),
            (lo + p.height * 0.39, r),
            (lo + p.height * 0.65, r * 0.88),
            (lo + p.height * 0.79, r * 0.64),
            (hi - 0.14, p.top_radius),
            (hi, p.top_radius * 0.9),
        ]
        surface.lathe(profile, paint, 28)
        surface.lathe([(lo + 0.12, r * 0.76), (lo + 0.19, r * 0.79)], "steel")
        if p.role == "lok":
            # A separate rounded orbital compartment sits above the olive return shell.
            surface.lathe(
                [
                    (hi - 0.61, r * 0.70),
                    (hi - 0.50, r * 0.766),
                    (hi - 0.36, r * 0.73),
                    (hi - 0.20, r * 0.60),
                    (hi - 0.11, p.top_radius * 1.03),
                ],
                "sage",
            )
            surface.lathe([(hi - 0.52, r * 0.773), (hi - 0.48, r * 0.773)], "steel", 32)
        else:
            surface.lathe([(0.24, r * 0.90), (0.32, r * 0.83)], "alloy", 28)
            for side in (-1, 1):
                surface.box((0.42 * side, 0.36, -0.34), (0.19, 0.28, 0.22), "foil", side * 0.35)
        for a in (0.2, pi - 0.2):
            surface.box(point(r * 0.9, a, -0.04), (0.12, 0.32, 0.24), "ink", a)
            surface.box(point(r * 0.96, a, -0.04), (0.06, 0.24, 0.17), "glass", a)
        hatch_r = r * 0.96
    elif p.role == "lsam":
        profile = [
            (lo, r * 0.82),
            (lo + 0.15, r * 0.98),
            (hi - 0.35, r),
            (hi - 0.12, r * 0.76),
            (hi, p.top_radius),
        ]
        surface.lathe(profile, "ivory", 8, angle=pi / 8)
        # A projecting flight deck gives the ferry its broad, forward-facing windshield.
        surface.box((0, 0.73, -0.30), (1.79, 0.83, 0.64), "alloy")
        surface.box((0, 1.13, -0.34), (1.67, 0.13, 0.17), "steel")
        surface.box((0, 1.20, -0.34), (1.56, 0.028, 0.055), "gold")
        windscreen = (
            ((-0.91, 1.16, 0.03), (0.91, 1.16, 0.03), (0.76, 1.01, 0.61), (-0.76, 1.01, 0.61)),
            ((-0.76, 1.01, 0.61), (0.76, 1.01, 0.61), (0.69, 0.64, 0.66), (-0.69, 0.64, 0.66)),
        )
        for panel in windscreen:
            surface.face(panel[::-1], "alloy")
        for side in (-1, 1):
            surface.face(
                (
                    (side * 0.91, 1.16, 0.03),
                    (side * 0.76, 1.01, 0.61),
                    (side * 0.69, 0.64, 0.66),
                    (side * 0.88, 0.64, 0.03),
                )[::-side],
                "steel",
            )
        for side in (-1, 1):

            def pane(x, w, h, depth, paint):
                v = [
                    (x - w, 1.16 + depth, 0.08),
                    (x + w, 1.16 + depth, 0.08),
                    (x + w * 0.86, 1.02 + depth, 0.08 + h),
                    (x - w * 0.86, 1.02 + depth, 0.08 + h),
                ]
                surface.face(v[::-1], paint)

            pane(side * 0.404, 0.408, 0.49, 0.025, "ink")
            pane(side * 0.404, 0.354, 0.43, 0.041, "glass")
            surface.box((side * 1.06, -0.1, hi - 0.13), (0.57, 1.22, 0.075), "solar")
            surface.box((side * 0.99, 0.02, -0.28), (0.24, 0.76, 0.40), "white")
            surface.box((side * 1.13, 0.03, -0.25), (0.035, 0.35, 0.08), "red")
        hatch_r = r * 0.94
    else:
        profile = [
            (lo, r * 0.69),
            (lo + 0.18, r * 0.90),
            (0.04, r),
            (hi - 0.26, r * 0.81),
            (hi - 0.13, p.top_radius),
            (hi, p.top_radius),
        ]
        surface.lathe(profile, "alloy", 8, angle=pi / 8)
        # Slanted twin forward panes share a broad brow above the ascent deck.
        surface.box((0, 0.71, 0.16), (1.28, 0.29, 0.35), "steel")
        for side in (-1, 1):
            for inner, outer, bottom, top, depth, paint in (
                (0.08, 0.67, 0.04, 0.50, 0, "gasket"),
                (0.13, 0.58, 0.110, 0.415, 0.019, "glass"),
            ):
                vertices = (
                    (side * inner, 0.94 + depth, bottom),
                    (side * outer, 0.89 + depth, bottom + 0.044),
                    (side * inner * 2.05, 0.87 + depth, top),
                )
                surface.face(vertices[::-side], paint)
            surface.beam((side * 0.08, 0.93, 0.048), (side * 0.68, 0.88, 0.09), 0.025, "alloy")
        surface.box((r * 0.9, 0, -0.13), (0.31, 0.68, 0.48), "ivory")
        surface.box((-r * 0.87, 0, -0.13), (0.26, 0.54, 0.43), "gold")
        surface.box((-r * 0.99, 0, -0.10), (0.070, 0.40, 0.33), "gasket")
        hatch_r = r * 0.92
    hull_collider(root, profile)
    if p.role == "cm":
        apollo_hatch(surface, root, profile)
    else:
        cabin_hatch(surface, root, hatch_r, 0.02)
    collar(surface, root, p)
    rcs_fittings(surface, root, p.height, hatch_r)
    if p.thrust:
        engines(surface, root, p, lo, 0.20, r * 0.27)


def joint(root, name, position, downward=False):
    root.children.append(node(name, position, (0, 1, 0, 0) if downward else (1, 0, 0, 0)))


def landing_frame(surface, root, p, fuel=None, motor=None):
    r, lo, hi = p.radius, -p.height / 2, p.height / 2
    paint = {"lkframe": "olive", "lmframe": "gold", "cradle": "ivory", "lsamframe": "steel"}[p.role]
    profile = [(lo + 0.24, r * 0.64), (lo + 0.36, r * 0.89), (hi - 0.18, r), (hi, r * 0.87)]
    if fuel:
        fuel_skin, fuel_root = fuel
        motor_skin, motor_root = motor
        frame_base, motor_top = hi - 0.28, lo + 0.38
        frame_profile = [(frame_base, r * 0.873), (hi - 0.18, r), (hi, r * 0.87)]
        fuel_profile = [(motor_top, r * 0.68), (motor_top + 0.05, r * 0.87), (frame_base, r * 0.873)]
        surface.lathe(frame_profile, "steel", 8, angle=pi / 8)
        hull_collider(root, frame_profile, 8)
        fuel_skin.lathe(fuel_profile, paint, 8, angle=pi / 8)
        hull_collider(fuel_root, fuel_profile, 8)
        joint(root, "fuelMount", (0, 0, frame_base), downward=True)
        joint(fuel_root, "frameMount", (0, 0, frame_base))
        joint(fuel_root, "engineMount", (0, 0, motor_top), downward=True)
        joint(motor_root, "fuelMount", (0, 0, motor_top))
        motor_skin.lathe([(motor_top - 0.04, r * 0.66), (motor_top, r * 0.68)], "alloy", 8)
        hull_collider(motor_root, [(lo + 0.11, 0.74 * r), (motor_top, 0.68 * r)])
    else:
        fuel_skin, motor_skin, motor_root = surface, surface, root
        surface.lathe(profile, paint, 8, angle=pi / 8)
        hull_collider(root, profile, 8)
    for i in range(4):
        a = pi / 4 + pi * i / 2
        foot_r = r * 1.48
        foot = point(foot_r, a, lo + 0.05)
        surface.beam(point(r * 0.83, a, hi - 0.04), foot, 0.055, "alloy")
        for off in (-0.50, 0.50):
            surface.beam(
                point(r * 0.95, a + off, hi - 0.24), point(foot_r - 0.08, a, lo + 0.14), 0.028, "copper"
            )
        surface.lathe([(lo, 0.19), (lo + 0.045, 0.20), (lo + 0.09, 0.10)], "alloy", 12, foot[:2])
        box_collider(root, "Foot" + str(i), foot, (0.27, 0.27, 0.09))
        sector = a + pi / 4
        if p.role == "lsamframe":
            xy = point(r * 0.87, sector, 0)[:2]
            fuel_skin.lathe(
                [(lo + 0.24, 0.11), (lo + 0.36, 0.25), (hi - 0.26, 0.25), (hi - 0.10, 0.10)], "ivory", 14, xy
            )
            fuel_skin.lathe([(lo + 0.53, 0.256), (lo + 0.61, 0.256)], "steel", 14, xy)
            pipe_low, pipe_high = (hi - 0.31, hi - 0.20) if fuel else (hi - 0.21, hi - 0.08)
            fuel_skin.beam(point(r * 0.60, sector, pipe_low), (*xy, pipe_high), 0.044, "copper")
        elif p.role == "lmframe":
            center, width, height = (0.08, 0.64, 0.30) if fuel else (0.12, 0.76, 0.44)
            fuel_skin.box(point(r * 0.91, sector, center), (0.16, width, height), "foil", sector)
            fuel_skin.box(point(r * 0.99, sector, center + 0.01), (0.07, 0.44, height - 0.11), "gold", sector)
        else:
            surface.beam(
                point(r * 0.79, a, hi - 0.04), point(r * 1.32, a, lo + 0.20), 0.076, "gasket", sides=6
            )
    engines(
        motor_skin, motor_root, p, lo + 0.11, 0.23 if motor else 0.30, r * (0.19 if p.engines == 4 else 0.32)
    )


def jamestown(surface, root, p):
    def horizontal(x, y, z):
        return z, x, y * 0.88 + HAB_PORT_Y

    profile = [(-2.18, 0.63), (-1.91, 0.94), (1.91, 0.94), (2.18, 0.63)]
    surface.lathe(profile, "ivory", 16, orient=horizontal)
    hull_collider(root, profile, 12, horizontal)
    for station in (-1.88, -0.07, 0.98, 1.87):
        surface.lathe([(station - 0.045, 0.943), (station + 0.045, 0.943)], "steel", 16, orient=horizontal)
    for side in (-1, 1):
        for x in (-1.52, 0.58, 1.38):
            surface.box((x, side * 0.893, 0.14), (0.49, 0.12, 0.37), "gasket")
            surface.box((x, side * 0.96, 0.14), (0.36, 0.045, 0.24), "glass")
        surface.box((1.32, side * 0.88, -0.48), (0.57, 0.13, 0.23), "alloy")

    # Keep the original centre stack planes and its roof port for existing craft.
    surface.box((0, 0, -1.13), (2.22, 1.42, p.height - 2.26), "alloy")
    surface.box((0, 0, 0.81), (0.96, 0.84, 0.38), "alloy")
    surface.lathe([(0.96, 0.48), (1.23, 0.48)], "steel", 16)
    collar(surface, root, p)
    box_collider(root, "Keel", (0, 0, -1.12), (2.22, 1.43, 0.45))
    for mount, size in ((HAB_SOLAR, (1.00, 0.92, 0.15)), (HAB_ANTENNA, (0.43, 0.42, 0.15))):
        x, z, y = mount
        # A narrower support keys the flat mounting plate into the curved pressure shell.
        surface.box((x, y, z - 0.20), (size[0] * 0.66, size[1] * 0.66, 0.24), "steel")
        surface.box((x, y, z - size[2] / 2), size, "alloy")
    x, z, y = HAB_LADDER
    surface.box((x, y - 0.05, z), (0.42, 0.10, 0.65), "alloy")
    # Fixed stock-compatible electrical output also keeps old landed habitats operational.
    surface.box((-0.97, -0.23, 0.77), (0.91, 0.55, 0.075), "solar")

    # The wide side hatch opens above the cradle stairs, away from the docking axes.
    x = -0.80
    surface.box((x, -1.01, -0.34), (0.86, 0.39, 1.06), "steel")
    surface.box((x, -1.223, -0.35), (0.68, 0.065, 0.81), "ivory")
    surface.box((x, -1.26, -0.17), (0.33, 0.025, 0.22), "glass")
    surface.box((x + 0.24, -1.265, -0.48), (0.045, 0.036, 0.17), "warning")
    box_collider(root, "Airlock Shell", (x, -1.02, -0.34), (0.85, 0.39, 1.04))
    box_collider(root, "Airlock", (x, -1.39, -0.38), (0.67, 0.43, 0.77), True)
    box_collider(root, "Ladder", (x, -1.48, -0.80), (0.63, 0.52, 1.42), True)
    rcs_fittings(surface, root, p.height, 1.05)

    for name, sign in HAB_PORTS:

        def end_port(x, y, z, direction=sign):
            return direction * z, direction * x, y + HAB_PORT_Y

        surface.lathe(
            [(2.09, 0.64), (2.22, 0.66), (HAB_PORT_X, 0.59), (HAB_PORT_X, 0.50), (HAB_PORT_X - 0.082, 0.50)],
            "alloy",
            24,
            orient=end_port,
            stripe=lambda band, sector: "warning" if band == 2 and sector % 8 == 0 else "alloy",
        )
        surface.lathe([(HAB_PORT_X - 0.079, 0.493), (HAB_PORT_X - 0.065, 0.48)], "steel", 24, orient=end_port)
        box_collider(root, name + " Collaring", (sign * 2.19, 0, HAB_PORT_Y), (0.24, 1.01, 1.01))
        half_turn = -sign * pi / 4
        root.children.append(
            node(name + "Dock", (sign * HAB_PORT_X, 0, HAB_PORT_Y), (cos(half_turn), 0, 0, sin(half_turn)))
        )


def jamestown_hull_review(surface, root, p, arrays, radio_mount):
    """Build the circular pressure room and the straight alcoves of the Phase 1 plan."""

    def plan(x, y, z):
        return max(-1.66, min(1.66, x)), max(-1.505, min(1.57, y)), z

    profile = [
        (-1.35, 1.36), (-1.26, 1.65), (-1.09, 1.80), (-0.97, 1.825),
        (0.34, 1.825), (0.49, 1.77), (0.57, 1.67),
    ]
    surface.lathe(profile, "ivory", 32, orient=plan,
                  stripe=lambda band, i: "steel" if band < 2 else "alloy" if i % 8 in (2, 6) else "ivory")
    hull_collider(root, profile, 32, plan)
    for z in (-0.88, 0.29):
        surface.lathe([(z - 0.024, 1.848), (z + 0.024, 1.848)], "steel", 32, orient=plan, caps=False)
    for i in range(8):
        angle = pi * (2 * i + 1) / 8
        surface.box(point(1.825, angle, -0.29), (0.115, 0.055, 1.12), "alloy", angle - pi / 2)
    for angle in (-pi / 4, -3 * pi / 4, pi / 4, 3 * pi / 4):
        surface.box(point(1.802, angle, -0.13), (0.44, 0.13, 0.33), "gasket", angle - pi / 2)
        surface.box(point(1.873, angle, -0.13), (0.345, 0.031, 0.23), "glass", angle - pi / 2)

    seat = (0, 0, ROOF_DOCK_SEAT - 0.035)
    surface.lathe([(ROOF_DOCK_SEAT - 0.07, 0.645), (ROOF_DOCK_SEAT, 0.645)], "alloy", 24)
    box_collider(root, "Roof Dock Seat", seat, (0.88, 0.88, 0.07))
    for i in range(3):
        angle = tau * i / 3
        surface.beam(point(0.87, angle, 0.56), point(0.53, angle, 0.83), 0.044, "alloy")
    joint(root, "roofMount", (0, 0, ROOF_DOCK_SEAT))

    x, y, z = AIRLOCK_SIDE
    surface.box((x, y + 0.032, z), (1.31, 0.064, 1.30), "steel")
    surface.box((x, y - 0.002, z + 0.648), (0.17, 0.004, 0.048), "gold")
    y = STATION_SEATS["rear"][1]
    surface.box((0, y - 0.15, HAB_PORT_Y), (1.22, 0.30, 1.21), "ivory")
    surface.box((0, y - 0.034, HAB_PORT_Y), (1.31, 0.068, 1.29), "alloy")
    box_collider(root, "Rear Alcove", (0, y - 0.14, HAB_PORT_Y), (1.21, 0.28, 1.21))
    # Keep an EVA hatch on the service side when the airlock is away from the cabin.
    hatch_x, hatch_y = -0.91, 1.54
    surface.box((hatch_x, hatch_y, -0.18), (0.57, 0.09, 0.61), "steel")
    surface.box((hatch_x, hatch_y + 0.05, -0.18), (0.46, 0.025, 0.53), "ivory")
    surface.box((hatch_x, hatch_y + 0.065, -0.025), (0.24, 0.025, 0.13), "glass")
    # KSP spawns the Kerbal along the hatch's local back axis with local up as head-up.
    box_collider(root, "Airlock", (hatch_x, hatch_y + 0.25, -0.19), (0.55, 0.42, 0.62), True, (0, 0, 0, 1))
    box_collider(root, "Ladder", (hatch_x, hatch_y + 0.26, -0.60), (0.55, 0.36, 0.85), True, (0, 0, 0, 1))
    # Provide an independent roof exit while the four side stations carry modules.
    hx, hy = 0.85, -0.38
    surface.box((hx, hy, 0.592), (0.62, 0.70, 0.055), "steel")
    surface.box((hx, hy, 0.63), (0.53, 0.61, 0.032), "ivory")
    surface.box((hx, hy, 0.653), (0.22, 0.07, 0.025), "gold")
    h = sqrt(0.5)
    box_collider(root, "Roof escape hatch", (hx, hy, 0.84), (0.54, 0.38, 0.61),
                 True, (h, -h, 0, 0), "Airlock")
    rcs_fittings(surface, root, p.height, 1.79)

    for port, sign in HAB_PORTS:
        surface.box((sign * 1.80, 0, HAB_PORT_Y), (0.38, 1.21, 1.26), "ivory")
        plate = (sign * (END_DOCK_SEAT - SERVO_DEPTH - 0.055), 0, HAB_PORT_Y)
        surface.box(plate, (0.11, 1.30, 1.29), "alloy")
        box_collider(root, port + " Alcove", (sign * 1.763, 0, HAB_PORT_Y), (0.23, 1.20, 1.20))
        for level in (-0.44, 0.44):
            surface.box((sign * 1.81, 0, HAB_PORT_Y + level), (0.42, 1.23, 0.052), "steel")

    # Open rolled-metal sleeves surround the servo and port barrel. Leave the
    # stock magnetic mating face proud of the lip and the rotating collar free.
    for side, (sx, sy, dx, dy) in STATION_SEATS.items():
        def sleeve(u, v, h):
            return sx + dx * h - dy * u, sy + dy * h + dx * u, HAB_PORT_Y + v

        lip = SERVO_DEPTH + DOCK_DEPTH - 0.072
        surface.lathe([(-0.08, 0.708), (0.01, 0.72), (lip - 0.04, 0.70),
                       (lip, 0.682), (lip, 0.65), (-0.08, 0.65)], "alloy", 32, orient=sleeve,
                      caps=False, stripe=lambda band, i: "steel" if band in (0, 3, 4) else "ivory")
        for h in (0.065, 0.16, lip - 0.08):
            surface.lathe([(h - 0.012, 0.718), (h, 0.733), (h + 0.014, 0.718)],
                          "steel", 32, orient=sleeve, caps=False)

    for x, y, z in arrays:
        side = 1 if y > 0 else -1
        surface.beam((x, 0.48 * side, 0.61), (x, y, z - 0.016), 0.064, "steel", sides=4)
        surface.box((x, y, z - 0.045), (0.36, 0.42, 0.09), "alloy")

    # An outboard service rack supports the stock folding relay.
    x, y, z = radio_mount
    surface.box((x, y, z - 0.045), (0.64, 0.48, 0.09), "alloy")
    for side in (-1, 1):
        u = x + side * 0.25
        surface.beam((u, 1.24, 0.46), (u, y + 0.21, z - 0.055), 0.043, "steel")
        surface.beam((u, 1.35, -0.29), (u, y + 0.18, z - 0.055), 0.046, "steel")
        surface.beam((u, y + 0.20, z - 0.055), (u, y + 0.20, z - 0.52), 0.040, "steel")
    surface.beam((x - 0.25, y + 0.20, z - 0.52), (x + 0.25, y + 0.20, z - 0.055), 0.035, "steel")
    surface.box((-0.87, 1.518, -0.57), (0.29, 0.09, 0.50), "alloy")


def jamestown_airlock(surface, root):
    lower, upper = -AIRLOCK_LENGTH / 2, AIRLOCK_LENGTH / 2
    profile = [(lower, 0.636), (lower + 0.09, 0.68), (lower + 0.21, 0.70),
               (upper - 0.12, 0.70), (upper, 0.64), (upper + 0.012, 0.595)]
    surface.lathe(profile, "steel", 32, stripe=lambda band, i: "ink" if band == 2 and i % 8 < 4 else "alloy")
    hull_collider(root, profile, 24)
    for z in (lower + 0.20, lower + 0.33, upper - 0.30, upper - 0.11):
        surface.lathe([(z - 0.027, 0.715), (z + 0.027, 0.715)], "alloy", 32, caps=False)
    for i in range(8):
        angle = i * tau / 8
        surface.beam(point(0.704, angle, lower + 0.21), point(0.704, angle, upper - 0.105), 0.026, "ink")
    # Rounded pressure door, gasket and a blue inspection window at Kerbal eye height.
    def door(width, height, depth, finish):
        x, y, corner = width / 2, height / 2, 0.12
        rim = [(-x + corner, -y), (x - corner, -y), (x, -y + corner), (x, y - corner),
               (x - corner, y), (-x + corner, y), (-x, y - corner), (-x, -y + corner)]
        face = [(u, v - 0.040, upper + depth) for u, v in rim]
        for i in range(1, len(face) - 1):
            surface.face((face[0], face[i], face[i + 1]), finish)
    door(0.85, 1.13, 0.020, "gasket")
    door(0.78, 1.065, 0.031, "ivory")
    surface.box((0, 0.17, upper + 0.038), (0.32, 0.20, 0.018), "steel")
    surface.box((0, 0.17, upper + 0.051), (0.245, 0.135, 0.012), "glass")
    for y in (-0.31, 0.21):
        surface.box((-0.381, y, upper + 0.041), (0.085, 0.15, 0.035), "alloy")
    for y in (-0.23, -0.12):
        surface.box((0.28, y, upper + 0.049), (0.042, 0.035, 0.056), "steel")
    surface.box((0.28, -0.175, upper + 0.078), (0.035, 0.15, 0.021), "gold")
    surface.box((0, 0.657, lower + 0.048), (0.17, 0.038, 0.045), "gold")
    # Each jamb carries a small downlight outside the gasket and the ladder grip.
    jamestown_lamps(surface, root, [
        ((side * 0.490, 0.205, upper + 0.005), (0, 0, 1), (-side * 0.22, -1, 0.65))
        for side in (-1, 1)
    ], radius=0.072, distance=8, spread=94, intensity=1.25)
    box_collider(root, "Airlock", (0, -0.04, upper + 0.25), (0.62, 0.42, 0.92), True, (sqrt(0.5), -sqrt(0.5), 0, 0))
    box_collider(root, "Ladder", (0, -0.39, upper + 0.19), (0.57, 0.42, 0.80), True, (sqrt(0.5), -sqrt(0.5), 0, 0))
    joint(root, "airlockDockPlane", (0, 0, lower), downward=True)
    rcs_fittings(surface, root, AIRLOCK_LENGTH, 0.66)
    review_stairs(root)


def jamestown_pod(surface, root, p):
    lo, hi = -p.height / 2, p.height / 2
    profile = [(lo, 0.23), (lo + 0.08, 0.26), (lo + 0.16, 0.27),
               (hi - 0.14, 0.27), (hi - 0.055, 0.25), (hi, 0.195)]
    surface.lathe(profile, "alloy", 24, stripe=lambda band, i: "steel" if band == 2 and i % 12 < 3 else "alloy")
    hull_collider(root, profile, 20)
    for z in (lo + 0.18, hi - 0.16):
        surface.lathe([(z - 0.024, 0.278), (z + 0.024, 0.278)], "ink", 24, caps=False)
    joint(root, "frameMount", (0, 0, hi))
    joint(root, "engineMount", (0, 0, lo), downward=True)


def animate_transform(clip, path, property_name, components, poses, duration):
    interval = duration / (len(poses) - 1)
    for component, values in zip(components, zip(*poses)):
        curve = mu.MuCurve()
        curve.path = path
        curve.property = f"m_Local{property_name}.{component}"
        curve.type, curve.wrapMode = 0, (8, 8)
        curve.keys = []
        for index, value in enumerate(values):
            slope = (values[index + 1] - values[index - 1]) / (2 * interval) if 0 < index < len(values) - 1 else 0
            key = mu.MuKey()
            key.time, key.value, key.tangent, key.tangentMode = index * interval, value, (slope, slope), 0
            curve.keys.append(key)
        clip.curves.append(curve)


def review_stairs(root):
    # On the detachable barrel, +Y is up after side docking and +Z points out of the door.
    y, z = -0.755, 0.760
    sill = Surface()
    sill.box((0, y, 0.595), (0.77, 0.05, 0.34), "steel")
    box_collider(root, "Hatch sill contact", (0, y, 0.595), (0.77, 0.05, 0.34))
    for x in (-0.35, 0.35):
        sill.beam((x, -0.54, 0.38), (x, y, z), 0.044, "alloy")
        sill.beam((x - 0.035, y, z), (x + 0.035, y, z), 0.053, "gold")
    add_skin(root, sill, "Exterior hatch sill")
    angle = math.radians(STAIR_FOLD)
    hinge = node(STAIR_GROUP, (0, y, z), (cos(angle / 2), sin(angle / 2), 0, 0))
    root.children.append(hinge)
    rise, run = 0.223, 0.226
    for i in range(1, STAIR_TREAD_COUNT + 1):
        step = node(f"stairTread{i}", (0, -i * rise, i * run - 0.095))
        hinge.children.append(step)
        skin = Surface()
        size = (0.65, 0.045, 0.224)
        skin.box((0, 0, 0), size, "steel")
        skin.box((0, 0.024, 0.090), (0.56, 0.004, 0.029), "warning")
        add_skin(step, skin, "Exterior tread")
        box_collider(step, "Tread Contact", (0, 0, 0), size)
    sides = Surface()
    # A short ground shoe completes the last riser. The main footpads carry the base.
    toe_y, toe_z = -REVIEW_DOCK_HEIGHT - y + 0.017, STAIR_TREAD_COUNT * run + 0.090
    for x in (-0.335, 0.335):
        sides.beam((x, 0, 0), (x, toe_y + 0.018, toe_z), 0.030, "alloy", sides=6)
        sides.beam((x, -0.12, 0.058), (x, toe_y + 0.12, toe_z - 0.10), 0.017, "gold", sides=6)
    shoe = (0.72, 0.030, 0.145)
    sides.box((0, toe_y, toe_z), shoe, "gasket")
    add_skin(hinge, sides, "Exterior stair stringers and toe")
    box_collider(hinge, "Ground shoe", (0, toe_y, toe_z), shoe)
    clip = mu.MuClip()
    clip.name, clip.lbCenter, clip.lbSize, clip.wrapMode = STAIR_CLIP, (0, 0, 0), (4, 4, 4), 0
    fractions = [i / 24 for i in range(25)]
    angles = [angle * (1 - f * f * (3 - 2 * f)) / 2 for f in fractions]
    animate_transform(clip, STAIR_GROUP, "Rotation", "xyzw",
                      [(-sin(a), 0, 0, cos(a)) for a in angles], STAIR_DURATION)
    root.animation = mu.MuAnimation()
    root.animation.clips, root.animation.clip, root.animation.autoPlay = [clip], "", 0


def jamestown_foot(surface, root):
    profile = [(-PAD_DEPTH, 0.18), (-PAD_DEPTH + 0.02, 0.214), (-0.048, 0.214),
               (-0.025, 0.14), (0, 0.092)]
    surface.lathe(profile, "alloy", 16, stripe=lambda band, i: "gasket" if band == 0 else "alloy")
    hull_collider(root, profile, 16)
    joint(root, "pistonSeat", (0, 0, 0))


def jamestown_lamps(surface, root, mounts, radius, distance, spread, intensity):
    """Bolt flanged, hooded LED heads to the given planes in Blender coordinates."""
    lenses = Surface()
    for index, (mount, normal, direction) in enumerate(mounts, 1):
        axis = unit(direction)
        pivot = tuple(p + radius * 0.65 * n for p, n in zip(mount, normal))

        def fitting(base, forward):
            tangent = unit(cross((0, 1, 0), forward))
            up = cross(forward, tangent)
            return lambda x, y, z: tuple(p + x * t + y * u + z * n
                                         for p, t, u, n in zip(base, tangent, up, forward))

        foot = fitting(mount, normal)
        face = fitting(pivot, axis)
        surface.lathe([(-0.012, radius), (0.014, radius), (0.026, 0.64 * radius)],
                      "steel", 12, orient=foot)
        surface.lathe([(-0.027, radius * 0.53), (0.002, radius * 0.83), (0.035, radius * 0.83),
                       (0.039, radius * 0.66), (0.031, radius * 0.63)],
                      "alloy", 12, orient=face, caps=False)
        lenses.lathe([(0.030, radius * 0.64), (0.034, radius * 0.62)], "white", 12, orient=face)
        # Unity spots emit along +Z, which is +Y in the editable Blender coordinate system.
        q = unit((1 + axis[1], axis[2], 0, -axis[0]))
        housing = node("Lamp " + str(index))
        source = node("jamestownFlood", face(0, 0, 0.043), q)
        source.light = mu.MuLight()
        source.light.type, source.light.color = 0, (1, 1, 1, 1)
        source.light.range, source.light.spotAngle, source.light.intensity = distance, spread, intensity
        source.light.cullingMask = 0x828001  # Stock KSP flight spotlight layers.
        housing.children.append(source)
        root.children.append(housing)
    add_skin(root, lenses, "Exterior lamp lenses")
    root.children[-1].renderer.materials = [1]


def jamestown_cradle(surface, root, p, pod_mounts=()):
    lo, hi = -p.height / 2, p.height / 2
    platform_depth = 0.12 if pod_mounts else 0.36
    platform_center = (0, 0, hi - platform_depth / 2)
    platform_size = (2.77, 1.66, platform_depth)
    surface.box(platform_center, platform_size, "steel")
    box_collider(root, "Engine Platform", platform_center, platform_size)
    if pod_mounts:
        lo = REVIEW_CARRIER_SEAT
        skirt = [(0.13, 1.34), (0.23, 1.57), (0.52, 1.62), (0.70, 1.36)]
        surface.lathe(skirt, "steel", 32, stripe=lambda band, i: "alloy" if i % 8 in (1, 6) else "steel")
        hull_collider(root, skirt, 24)
        # Aim outside the ring and away from the Sparks, jacks and docking lanes.
        jamestown_lamps(surface, root, [
            ((side * 1.594, 0, 0.42), (side, 0, 0), (side * 0.80, 0, -1))
            for side in (-1, 1)
        ], radius=0.106, distance=25, spread=86, intensity=1.8)
        surface.box((0, 0, 0.48), (1.82, 1.02, 0.31), "gasket")
        for side in (-1, 1):
            surface.beam((-0.89, 0.45 * side, 0.52), (0.89, -0.45 * side, 0.34), 0.048, "alloy")
            for end in (-1, 1):
                surface.beam(
                    (end * 0.56, 0.36 * side, 0.33), (end * 0.21, side * 0.19, lo + 0.10), 0.052, "steel"
                )
        surface.lathe([(lo, 0.32), (lo + 0.12, 0.34)], "alloy", 12)
        hull_collider(root, [(lo, 0.32), (lo + 0.12, 0.34), (0.34, 0.38)])
    else:
        surface.lathe([(lo + 0.43, 0.71), (lo + 0.52, 0.82), (hi - 0.18, 0.82)], "gasket", 16)
    foot_x, foot_y = (1.62, 1.56) if pod_mounts else (1.75, 1.48)
    corners = [(x, y) for x in (-foot_x, foot_x) for y in (-foot_y, foot_y)]
    for index, (x, y) in enumerate(corners):
        sign = 1 if x > 0 else -1
        front = 1 if y > 0 else -1
        foot = (x, y, lo + 0.05)
        if pod_mounts:
            jx, jy, jz = JACKS[index]
            surface.box((jx, jy, jz + 0.042), (0.31, 0.31, 0.084), "gold")
            box_collider(root, f"Jack seat {index + 1}", (jx, jy, jz + 0.042), (0.31, 0.31, 0.084))
            # Rise inboard of the piston, then cantilever over its fixed end.
            # The sliding rod and the stock cylinder wall stay clear at every stroke.
            knuckle_y = jy - front * 0.34
            for offset in (-0.105, 0.105):
                bearing = (jx + offset, knuckle_y, jz + 0.10)
                surface.beam((jx + offset, front * 1.04, 0.56), bearing, 0.053, "steel", sides=6)
                surface.beam(bearing, (jx + offset, jy, jz + 0.060), 0.046, "alloy", sides=6)
            surface.beam((sign * 0.90, front * 1.10, 0.44), (jx, knuckle_y, jz + 0.08),
                         0.041, "gold", sides=6)
            joint(root, f"jack{index + 1}Mount", (jx, jy, jz), downward=True)
            px, py, pz = pod_mounts[index]
            mount = (px, py, pz + 0.04)
            mount_size = (0.49, 0.47, 0.08)
            surface.box(mount, mount_size, "alloy")
            box_collider(root, f"Pod Mount {index + 1}", mount, mount_size)
            hanger = (sign * 1.27, front * 1.10, mount[2])
            surface.beam((sign * 1.08, front * 0.89, 0.58), hanger, 0.054, "steel")
            surface.beam(hanger, mount, 0.031, "steel")
            joint(root, f"pod{index + 1}Mount", (px, py, pz), downward=True)
            continue
        shoulder = (sign * 1.22, front * 1.25, hi - 0.19)
        surface.beam((sign * 1.05, front * 0.76, hi - 0.17), shoulder, 0.094, "steel")
        brace = (sign * 0.94, shoulder[1], hi - 0.31)
        surface.beam((brace[0], front * 0.80, brace[2]), brace, 0.063, "steel")
        surface.beam(shoulder, foot, 0.084, "gold")
        surface.beam(brace, (x, y, lo + 0.25), 0.041, "alloy")
        surface.lathe([(lo, 0.22), (lo + 0.09, 0.22), (lo + 0.13, 0.15)], "alloy", 12, (x, y))
        box_collider(root, "Foot" + str(index), foot, (0.31, 0.31, 0.10))
        xy = (sign * HAB_BELL_X, front * HAB_BELL_Z)
        surface.lathe([(-0.06, 0.14), (0.045, 0.26), (0.58, 0.26), (0.71, 0.145)], "ivory", 14, xy)
        surface.lathe([(0.13, 0.265), (0.23, 0.265)], "steel", 14, xy)
        surface.beam((0.89 * sign, y * 0.68, 0.24), (xy[0], xy[1], 0.64), 0.041, "copper")
    if pod_mounts:
        joint(root, "habitatMount", (0, 0, hi))
        joint(root, "deliveryMount", (0, 0, lo), downward=True)
    else:
        layout = [(x, y) for x in (-HAB_BELL_X, HAB_BELL_X) for y in (-HAB_BELL_Z, HAB_BELL_Z)]
        engines(surface, root, p, lo + HAB_BELL_CLEARANCE, 0.465, 0.36, layout)

    # A landing and steps lead away from the side airlock, between the front feet.
    if pod_mounts:
        return
    x = -0.80
    for i in range(8):
        y, z = -1.24 - i * 0.13, 0.98 - i * 0.215
        surface.box((x, y, z), (0.67, 0.19, 0.08), "steel")
        box_collider(root, "Step" + str(i), (x, y, z), (0.67, 0.19, 0.08))
    for side in (-1, 1):
        rx = x + side * 0.35
        surface.beam((rx, -1.34, 1.28), (rx, -2.15, -0.23), 0.028, "gold")
        surface.beam((rx, -1.34, 0.98), (rx, -1.34, 1.28), 0.026, "alloy")
        surface.beam((rx, -2.15, -0.54), (rx, -2.15, -0.23), 0.026, "alloy")


def equipment(surface, root, p, motor=None):
    r, lo, hi = p.radius, -p.height / 2, p.height / 2
    if p.role == "service":
        profile = [(lo + 0.38, r * 0.76), (lo + 0.48, r), (hi - 0.09, r), (hi, r * 0.94)]
        paint = "ivory" if p.id == "famApolloSM" else "olive"
        surface.lathe(
            profile, paint, 32, stripe=lambda n, i: "steel" if n == 1 and i % 8 in (0, 1) else paint
        )
        for i in range(4):
            a = pi * i / 2
            for j in range(4):
                surface.beam(
                    point(r + 0.012, a + 0.055 * j, lo + 0.54),
                    point(r + 0.012, a + 0.055 * j, hi - 0.17),
                    0.018,
                    "alloy",
                )
        if p.id == "famApolloSM":
            surface.box((0, r - 0.005, -0.13), (0.83, 0.15, 1.04), "steel")
            for row in (-0.40, -0.09, 0.22):
                surface.box((0, r + 0.077, row), (0.71, 0.035, 0.17), "ivory")
        else:
            surface.lathe([(lo + 0.49, r + 0.009), (lo + 0.56, r + 0.009)], "sage")
            for side in (-1, 1):
                a = side * pi / 4
                surface.box(point(r * 0.95, a, 0.18), (0.12, 0.43, 0.58), "gasket", a)
                center = point(r * 0.98, a, 0.18)[:2]
                surface.lathe([(-0.09, 0.11), (0.04, 0.17), (0.37, 0.17), (0.46, 0.11)], "sage", 12, center)
        if motor:
            engine_skin, engine_root = motor
            joint_z = lo + 0.38
            engine_skin.lathe([(joint_z - 0.048, r * 0.74), (joint_z, r * 0.76)], "steel")
            hull_collider(root, profile)
            hull_collider(engine_root, [(lo, r * 0.44), (joint_z, r * 0.76)])
            joint(root, "engineMount", (0, 0, joint_z), downward=True)
            joint(engine_root, "serviceMount", (0, 0, joint_z))
            engines(engine_skin, engine_root, p, lo, 0.332, r * 0.43)
            split_shroud(engine_root, p, lo, joint_z)
        else:
            hull_collider(root, [(lo, r * 0.44), *profile])
            engines(surface, root, p, lo, 0.55, r * 0.43)
    elif p.role == "ring":
        # Hollow visually; the contact collider is an array of segments, so a port can pass through.
        surface.lathe([(lo, r * 0.97), (lo + 0.035, r), (hi - 0.035, r), (hi, r * 0.97)], "steel", 32)
        # Replace the lathe end caps with annular faces.
        tris = surface.mesh.submeshes[0]
        del tris[-2 * (32 - 2) :]
        for i in range(32):
            a, b = tau * i / 32, tau * (i + 1) / 32
            for z in (lo, hi):
                face = [
                    point(r * 0.82, a, z),
                    point(r * 0.97, a, z),
                    point(r * 0.97, b, z),
                    point(r * 0.82, b, z),
                ]
                surface.face(face if z == hi else face[::-1], "warning" if i % 8 == 0 else "alloy")
            surface.face(
                [
                    point(r * 0.82, b, lo),
                    point(r * 0.82, a, lo),
                    point(r * 0.82, a, hi),
                    point(r * 0.82, b, hi),
                ],
                "steel",
            )
        for i in range(8):
            a = tau * i / 8
            obj = node("Rim" + str(i), point(r * 0.9, a, 0), (cos(a / 2), 0, 0, sin(a / 2)))
            obj.collider = mu.MuColliderBox(True)
            obj.collider.center = (0, 0, 0)
            obj.collider.size = (r * 0.17, r * 0.70, p.height)
            obj.collider.isTrigger = 0
            root.children.append(obj)
    elif p.role == "adapter":
        surface.lathe([(lo, r), (lo + 0.12, r), (lo + 0.17, r * 0.91)], "alloy")
        surface.lathe([(hi - 0.08, p.top_radius), (hi, p.top_radius)], "ivory")
        for i in range(14):
            a = tau * i / 14
            surface.beam(
                point(r * 0.92, a, lo + 0.13), point(p.top_radius, a + pi / 14, hi - 0.04), 0.037, "steel"
            )
            surface.beam(
                point(r * 0.92, a, lo + 0.13), point(p.top_radius, a - pi / 14, hi - 0.04), 0.037, "alloy"
            )
        hull_collider(root, [(lo, r), (hi, p.top_radius)])
    elif p.role == "tower":
        surface.lathe([(lo, r), (lo + 0.09, r), (lo + 0.11, r * 0.78)], "white", 18)
        for i in range(4):
            a = tau * i / 4 + pi / 4
            surface.beam(point(r * 0.84, a, lo + 0.08), point(0.18, a, 0.14), 0.037, "white")
            surface.beam(point(r * 0.71, a, lo + 0.35), point(0.20, a + pi / 2, -0.01), 0.023, "alloy")
        surface.lathe(
            [(-0.04, 0.21), (0.12, 0.23), (hi - 0.33, 0.20), (hi - 0.18, 0.15), (hi, 0.018)], "ivory", 20
        )
        surface.lathe([(0.30, 0.235), (0.38, 0.235)], "red", 20)
        hull_collider(root, [(lo, r), (0, 0.24), (hi, 0.05)])
        for i in range(4):
            a = pi * i / 2 + pi / 4
            x, y, z = point(0.25, a, -0.02)
            surface.beam((x * 1.4, y * 1.4, z - 0.1), (x * 0.67, y * 0.67, z + 0.14), 0.083, "nozzle")
            # Rotate local +Y into a canted exhaust vector.
            direction = (0.42 * cos(a), 0.42 * sin(a), -math.sqrt(1 - 0.42**2))
            w = math.sqrt((1 + direction[1]) / 2)
            q = (w, direction[2] / (2 * w), 0, -direction[0] / (2 * w))
            root.children.append(node("escapeJet", (x * 1.4, y * 1.4, z - 0.1), q))
    elif p.role == "corer":
        surface.box((0, 0, 0.04), (0.35, 0.20, 0.34), "gold")
        surface.box((0, -0.08, 0.06), (0.23, 0.09, 0.20), "ivory")
        surface.lathe([(lo, 0.035), (0.08, 0.035)], "steel", 12, (0.115, 0))
        box_collider(root, "Housing", (0, 0, 0), (0.36, 0.21, p.height))
    else:
        profile = [(lo, r * 0.87), (lo + 0.05, r), (hi - 0.05, r), (hi, r * 0.87)]
        surface.lathe(profile, "alloy", 8, angle=pi / 8)
        for i in range(8):
            a = i * pi / 4
            surface.box(point(r * 0.91, a, 0), (0.13, 0.41, 0.22), "gold", a)
        hull_collider(root, profile)


def model(part):
    obj = node(part.id)
    surface = Surface()
    if part.role in ("n1", "saturn"):
        booster(surface, obj, part)
    elif part.role == "hab":
        jamestown(surface, obj, part)
    elif part.role == "cradle":
        jamestown_cradle(surface, obj, part)
    elif part.role in CAPSULES | CREWED_LANDERS:
        cabin(surface, obj, part)
    elif part.role in FRAMES:
        landing_frame(surface, obj, part)
    else:
        equipment(surface, obj, part)
    if part.role in ("n1", "saturn", "service"):
        # Stock auto-shrouds enclose the engine bells while another stage is attached below.
        shell = Surface()
        r, lo = part.radius, -part.height / 2
        h = (
            0.50
            if part.role == "service"
            else min(
                part.height * 0.22, r * {1: 0.58, 4: 0.29, 5: 0.255, 8: 0.22, 30: 0.095}[part.engines] * 2.3
            )
        )
        paint = n1_paint(part.id) if part.role == "n1" else "ivory"
        shell.lathe(
            [(lo, r), (lo + h * 0.89, r * 0.995)],
            paint,
            stripe=lambda _, i: (
                n1_paint(part.id, i) if part.role == "n1"
                else "ink" if part.role == "saturn" and i // 4 % 2 == 0
                else paint
            ),
        )
        part_shroud = node("interstage")
        part_shroud.shared_mesh = shell.mesh
        part_shroud.renderer = mu.MuRenderer()
        part_shroud.renderer.materials = [0]
        obj.children.append(part_shroud)
    if part.role in ("hab", "lsam"):
        # ModuleDeployableSolarPanel uses a fixed transform in static mode.
        obj.children.append(
            node(
                "sunCatcher",
                (-0.97, -0.23, 0.82) if part.role == "hab" else (1.05, 0, part.height / 2 + 0.03),
                (math.sqrt(0.5), math.sqrt(0.5), 0, 0),
            )
        )
    return finish_model(obj, surface)


def add_skin(obj, surface, name):
    skin = node(name)
    skin.shared_mesh = surface.mesh
    skin.renderer = mu.MuRenderer()
    skin.renderer.materials = [0]
    obj.children.append(skin)


def finish_model(obj, surface):
    add_skin(obj, surface, "Exterior")
    material = mu.MuMaterial()
    material.name = "FAM Flight Finish"
    material.shaderName = "KSP/Diffuse"
    tex = mu.MuMatTex()
    tex.index, tex.scale, tex.offset = 0, (1, 1), (0, 0)
    material.textureProperties["_MainTex"] = tex
    texture = mu.MuTexture()
    texture.name, texture.type = "livery.png", 0
    result = mu.Mu(obj.transform.name)
    result.obj, result.materials, result.textures = obj, [material], [texture]
    if any(child.transform.name == "Exterior lamp lenses" for child in obj.children):
        lens = mu.MuMaterial()
        lens.name, lens.shaderName = "Jamestown LED lenses", "KSP/Emissive/Diffuse"
        lens.textureProperties.update({"_MainTex": tex, "_Emissive": tex})
        lens.colorProperties["_EmissiveColor"] = (0, 0, 0, 1)
        result.materials.append(lens)
    return result
