"""Inspect the Season 1 model kits in Blender and render their documentation views."""

import argparse
import sys
from itertools import combinations, pairwise
from math import cos, pi, radians, tau
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from io_object_mu.utils import strip_nnn
from mathutils import Quaternion, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import PAINT, point
from modular_models import (
    AIRLOCK,
    AIRLOCK_RELEASE,
    AIRLOCK_RELEASE_HEIGHT,
    CARGO,
    CARGO_PIVOT,
    CHUTE_MODEL,
    DOCK_MODEL,
    FRAME,
    HULL,
    PAD,
    PISTON_MODEL,
    POD,
    PODS,
    RADIO,
    SERVO_MODEL,
    SOLAR_MODELS,
    SPARK,
    TAIL_FINS,
    Piece,
    cargo_fairing,
    kits,
    write_splits,
)
from parts import (
    HAB_PORT_X,
    REVIEW_DOCK_HEIGHT,
    REVIEW_LIFT,
    REVIEW_PAD_Z,
    ROOT,
    STAIR_CLIP,
    STAIR_GROUP,
    STAIR_TREAD_COUNT,
)


def load_editable(name, collection):
    with bpy.data.libraries.load(str(ROOT / "art" / "season-1" / (name + ".blend"))) as (source, result):
        result.objects = list(source.objects)
    roots = [obj for obj in result.objects if obj.parent is None]
    candidates = [obj for obj in roots if strip_nnn(obj.name) == name]
    if len(candidates) != 1:
        raise ValueError(f"Could not find {name} in Blender roots {[obj.name for obj in roots]}")
    root = candidates[0]
    for obj in [root, *root.children_recursive]:
        collection.objects.link(obj)
    return root


def load_mesh(path):
    existing = set(bpy.context.scene.objects)
    result = bpy.ops.import_object.ksp_mu(filepath=str(path), create_colliders=False)
    if "FINISHED" not in result:
        raise RuntimeError(f"Could not open {path} in Blender")
    roots = [obj for obj in set(bpy.context.scene.objects) - existing if obj.parent is None]
    if len(roots) != 1:
        raise RuntimeError(f"Expected one root while importing {path}")
    return roots[0]


def painted_mesh(obj):
    """Read the atlas tiles on the editable mesh and display their solid colors for inspection."""
    mesh = obj.data
    uv = mesh.uv_layers.active.data
    materials = []
    for finish, rgb in PAINT.items():
        material = bpy.data.materials.get("Review " + finish) or bpy.data.materials.new("Review " + finish)
        material.diffuse_color = (*(c / 255 for c in rgb), 1)
        materials.append(material)
    mesh.materials.clear()
    for material in materials:
        mesh.materials.append(material)
    for poly in mesh.polygons:
        u, v = uv[poly.loop_start].uv
        poly.material_index = int(u * 4) + 4 * int(v * 4)


def meshes(root):
    return [o for o in [root, *root.children_recursive] if o.type == "MESH" and not o.hide_render]


def triangles(root, trim_above=float("inf")):
    vertices, faces = [], []
    for obj in meshes(root):
        start = len(vertices)
        vertices.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        obj.data.calc_loop_triangles()
        for triangle in obj.data.loop_triangles:
            face = tuple(start + i for i in triangle.vertices)
            if min(vertices[index].z for index in face) < trim_above:
                faces.append(face)
    return vertices, faces


