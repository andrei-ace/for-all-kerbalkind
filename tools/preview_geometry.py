"""Render the same part prefabs and persisted configurations that players load."""

from copy import copy
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from attachments import STOCK_CHUTE, world_direction
from build_review import STOCK_PARTS
from config import read_node
from models import Surface
from modular_models import PISTON, ROBOTICS, SERVO
from parts import HAB_FIXTURES
from vendor.mu import Mu
from verify import craft_pose, key, snapshot_pose


def unit(v):
    return np.asarray(v) / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-12)


def transform(vectors, matrix):
    # Small fixed-size products avoid platform BLAS dispatch for each triangle.
    return np.einsum("...j,ij->...i", vectors, matrix)


def rotation(q):
    return np.column_stack([world_direction(q, v) for v in np.eye(3)])


def value(node, key, default=None):
    values = node.values(key)
    if values:
        return values[0]
    if default is None:
        raise ValueError(f"Missing {key} in {node.kind}")
    return default


def modules(node):
    return {value(m, "name"): m for m in node.children("MODULE")}


@lru_cache
def texture(path):
    with Image.open(path) as image:
        return np.ascontiguousarray(image.convert("RGB"))


def solar_paint(image):
    # Preserve the stock cell pattern and apply the blue from the Blender review palette.
    luminance = np.asarray(image).mean(axis=2, keepdims=True) / 255
    return np.ascontiguousarray((.60 + .40 * luminance) * (60, 97, 151), dtype=np.uint8)


def mesh_batch(mesh, transforms, tex, submesh):
    vertices = np.asarray(mesh.verts)
    normals = np.asarray(mesh.normals)
    for step in transforms:
        w, x, y, z = step.localRotation
        matrix = rotation((x, y, z, w))
        scale = np.array(step.localScale)
        vertices = transform(vertices * scale, matrix) + np.array(step.localPosition)
        normals = transform(normals / np.where(scale == 0, 1, scale), matrix)
    faces = np.array(mesh.submeshes[submesh])
    points = vertices[:, (0, 2, 1)][faces]
    normal = unit(normals[:, (0, 2, 1)][faces].mean(axis=1))
    uv = np.asarray(mesh.uvs)[faces] if mesh.uvs else np.zeros((*faces.shape, 2))
    return points, uv, normal, tex


def animated_poses(root, clips):
    """Apply saved animation endpoints. Mu transforms are Blender-space, curves Unity-space."""
    overrides = {}

    def visit(node, path):
        for clip in getattr(getattr(node, "animation", None), "clips", ()):
            if clip.name not in clips:
                continue
            for curve in clip.curves:
                field, _, axis = curve.property.rpartition(".")
                target = (path + "/" + curve.path).strip("/")
                if axis not in ("x", "y", "z", "w") or field not in (
                    "m_LocalPosition", "m_LocalRotation", "m_LocalScale", "localPosition", "localRotation", "localScale"
                ):
                    continue
                keyframe = curve.keys[-1] if clips[clip.name] else curve.keys[0]
                prop = field.replace("m_Local", "local")
                if prop == "localRotation":
                    index = {"w": 0, "x": 1, "z": 2, "y": 3}[axis]
                    val = keyframe.value if axis == "w" else -keyframe.value
                else:
                    index = {"x": 0, "z": 1, "y": 2}[axis]
                    val = keyframe.value
                overrides.setdefault(target, []).append((prop, index, val))
        for child in node.children:
            visit(child, path + "/" + child.transform.name)
    visit(root, "")
    return overrides


