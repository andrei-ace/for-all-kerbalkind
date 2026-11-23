"""Open the authored part meshes as editable .blend files with the io_object_mu add-on.

blender --background --python tools/blender_parts.py -- import /path/to/art
blender --background --python tools/blender_parts.py -- export /path/to/art
"""

import argparse
import sys
from pathlib import Path

import addon_utils
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parts import ART, CATALOG


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("import", "refresh", "export"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--models", type=Path, default=ART, help="Directory for the game .mu files")
    parser.add_argument("--part", action="append", choices=[p.id for p in CATALOG])
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True, exist_ok=True)
    args.models = args.models.resolve()
    args.models.mkdir(parents=True, exist_ok=True)
    if not addon_utils.check("io_object_mu")[1]:
        addon_utils.enable("io_object_mu", default_set=True)
    from io_object_mu.export_mu.attachnode import rotation_correction
    from io_object_mu.utils import strip_nnn

    for p in CATALOG:
        if args.part and p.id not in args.part:
            continue
        workfile = args.directory / (p.id + ".blend")
        gamefile = args.models / (p.id + ".mu")
        if args.action == "import":
            if workfile.exists():
                raise FileExistsError(f"An editable source already exists at {workfile}")
            # Keep the add-on registered while giving each part its own scene resources.
            data = bpy.data
            data.batch_remove(
                [
                    item
                    for items in (
                        data.objects,
                        data.collections,
                        data.meshes,
                        data.materials,
                        data.images,
                        data.node_groups,
                    )
                    for item in items
                ]
            )
            result = bpy.ops.import_object.ksp_mu(filepath=str(gamefile), create_colliders=True)
            if "FINISHED" not in result:
                raise RuntimeError(f"Could not import {gamefile}")
            # The exporter applies its Blender-empty axis convention to thrustTransform.
            # Store that convention in the editable scene so KSP gets the original nozzle direction.
            for obj in bpy.context.scene.objects:
                if strip_nnn(obj.name) == "thrustTransform":
                    obj.rotation_quaternion @= rotation_correction.inverted()
            bpy.ops.file.pack_all()
            bpy.ops.wm.save_as_mainfile(filepath=str(workfile), compress=True)
        else:
            bpy.ops.wm.open_mainfile(filepath=str(workfile))
            roots = [o for o in bpy.context.scene.objects if o.parent is None and strip_nnn(o.name) == p.id]
            if len(roots) != 1:
                raise RuntimeError(f"Expected one {p.id} model root in {workfile}")
            if args.action == "refresh":
                # Keep the existing Blender workfile, root, and scene settings.
                root = roots[0]
                for obj in list(root.children_recursive):
                    bpy.data.objects.remove(obj, do_unlink=True)
                scene_objects = set(bpy.context.scene.objects)
                result = bpy.ops.import_object.ksp_mu(filepath=str(gamefile), create_colliders=True)
                if "FINISHED" not in result:
                    raise RuntimeError(f"Could not import {gamefile}")
                imported = set(bpy.context.scene.objects) - scene_objects
                replacement = next(o for o in imported if o.parent is None and strip_nnn(o.name) == p.id)
                for obj in imported:
                    if obj.parent == replacement:
                        obj.parent = root
                    if strip_nnn(obj.name) == "thrustTransform":
                        obj.rotation_quaternion @= rotation_correction.inverted()
                bpy.data.objects.remove(replacement, do_unlink=True)
                bpy.context.preferences.filepaths.save_version = 0
                bpy.ops.file.pack_all()
                bpy.ops.wm.save_as_mainfile(filepath=str(workfile), compress=True)
                continue
            bpy.ops.object.select_all(action="DESELECT")
            roots[0].select_set(True)
            bpy.context.view_layer.objects.active = roots[0]
            result = bpy.ops.export_object.ksp_mu(filepath=str(gamefile))
            if "FINISHED" not in result:
                raise RuntimeError(f"Could not export {gamefile}")


if __name__ == "__main__":
    main()