def check_jamestown(entries, packed):
    bpy.context.view_layer.update()
    frame = next(obj for piece, obj in entries if piece.name == FRAME)
    hull = next(obj for piece, obj in entries if piece.name == HULL)
    airlock = next(obj for piece, obj in entries if piece.name == AIRLOCK)
    vertices, faces = triangles(frame)
    structure = BVHTree.FromPolygons(vertices, faces, all_triangles=True)
    cabin = BVHTree.FromPolygons(*triangles(hull), all_triangles=True)
    pads = [obj for piece, obj in entries if piece.name == PAD]
    floor = frame.location.z + REVIEW_PAD_Z
    if len(pads) != 4 or any(abs(min(v.z for v in triangles(pad)[0]) - floor) > 1e-4 for pad in pads):
        raise ValueError("The four hydraulic footpads must share the boarding plane")
    if min(v.z for v in vertices) - floor < 0.06:
        raise ValueError("The chassis would ground before the footpads")
    nozzle_floor = []
    for piece, root in entries:
        if piece.stock != SPARK and piece.name != POD.id:
            continue
        # Ignore the shared face at the tank mount.
        top = frame.location.z + PODS[0][2]
        verts, tris = triangles(root, trim_above=top - 0.003)
        hardware = BVHTree.FromPolygons(verts, tris, all_triangles=True)
        intersection = next(
            ((a, b) for a, b in structure.overlap(hardware) if min(vertices[i].z for i in faces[a]) < top - 0.003),
            None,
        )
        if intersection:
            a, b = intersection
            support = [tuple(round(k, 3) for k in vertices[i]) for i in faces[a]]
            sample = [
                tuple(round(coordinate, 3) for coordinate in verts[i]) for i in tris[b]
            ]
            raise ValueError(f"{piece.name} intersects the frame below its mount near {sample} and {support}")
        if cabin.overlap(hardware):
            raise ValueError(f"{piece.name} intersects the circular cabin")
        if piece.stock == SPARK:
            nozzle_floor.append(min(v.z for v in verts))
    clearance = min(nozzle_floor) - floor
    if not 0.15 <= clearance <= 0.40:
        raise ValueError(f"Spark ground clearance is {clearance:.3f} m")
    all_vertices = [v for _, obj in entries for v in triangles(obj)[0]]
    ports = {piece.name: obj for piece, obj in entries if piece.stock == DOCK_MODEL}
    faces = {
        name: next(o for o in obj.children_recursive if strip_nnn(o.name) == "dockingNode").matrix_world
        for name, obj in ports.items()
    }
    hull_face = faces["Roof Clamp-O-Tron" if packed else "Front Clamp-O-Tron"]
    tunnel_face = faces["Airlock Clamp-O-Tron"]
    forward = Vector((0, 1, 0))
    up = Vector((0, 0, 1))
    separation = Vector((0, 0, AIRLOCK_RELEASE_HEIGHT if packed else 0))
    if (hull_face.translation + separation - tunnel_face.translation).length > 0.004 or (
        hull_face.to_quaternion() @ forward
    ).dot(tunnel_face.to_quaternion() @ forward) > -0.999:
        raise ValueError("The airlock docking faces do not align")
    if packed:
        ring = next(obj for piece, obj in entries if piece.name == AIRLOCK_RELEASE)
        if (ring.location - hull_face.translation - separation / 2).length > 0.002:
            raise ValueError("The stock TS-12 is off its roof mounting plane")
        adapter = next(obj for piece, obj in entries if piece.name == CARGO.id)
        origin = adapter.location.z + CARGO_PIVOT
        profile = cargo_fairing()
        clearance_values = []
        for piece, obj in entries:
            if piece.name == CARGO.id:
                continue
            for v in triangles(obj)[0]:
                height = v.z - origin
                run = next(((a, r, b, s) for (a, r), (b, s) in pairwise(profile) if a <= height <= b), None)
                if run is None:
                    raise ValueError(f"{piece.name} extends beyond the fairing at height {height:.3f} m")
                a, r, b, s = run
                apothem = cos(pi / 32) * (r + (s - r) * (height - a) / (b - a))
                clearance_values.append((apothem - v.xy.length, piece.name, height))
        gap, limiting_part, height = min(clearance_values)
        if gap <= 0.015:
            raise ValueError(f"{limiting_part} has only {gap:.3f} m of fairing clearance at {height:.3f} m")
        print(f"Packed Jamestown minimum fairing clearance is {gap:.3f} m", flush=True)
    else:
        if (hull_face.to_quaternion() @ up).dot(tunnel_face.to_quaternion() @ up) < 0.999:
            raise ValueError("The side airlock hatch is not upright")
        if structure.overlap(BVHTree.FromPolygons(*triangles(airlock), all_triangles=True)):
            raise ValueError("The side airlock intersects the landing frame")
        check_stair_sweep(frame, airlock, entries, floor)
    for name in ("west", "east", "Rear", "Front"):
        face = faces[name + " Clamp-O-Tron"]
        if abs(face.translation.z - floor - REVIEW_DOCK_HEIGHT) > 1e-4:
            raise ValueError(f"The {name} port moved off its boarding approach height")
        if name in ("west", "east") and abs(abs(face.translation.x) - HAB_PORT_X) > 0.002:
            raise ValueError(f"The {name} port moved off the original end plane")
        if name == "Front" and not packed:
            continue  # The EVA airlock is the visiting module on this face.
        axis = face.to_quaternion() @ forward
        for v in all_vertices:
            offset = v - face.translation
            length = offset.dot(axis)
            if length > 0.01 and (offset - length * axis).length < 1:
                raise ValueError(f"A part enters the {name} port approach near {tuple(v)}")
    print(
        f"Jamestown Blender fit: {clearance:.3f} m bell clearance and four {REVIEW_DOCK_HEIGHT:.2f} m side ports",
        flush=True,
    )