class Fleet:
    def __init__(self, release, game):
        self.release = release
        self.game_data = game / "GameData"
        self.parts = release / "GameData/FAMSeasons/Season1/Parts"
        self.configs = {}
        stock = self.game_data / "Squad/Parts"
        paths = [*sorted(self.parts.glob("*.cfg")), stock.parent.parent / STOCK_CHUTE / "parachuteMk2-R.cfg"]
        paths += [stock / path for path in STOCK_PARTS.values()]
        paths += [stock / fixture.config for fixture in HAB_FIXTURES.values()]
        paths += [self.game_data / ROBOTICS / f"{name}.cfg" for name in (PISTON, SERVO)]
        for path in paths:
            cfg = read_node(path).children("PART")[0]
            self.configs[value(cfg, "name")] = (path, cfg)

    def scenario(self, number):
        path, = (self.release / "saves/scenarios").glob(f"FAM S1.{number} - *.sfs")
        flight = read_node(path).children("GAME")[0].children("FLIGHTSTATE")[0]
        return {value(v, "name"): v for v in flight.children("VESSEL")}

    def vab(self, title):
        return read_node(self.release / f"Ships/VAB/FAM S1 - {title}.craft")

    def model(self, name):
        path, cfg = self.configs[name]
        if cfg.children("MODEL"):
            model, = cfg.children("MODEL")
            data = self.release / "GameData" if path.parent == self.parts else self.game_data
            return (data / value(model, "model")).with_suffix(".mu")
        return path.parent / value(cfg, "mesh")

    @lru_cache
    def asset(self, name, hidden, clips):
        path = self.model(name)
        mu = Mu().read(path)
        cfg = self.configs[name][1]
        scale = float(value(cfg, "rescaleFactor", "1.25"))
        overrides = animated_poses(mu.obj, dict(clips))
        batches = []

        def visit(obj, trail, ancestors):
            if obj.transform.name in hidden:
                return
            tf = copy(obj.transform)
            for prop, idx, v in overrides.get(trail.strip("/"), ()):
                vals = list(getattr(tf, prop))
                vals[idx] = v
                setattr(tf, prop, vals)
            steps = ancestors if obj is mu.obj else (tf, *ancestors)
            mesh = getattr(obj, "shared_mesh", None)
            if mesh is not None and hasattr(obj, "renderer"):
                for idx, group in enumerate(mesh.submeshes):
                    if not group:
                        continue
                    mat = mu.materials[obj.renderer.materials[idx]]
                    entry = mat.textureProperties.get("_MainTex")
                    if entry:
                        stem = Path(mu.textures[entry.index].name).stem
                        texfile = next((f for f in path.parent.iterdir()
                                        if f.stem.lower() == stem.lower() and f.suffix.lower() in (".dds", ".png")), None)
                        if texfile is None:
                            raise ValueError(f"{path}: missing material texture {stem}")
                        tex = texture(texfile)
                    else:
                        color = mat.colorProperties.get("_Color", (.78, .79, .8, 1))
                        tex = np.array([[np.clip(np.asarray(color[:3]) * 255, 0, 255)]], dtype=np.uint8)
                    if "solarcell" in mat.name.lower():
                        tex = solar_paint(tex)
                    points, uv, normals, tex = mesh_batch(mesh, steps, tex, idx)
                    batches.append((points * scale, uv, normals, tex))
            for child in obj.children:
                visit(child, trail + "/" + child.transform.name, steps)
        visit(mu.obj, "", ())
        return batches

    def craft(self, vessel, select=None, origin=None):
        parts = vessel.children("PART")
        ids = [key(p) for p in parts]
        vab_ids = {value(p, "part"): i for i, p in enumerate(parts) if p.values("part")}
        pose = craft_pose if vab_ids else snapshot_pose
        pivot = np.asarray(pose(parts[ids.index(origin)])[0]) if origin else np.zeros(3)
        result = []
        for i, part in enumerate(parts):
            name = ids[i]
            if select is not None and i not in select:
                continue
            cfg = self.configs[name][1]
            defaults, saved = modules(cfg), modules(part)
            hidden, clips = {"canopy"}, {}
            bottom = next((s.split(",")[1].strip() for s in part.values("attN") if s.startswith("bottom,")), "-1")
            if "ModuleJettison" in defaults:
                connected = bottom not in ("-1", "")
                if select is not None and connected:
                    attached = vab_ids[bottom.rsplit("_", 1)[0]] if vab_ids else int(bottom)
                    connected = attached in select
                if not connected or value(saved.get("ModuleJettison", cfg), "isJettisoned", "False") == "True":
                    hidden.add(value(defaults["ModuleJettison"], "jettisonName"))
            if "ModulePartVariants" in saved:
                variant_id = value(saved["ModulePartVariants"], "selectedVariant", "")
                for variant in defaults["ModulePartVariants"].children("VARIANT"):
                    if value(variant, "name") == variant_id:
                        for objects in variant.children("GAMEOBJECTS"):
                            hidden.update(k for k, v in objects.entries if str(v).lower() == "false")
            for label, mod in saved.items():
                if label in defaults and defaults[label].values("animationName"):
                    if mod.values("animTime") or mod.values("deployState"):
                        extended = float(value(mod, "animTime", "0")) >= .5 or value(mod, "deployState", "") == "EXTENDED"
                        clips[value(defaults[label], "animationName")] = extended
            shapes = list(self.asset(name, frozenset(hidden), tuple(sorted(clips.items()))))
            if "ModuleProceduralFairing" in saved:
                fairing = saved["ModuleProceduralFairing"]
                rings = fairing.children("XSECTION")
                if rings:
                    y = float(value(defaults["ModuleProceduralFairing"], "pivot").split(",")[1])
                    surface = Surface()
                    surface.lathe([(y + float(value(r, "h")), float(value(r, "r"))) for r in rings], "ivory", 64)
                    shapes.append(mesh_batch(surface.mesh, (), texture(self.parts / "livery.png"), 0))
            pos, quat = pose(part)
            r = rotation(quat)
            for points, uv, normals, tex in shapes:
                result.append((transform(points, r) + np.asarray(pos) - pivot, uv, transform(normals, r), tex))
        return result