def check_stair_sweep(frame, airlock, entries, floor):
    scene = bpy.context.scene
    stairs = next(o for o in airlock.children if strip_nnn(o.name) == STAIR_GROUP)
    steps = [next(o for o in stairs.children if strip_nnn(o.name) == f"stairTread{i + 1}")
             for i in range(STAIR_TREAD_COUNT)]
    clip = stairs.animation_data.nla_tracks[STAIR_CLIP].strips[0]
    shell = next(o for o in airlock.children if strip_nnn(o.name) == "Exterior")
    others = [shell, *(obj for piece, obj in entries if obj != airlock)]
    clearance = [(obj.name, BVHTree.FromPolygons(*triangles(obj), all_triangles=True)) for obj in others]
    for i in range(33):
        fraction = i / 32
        time = clip.frame_start + (clip.frame_end - clip.frame_start) * fraction
        scene.frame_set(int(time), subframe=time % 1)
        vertices, faces = triangles(stairs)
        stair = BVHTree.FromPolygons(vertices, faces, all_triangles=True)
        gap = min(v.z for v in vertices) - floor
        if gap < -0.001:
            raise ValueError(f"The stairs clear the pad plane by only {gap:.3f} m at {fraction:.0%} deployment")
        for name, obstacle in clearance:
            if obstacle.overlap(stair):
                raise ValueError(f"The stairs intersect {name} at {fraction:.0%} deployment")
    if not 0 <= gap <= 0.004:
        raise ValueError(f"The deployed airlock shoe ends {gap:.3f} m from the pad plane")
    tops = [max(v.z for v in triangles(next(o for o in step.children if o.type == "MESH"))[0])
            for step in steps]
    if not all(0.17 <= a - b <= 0.24 for a, b in zip(tops, tops[1:] + [floor])):
        raise ValueError("Jamestown stairs have an excessive rise or stop too far above the ground")
    print(f"Jamestown stairs clear 33 animated positions. Lowest tread is {tops[-1] - floor:.3f} m high.")
    scene.frame_set(999)


def build_assembly(scene, spec, stock_parts, split_parts):
    collection = bpy.data.collections.new("Parts")
    scene.collection.children.link(collection)
    roots = []
    for piece in spec:
        if piece.stock:
            model = (stock_parts.parents[1] if piece.stock.startswith("SquadExpansion/") else stock_parts) / piece.stock
            root = load_mesh(model)
            if piece.stock in SOLAR_MODELS:
                for obj in meshes(root):
                    if "pane" in strip_nnn(obj.name).lower():
                        for material in obj.data.materials:
                            material.diffuse_color = (0.07, 0.16, 0.32, 1)
            if piece.stock in (SPARK, CHUTE_MODEL):
                hidden = {"Shroud", "LgMount", "BoatTail"} if piece.stock == SPARK else {"canopy"}
                for obj in root.children_recursive:
                    if strip_nnn(obj.name) in hidden:
                        obj.hide_render = True
                        for child in obj.children_recursive:
                            child.hide_render = True
        else:
            draft = split_parts / (piece.name + ".mu")
            root = load_mesh(draft) if draft.exists() else load_editable(piece.name, collection)
            for obj in root.children_recursive:
                obj.hide_render = obj.type != "MESH" or not strip_nnn(obj.name).startswith("Exterior")
                if not obj.hide_render:
                    painted_mesh(obj)
        root.name = piece.name
        root.location = piece.position
        root.rotation_mode = "QUATERNION"
        root.rotation_quaternion = piece.rotation
        roots.append((piece, root))
    return roots


def check_split_joints(entries):
    bpy.context.view_layer.update()
    groups = {(piece.name, piece.position): obj for piece, obj in entries}

    def marker(root, name):
        return next(obj for obj in root.children_recursive if strip_nnn(obj.name) == name)

    def face_each_other(a, b):
        first, second = a.matrix_world, b.matrix_world
        up = Vector((0, 0, 1))
        dot = (first.to_quaternion() @ up).dot(second.to_quaternion() @ up)
        if (first.translation - second.translation).length > 0.0001 or dot > -0.999:
            raise ValueError(f"{a.parent.name} and {b.parent.name} have mismatched stack planes")

    for piece, root in entries:
        if not piece.name.endswith("Motor"):
            continue
        prefix = piece.name.removesuffix("Motor")
        tank = groups.get((prefix + "Tank", piece.position))
        if tank is None:
            bus = groups[(prefix + "Bus", piece.position)]
            face_each_other(marker(bus, "engineMount"), marker(root, "serviceMount"))
        elif (frame := groups.get((prefix + "Frame", piece.position))) is not None:
            face_each_other(marker(frame, "fuelMount"), marker(tank, "frameMount"))
            face_each_other(marker(tank, "engineMount"), marker(root, "fuelMount"))
        else:
            face_each_other(marker(tank, "engineMount"), marker(root, "tankMount"))


def check_tail_fins(entries):
    for stage, name in TAIL_FINS.items():
        motor = next(obj for piece, obj in entries if piece.name == stage + "Motor")
        tank = next(obj for piece, obj in entries if piece.name == stage + "Tank")
        skirt = BVHTree.FromPolygons(*triangles(motor), all_triangles=True)
        barrel = BVHTree.FromPolygons(*triangles(tank), all_triangles=True)
        fins = [obj for piece, obj in entries if piece.name == name]
        if len(fins) != 4:
            raise ValueError(f"{stage} requires four tail fins")
        for fin in fins:
            pose = fin.matrix_world
            inward = pose.to_quaternion() @ Vector((1, 0, 0))
            height = 0.195 if stage == "famSaturnIC" else 0.085
            for z in (-height, 0, height):
                for y in (-0.073, 0.073):
                    _, _, _, distance = skirt.ray_cast(pose @ Vector((-0.10, y, z)), inward, 0.14)
                    if distance is None or distance < 0.066:
                        raise ValueError(f"{name}: the saddle footprint misses the engine skirt")
            pivot = next(o for o in fin.children_recursive if strip_nnn(o.name) == "obj_ctrlSrf")
            pivot.rotation_mode = "QUATERNION"
            blade = next(o for o in pivot.children_recursive if o.type == "MESH")
            for angle in (-12, 0, 12):
                pivot.rotation_quaternion = Quaternion((1, 0, 0), radians(angle))
                bpy.context.view_layer.update()
                blade.data.calc_loop_triangles()
                moved = BVHTree.FromPolygons(
                    [blade.matrix_world @ v.co for v in blade.data.vertices],
                    [t.vertices for t in blade.data.loop_triangles],
                    all_triangles=True,
                )
                if skirt.overlap(moved) or barrel.overlap(moved):
                    raise ValueError(f"{name}: blade clips the airframe at {angle} degrees")
            pivot.rotation_quaternion = Quaternion()
        print(f"{stage}: four tail saddles seat on the skirts and blades clear the airframe through ±12°")


def check_canopy(scene, entries):
    deployables = [(p.name, obj) for p, obj in entries if p.stock in SOLAR_MODELS or p.stock == RADIO]
    for frame in (1, 40, 80, 120, 160, 999):
        scene.frame_set(frame)
        meshes_by_part = [
            (name, BVHTree.FromPolygons(*triangles(obj), all_triangles=True)) for name, obj in deployables
        ]
        for (first, a), (second, b) in combinations(meshes_by_part, 2):
            if a.overlap(b):
                raise ValueError(f"{first} intersects {second} during deployment at frame {frame}")


def fairing_shell(scene, origin, cutaway):
    profile = cargo_fairing()
    stations = 32
    sectors = range(4, 23) if cutaway else range(stations)
    vertices, faces = [], []
    for (low, radius), (high, upper) in pairwise(profile):
        for i in sectors:
            a, b = tau * i / stations, tau * (i + 1) / stations
            start = len(vertices)
            vertices.extend((point(radius, a, low), point(radius, b, low), point(upper, b, high), point(upper, a, high)))
            faces.append(tuple(range(start, start + 4)))
    drawing = bpy.data.meshes.new("Procedural fairing profile")
    drawing.from_pydata(vertices, [], faces)
    for name in ("ivory", "ink"):
        material = bpy.data.materials.get("Review " + name) or bpy.data.materials.new("Review " + name)
        material.diffuse_color = (*(channel / 255 for channel in PAINT[name]), 1)
        drawing.materials.append(material)
    for face in drawing.polygons[:len(sectors)]:
        face.material_index = 1
    label = "Fairing cutaway" if cutaway else "Fairing exterior"
    shell = bpy.data.objects.new(label, drawing)
    scene.collection.objects.link(shell)
    shell.location.z = origin
    return Piece(label, (0, 0, origin)), shell


def render_transposition(scene, camera, entries, output):
    assembly = [(piece, obj) for piece, obj in entries if piece.name not in (CARGO.id, AIRLOCK_RELEASE)]
    hardware = [
        (mesh, mesh.hide_render)
        for piece, obj in entries if piece.name in (CARGO.id, AIRLOCK_RELEASE)
        for mesh in meshes(obj)
    ]
    for mesh, _ in hardware:
        mesh.hide_render = True
    saved = [(obj, obj.matrix_world.copy()) for _, obj in assembly]
    front = next(obj for piece, obj in assembly if piece.name == "Front Clamp-O-Tron")
    airlock = next(obj for piece, obj in assembly if piece.name == "Airlock Clamp-O-Tron")
    side = next(obj for obj in front.children_recursive if strip_nnn(obj.name) == "dockingNode")
    collar = next(obj for obj in airlock.children_recursive if strip_nnn(obj.name) == "dockingNode")
    turn = Quaternion((1, 0, 0), -pi / 2)
    offset = collar.matrix_world.translation - turn @ side.matrix_world.translation - Vector((0, 0, 0.48))
    for obj, pose in saved:
        if obj != airlock and obj.name != AIRLOCK:
            obj.matrix_world = turn.to_matrix().to_4x4() @ pose
            obj.location += offset
    bpy.context.view_layer.update()
    render(scene, camera, assembly, output, (6.5, -10, 4.0))
    for obj, pose in saved:
        obj.matrix_world = pose
    for mesh, hidden in hardware:
        mesh.hide_render = hidden
    bpy.context.view_layer.update()


def render_airlock(scene, camera, entries, output):
    module = [(p, obj) for p, obj in entries if p.name in (AIRLOCK, "Airlock Clamp-O-Tron")]
    rest = [mesh for entry in entries if entry not in module for mesh in meshes(entry[1])]
    for mesh in rest:
        mesh.hide_render = True
    for pose, frame in (("stowed", 1), ("stairs", 999)):
        scene.frame_set(frame)
        render(scene, camera, module, output / f"jamestown-airlock-{pose}.png", (6, -9, 3.8))
    for mesh in rest:
        mesh.hide_render = False


def render_columbia(scene, camera, entries, output):
    capsule = [(p, obj) for p, obj in entries if p.name == "famApolloCM" or p.stock == CHUTE_MODEL]
    others = [mesh for p, obj in entries if (p, obj) not in capsule for mesh in meshes(obj)]
    for mesh in others:
        mesh.hide_render = True
    for shot, direction in (("hatch", (4, -9, 3.6)), ("edge", (9, -2, 1.0)), ("underside", (2, -8, -6))):
        render(scene, camera, capsule, output / ("apollo-columbia-" + shot + ".png"), direction)
    for mesh in others:
        mesh.hide_render = False


def render_lift(scene, camera, entries, output):
    scene.frame_set(1)  # The stair flight folds before raising the cabin.
    frame = next(root for piece, root in entries if piece.name == FRAME)
    pistons = [root for piece, root in entries if piece.stock == PISTON_MODEL]
    pads = [root for piece, root in entries if piece.name == PAD]
    if len(pistons) != 4 or len(pads) != 4:
        raise ValueError("Four independent cylinders and pads are required")
    fixed = [(piece.name, BVHTree.FromPolygons(*triangles(root), all_triangles=True))
             for piece, root in entries if piece.name in (FRAME, HULL, POD.id) or piece.stock == SPARK]
    tips = [next(o for o in root.children_recursive if strip_nnn(o.name) == "TopJoint") for root in pistons]
    origins = [(tip, tip.location.copy()) for tip in tips] + [(pad, pad.location.copy()) for pad in pads]
    for step in range(9):
        stroke = REVIEW_LIFT * step / 8
        for obj, location in origins:
            obj.location.z = location.z + (stroke if obj in tips else -stroke)
        bpy.context.view_layer.update()
        floor = frame.location.z + REVIEW_PAD_Z - stroke
        for tip, pad in zip(tips, pads):
            # The moving end and its own foot share a mounting plane.
            if abs(min(v.z for v in triangles(pad)[0]) - floor) > 0.0001:
                raise ValueError(f"{pad.name} missed the expected pad plane at {stroke:.3f} m")
            for moving in (tip, pad):
                tree = BVHTree.FromPolygons(*triangles(moving), all_triangles=True)
                for name, other in fixed:
                    hits = other.overlap(tree)
                    if hits:
                        vi, fs = triangles(moving)
                        points = [tuple(round(k, 3) for k in vi[i]) for i in fs[hits[0][1]]]
                        raise ValueError(f"{moving.name} clips {name} at {stroke:.3f} m near {points}")
    render(scene, camera, entries, output / "jamestown-raised.png", (-10, -6.7, 2.4))
    for obj, location in origins:
        obj.location = location
    scene.frame_set(999)


def check_roll(scene, camera, entries, output):
    scene.frame_set(1)
    servo = next(root for piece, root in entries if piece.stock == SERVO_MODEL)
    rotor = next(o for o in servo.children_recursive if strip_nnn(o.name) == "TopJoint")
    moving = [(piece, root) for piece, root in entries if piece.name in
              (AIRLOCK, "Front Clamp-O-Tron", "Airlock Clamp-O-Tron")]
    pose = [(root, root.matrix_world.copy()) for _, root in moving] + [(rotor, rotor.matrix_world.copy())]
    stationary = [(p.name, BVHTree.FromPolygons(*triangles(obj), all_triangles=True)) for p, obj in entries
                  if p.name not in (AIRLOCK, "Front Clamp-O-Tron", "Airlock Clamp-O-Tron") and obj != servo]
    axis = servo.matrix_world.to_quaternion() @ Vector((0, 0, 1))
    origin = servo.matrix_world.translation.copy()
    for angle in sorted({-177, 177, *range(-175, 176, 5)}):
        rotation = Quaternion(axis, radians(angle))
        for obj, original in pose:
            mat = rotation.to_matrix().to_4x4() @ original
            mat.translation = origin + rotation @ (original.translation - origin)
            obj.matrix_world = mat
        bpy.context.view_layer.update()
        barrel = next(root for piece, root in moving if piece.name == AIRLOCK)
        tree = BVHTree.FromPolygons(*triangles(barrel), all_triangles=True)
        for name, obstacle in stationary:
            if obstacle.overlap(tree):
                raise ValueError(f"Folded airlock hits {name} at {angle} degrees servo roll")
        if angle == 90:
            render(scene, camera, entries, output / "jamestown-servo.png", (5, -10, 3.0))
    for obj, original in pose:
        obj.matrix_world = original
    scene.frame_set(999)


def frame_camera(scene, camera, entries, direction):
    bpy.context.view_layer.update()
    verts = [v for _, obj in entries for v in triangles(obj)[0]]
    orientation = (
        Quaternion((0, 0, 1), -pi / 2) if direction[:2] == (0, 0)
        else (-Vector(direction)).to_track_quat("-Z", "Y")
    )
    axes = [orientation @ Vector(axis) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    limits = [(min(v.dot(axis) for v in verts), max(v.dot(axis) for v in verts)) for axis in axes]
    center = sum((axis * ((a + b) / 2) for axis, (a, b) in zip(axes, limits)), Vector())
    width, height = (b - a for a, b in limits[:2])
    aspect = scene.render.resolution_x / scene.render.resolution_y
    camera.data.ortho_scale = 1.19 * max(width, aspect * height)
    camera.location = center + Vector(direction).normalized() * 40
    camera.rotation_euler = orientation.to_euler()
    bpy.context.view_layer.update()
    for v in verts:
        p = world_to_camera_view(scene, camera, v)
        if not (0.02 < p.x < 0.98 and 0.02 < p.y < 0.98):
            raise ValueError("Blender review camera cropped the model")


def render(scene, camera, entries, filename, direction):
    frame_camera(scene, camera, entries, direction)
    scene.render.filepath = str(filename)
    bpy.ops.render.render(write_still=True)


def save_editable(scene, entries, destination):
    # Keep the native model files portable by storing exact stock attachment references as empties.
    for piece, root in entries:
        if piece.stock:
            for obj in [*root.children_recursive, root]:
                bpy.data.objects.remove(obj, do_unlink=True)
            reference = bpy.data.objects.new(piece.name + " [stock]", None)
            scene.collection.objects.link(reference)
            reference.location = piece.position
            reference.rotation_mode = "QUATERNION"
            reference.rotation_quaternion = piece.rotation
            reference.empty_display_type = "CIRCLE"
            reference.empty_display_size = 0.24
            reference["KSP stock model"] = ("" if piece.stock.startswith("SquadExpansion/") else "Squad/Parts/") + piece.stock
        else:
            root.location = piece.position
            root["Exploded Z offset"] = piece.separation
            for obj in root.children_recursive:
                if obj.type == "MESH" and obj.hide_render:
                    obj.hide_set(True)
    bpy.data.orphans_purge(do_recursive=True)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
                area.spaces.active.shading.color_type = "MATERIAL"
    bpy.ops.wm.save_as_mainfile(filepath=str(destination), compress=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kit", choices=tuple(kits()), action="append")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    args.output.mkdir(parents=True, exist_ok=True)
    split_parts = args.output / "parts"
    write_splits(split_parts)
    stock_parts = args.ksp_root / "GameData/Squad/Parts"
    views = {
        "jamestown": (-10, -6.7, 3.5),
        "jamestown-packed": (4, -10, 2.1),
        "launchers": (4, -25, 3),
        "soviet": (2, 12, 2),
        "apollo": (2.5, 12, 2),
        "lsam": (4.5, 10, 2.5),
    }
    for name, spec in kits().items():
        if args.kit and name not in args.kit:
            continue
        bpy.data.batch_remove(list(bpy.data.objects))
        scene = bpy.context.scene
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x = 1400 if name in ("launchers", "lsam") else 1920
        scene.render.resolution_y = 1920 if name in ("launchers", "lsam") else 1440
        scene.render.resolution_percentage = 100
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.color_type = "MATERIAL"
        shading.show_shadows = True
        shading.show_cavity = True
        shading.cavity_type = "BOTH"
        shading.background_type = "WORLD"
        entries = build_assembly(scene, spec, stock_parts, split_parts)
        check_split_joints(entries)
        camera = bpy.data.objects.new("Review camera", bpy.data.cameras.new("Review camera"))
        scene.collection.objects.link(camera)
        scene.camera = camera
        camera.data.type = "ORTHO"
        camera.data.sensor_fit = "HORIZONTAL"
        direction = views[name]
        if name == "apollo":
            render_columbia(scene, camera, entries, args.output)
        if name == "launchers":
            check_tail_fins(entries)
            tails = [
                (piece, obj) for piece, obj in entries
                if piece.name in TAIL_FINS.values() or piece.name.removesuffix("Motor") in TAIL_FINS
            ]
            scene.render.resolution_x = 1800
            scene.render.resolution_y = 940
            render(scene, camera, tails, args.output / "launchers-tail.png", (1, -7, -2))
            scene.render.resolution_x = 1400
            scene.render.resolution_y = 1920
        shrouds = [
            child for _, obj in entries for child in obj.children_recursive
            if child.type == "MESH" and strip_nnn(child.name) == "interstage"
        ]
        if name == "launchers":
            for shroud in shrouds:
                painted_mesh(shroud)
                shroud.hide_render = False
            render(scene, camera, entries, args.output / "launchers-assembled.png", direction)
            for shroud in shrouds:
                shroud.hide_render = True
        if name == "jamestown":
            scene.frame_set(999)
            check_jamestown(entries, packed=False)
            check_canopy(scene, entries)
            scene.frame_set(1)
            render(scene, camera, entries, args.output / "jamestown-folded.png", direction)
            render(scene, camera, entries, args.output / "jamestown-plan.png", (0, 0, 10))
            scene.frame_set(999)
            render(scene, camera, entries, args.output / "jamestown-assembled.png", direction)
            render_airlock(scene, camera, entries, args.output)
            render_lift(scene, camera, entries, args.output)
            check_roll(scene, camera, entries, args.output)
            render(scene, camera, entries, args.output / "jamestown-rear.png", (5.5, 10, 3.2))
            render(scene, camera, entries, args.output / "jamestown-undercarriage.png", (5, -10, -5.0))
        if name == "jamestown-packed":
            scene.frame_set(1)
            check_jamestown(entries, packed=True)
            render_transposition(scene, camera, entries, args.output / "jamestown-transposition.png")
            adapter = next(obj for piece, obj in entries if piece.name == CARGO.id)
            origin = adapter.location.z + CARGO_PIVOT
            exterior = fairing_shell(scene, origin, cutaway=False)
            render(scene, camera, [*entries, exterior], args.output / "jamestown-fairing.png", direction)
            bpy.data.objects.remove(exterior[1], do_unlink=True)
            cutaway = fairing_shell(scene, origin, cutaway=True)
            entries.append(cutaway)
            render(scene, camera, entries, args.output / "jamestown-packed.png", direction)
            save_editable(scene, entries, args.output / (name + ".blend"))
            continue
        for piece, root in entries:
            root.location.z += piece.separation
            if piece.stock == SPARK or piece.name == POD.id:
                root.location.x += 0.37 if piece.position[0] > 0 else -0.37
                root.location.y += 0.23 if piece.position[1] > 0 else -0.23
        render(scene, camera, entries, args.output / (name + "-exploded.png"), direction)
        for piece, root in entries:
            root.location = piece.position
        if name == "launchers":
            for shroud in shrouds:
                shroud.hide_render = False
        frame_camera(scene, camera, entries, direction)
        save_editable(scene, entries, args.output / (name + ".blend"))


if __name__ == "__main__":
    main()
