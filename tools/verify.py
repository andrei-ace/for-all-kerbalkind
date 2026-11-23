"""Check the actual GameData and .craft payload, including staging and delta-v."""

import argparse
import math
import struct
from collections import defaultdict
from pathlib import Path

from attachments import (
    STOCK_CHUTE,
    add,
    dot,
    local_direction,
    mesh_triangles,
    mount_samples,
    rotate,
    scale,
    surface_offset,
    world_direction,
    world_point,
)
from config import Node, read_node
from contracts import AMERICAN, GROUP, SITE_LAT, SITE_LON, SOVIET
from crew import SEASON_ONE_CAST
from models import minus, unit
from parts import (
    FRAMES,
    HAB,
    HAB_BELL_CLEARANCE,
    HAB_BELL_X,
    HAB_BELL_Z,
    HAB_FIXTURES,
    HAB_PORT_X,
    HAB_PORT_Y,
    HAB_PORTS,
    LOGISTICS,
    PARTS,
    POLAR,
    ROOT,
)
from scenarios import (
    KERBIN,
    MUN,
    MUN_RADIUS,
    OBJECTIVE_ASSETS,
    PAD_HEIGHT,
    PAD_LAT,
    PAD_LON,
    SCENARIOS,
    scenarios,
)
from mun_descent import polar_descent
from vendor.mu import Mu

G0 = 9.80665
DENSITY = {
    "LiquidFuel": 0.005,
    "Oxidizer": 0.005,
    "MonoPropellant": 0.004,
    "Ablator": 0.001,
    "SolidFuel": 0.0075,
    "ElectricCharge": 0,
}


def need(ok, message):
    if not ok:
        raise ValueError(message)


def one(node, key):
    values = node.values(key)
    need(len(values) == 1, f"{node.kind} must have exactly one {key}, got {values}")
    return values[0]


def descendants(node):
    yield node
    for child in node.entries:
        if not isinstance(child, tuple):
            yield from descendants(child)


def objects(obj):
    yield obj
    for child in obj.children:
        yield from objects(child)


def modules(part):
    return {one(m, "name"): m for m in part.children("MODULE")}


def skips_staging(module):
    return all(
        module.values(key) == ["False"]
        for key in (
            "stagingEnabled",
            "stagingToggleEnabledEditor",
            "stagingToggleEnabledFlight",
        )
    )


def resources(part):
    return {one(r, "name"): float(one(r, "amount")) for r in part.children("RESOURCE")}


def key(piece):
    # The VAB appends a craft ID. Flight snapshots store the prefab name directly.
    identifier = one(piece, "part").rsplit("_", 1)[0] if piece.values("part") else one(piece, "name")
    return identifier.replace(".", "_")


def floats(value):
    return tuple(map(float, value.split(",")))


def verify_saturn_steering(part):
    kind = key(part)
    if kind == "famSaturnIITank":
        need(one(part, "autostrutMode") == "Root" and one(part, "rigidAttachment") == "True",
             "The supplied S-II tank must brace to the command section")
    if kind == "famSaturnIIMotor" and "ModuleGimbal" in modules(part):
        gimbal = modules(part)["ModuleGimbal"]
        need(float((gimbal.values("gimbalLimiter") or [100])[0]) >= 87.5
             and (gimbal.values("gimbalLock") or ["False"])[0].lower() == "false",
             "The supplied S-II must load with at least 3.5 degrees of usable gimbal travel")


def verify_columbia_hatch(nodes):
    capsule = PARTS["famApolloCM"]
    low, high = -capsule.height / 2 + 0.22, capsule.height / 2 - 0.16
    base = 0.995 * capsule.radius
    slope = (capsule.top_radius - base) / (high - low)
    facet = math.tau / 40
    exterior = next(n.shared_mesh for n in nodes if n.transform.name == "Exterior")
    relief = []
    for x, y, z in exterior.verts:
        azimuth = math.atan2(y, x)
        if -.33 < z < .32 and abs(math.atan2(x, -y)) < .52:
            radius = (base + slope * (z - low)) * math.cos(facet / 2) / math.cos(azimuth % facet - facet / 2)
            relief.append((z, math.hypot(x, y) - radius))
    need(relief and all(-.001 <= distance <= .040 for _, distance in relief)
         and all(any(a < z < b and distance >= .007 for z, distance in relief)
                 for a, b in ((-.33, -.20), (.04, .22), (.23, .31))),
         "Columbia's hatch and window must follow the cone over the full door height within 40 mm")
    normal = unit((0, -1, -slope))
    for name in ("Airlock", "Ladder"):
        trigger = next(n for n in nodes if n.transform.name == name).transform
        x, y, z = trigger.localPosition
        clearance = (-y - (base + slope * (z - low))) / math.hypot(1, slope)
        need(abs(x) < .02 and .10 <= clearance <= .25
             and dot(rotate(trigger.localRotation, (0, -1, 0)), normal) > .99,
             f"Columbia's {name} trigger must follow the sloping side hatch")


def check_model(cfg, root):
    pid = one(cfg, "name")
    model_path = root / "GameData" / (one(cfg.children("MODEL")[0], "model") + ".mu")
    model = Mu().read(model_path)
    need(model and model.version == 5, f"{pid} missing KSP model")
    if pid == "famIceCorer":
        need(
            one(cfg, "attachRules") == "0,1,0,0,0" and not cfg.values("node_stack_top"),
            "The sampler needs its own surface mount",
        )
        pad, _ = mount_samples(pid, model_path)
        need(
            abs(floats(one(cfg, "node_attach"))[2] - pad[0][2]) < 1e-4,
            "The sampler's node needs to be on the mounting face",
        )
    elif pid in PARTS and pid != "famJamestown":
        skin = mesh_triangles(model_path, ("Exterior", "interstage"))
        for side, sign in (("top", 1), ("bottom", -1)):
            x, height, z, dx, dy, dz, _ = floats(one(cfg, "node_stack_" + side))
            need(
                (x, z, dx, dy, dz) == (0, 0, 0, sign, 0)
                and any(abs(vertex[1] - height) < 0.015 for face in skin for vertex in face),
                f"{pid} {side} stack node needs a matching model plane",
            )
    nodes = list(objects(model.obj))
    if pid == "famApolloCM":
        verify_columbia_hatch(nodes)
    names = {n.transform.name for n in nodes}
    need(
        any(hasattr(n, "collider") and not n.collider.isTrigger for n in nodes),
        f"{pid} has no physical collider",
    )
    for texture in model.textures:
        path = model_path.parent / texture.name
        need(
            any(path.with_suffix(ext).is_file() for ext in (".png", ".dds", ".mbm", ".tga")),
            f"{pid} missing texture {texture.name}",
        )
    need(
        model.textures and model.materials and any(hasattr(n, "shared_mesh") for n in nodes),
        f"{pid} missing visible textured geometry",
    )
    for material in model.materials:
        need(
            material.shaderName == "KSP/Diffuse"
            and 0 <= material.textureProperties["_MainTex"].index < len(model.textures),
            f"{pid} has an invalid diffuse material",
        )
    for n in nodes:
        if not hasattr(n, "shared_mesh"):
            continue
        mesh = n.shared_mesh
        need(
            len(mesh.verts) == len(mesh.normals) == len(mesh.uvs) > 0,
            f"{pid} invalid mesh channels",
        )
        for submesh in mesh.submeshes:
            need(
                all(min(f) >= 0 and max(f) < len(mesh.verts) for f in submesh),
                f"{pid} invalid triangles",
            )
        need(
            all(0 <= m < len(model.materials) for m in n.renderer.materials),
            f"{pid} invalid material index",
        )
    m = modules(cfg)
    checks = (
        ("ModuleEnginesFX", "thrustVectorTransformName"),
        ("ModuleGimbal", "gimbalTransformName"),
        ("ModuleDockingNode", "nodeTransformName"),
        ("ModuleRCSFX", "thrusterTransformName"),
        ("ModuleDeployableSolarPanel", "raycastTransformName"),
        ("ModuleProceduralFairing", "BaseModelTransformName"),
        ("ModuleJettison", "jettisonName"),
    )
    for kind, field in checks:
        for module in cfg.children("MODULE"):
            if one(module, "name") == kind:
                need(one(module, field) in names, f"{pid} missing {field}")
    parents = {id(child): parent for parent in nodes for child in parent.children}
    for n in nodes:
        if n.transform.name in ("thrustTransform", "dockingNode"):
            forward = (0, 1, 0)
            ancestor = n
            while ancestor is not None:
                forward = rotate(ancestor.transform.localRotation, forward)
                ancestor = parents.get(id(ancestor))
            sign = -1 if n.transform.name == "thrustTransform" else 1
            need(
                forward[2] * sign > 0.999,
                f"{pid} incorrect axial transform {n.transform.name}",
            )
    if "ModuleCommand" in m:
        for tag in ("Airlock", "Ladder"):
            need(
                any(
                    n.tag_and_layer.tag == tag and n.tag_and_layer.layer == 21 and n.collider.isTrigger
                    for n in nodes
                ),
                f"{pid} lacks a usable {tag}",
            )
        directions = [
            rotate(n.transform.localRotation, (0, 0, 1)) for n in nodes if n.transform.name == "rcsJet"
        ]
        need(
            len(directions) == 12
            and all(
                any(d[axis] > 0.5 for d in directions) and any(d[axis] < -0.5 for d in directions)
                for axis in range(3)
            ),
            f"{pid} needs RCS in both directions of every axis",
        )
    if pid in ("famLMDescentFrame", "famLSAMDriveFrame", "famLKPlatformFrame"):
        need(
            sum(
                n.transform.name.startswith("Foot") and hasattr(n, "collider") and not n.collider.isTrigger
                for n in nodes
            )
            == 4,
            f"{pid} needs four solid landing feet",
        )
    nozzles = [n.transform.localPosition for n in nodes if n.transform.name == "thrustTransform"]
    if pid == "famHabCradle":
        bell_z = -PARTS[pid].height / 2 + HAB_BELL_CLEARANCE
        layout = [(x, y, bell_z) for x in (-HAB_BELL_X, HAB_BELL_X) for y in (-HAB_BELL_Z, HAB_BELL_Z)]
        need(
            len(nozzles) == 4 and all(math.dist(a, b) < 1e-4 for a, b in zip(sorted(nozzles), layout)),
            "Jamestown's four nozzle exits must match the tank pods and sit above the feet",
        )
    return len(nozzles)


def verify_part_systems(part, game):
    pid = one(part, "name")
    fitted = modules(part)
    tanks = resources(part)
    if pid == "famLaunchTower":
        need(
            skips_staging(fitted["ModuleEnginesFX"])
            and one(fitted["FAMStagePolicy"], "manualIgnition") == "True",
            f"{pid} needs manual engine ignition, with staging disabled",
        )
    if pid in ("famApolloSMMotor", "famLOKServiceMotor"):
        policy = fitted["FAMStagePolicy"]
        need(
            fitted["ModuleEnginesFX"].values("stagingEnabled") != ["False"]
            and one(policy, "stageServiceEngine") == "True"
            and policy.values("manualIgnition") != ["True"],
            f"{pid} needs a stageable engine for the stock delta-v readout",
        )
    if "ModuleJettison" in fitted:
        shroud = fitted["ModuleJettison"]
        need(
            skips_staging(shroud) and one(shroud, "checkBottomNode") == "True" and "FAMStagePolicy" in fitted,
            f"{pid} needs an automatic shroud outside the staging stack",
        )
    for tank in part.children("RESOURCE"):
        need(
            0 <= float(one(tank, "amount")) <= float(one(tank, "maxAmount")),
            f"{pid} invalid tank fill",
        )
    if "ModuleEnginesFX" in fitted:
        engine = fitted["ModuleEnginesFX"]
        exhaust = one(engine, "runningEffectName")
        need(
            any(e.children(exhaust) for e in part.children("EFFECTS")),
            f"{pid} has no engine effect",
        )
        fuels = engine.children("PROPELLANT")
        need(
            fuels and all((pid.endswith("Motor") or tanks.get(one(f, "name"), 0) > 0) and float(one(f, "ratio")) > 0 for f in fuels),
            f"{pid} lacks its own engine propellant",
        )
        isp = engine.children("atmosphereCurve")[0].values("key")
        need(
            float(one(engine, "maxThrust")) > 0 and all(float(k.split()[1]) > 0 for k in isp),
            f"{pid} needs thrust and a valid Isp curve",
        )
    if "ModuleDecouple" in fitted:
        need(
            part.values("sound_decoupler_fire") == ["decouple"]
            and any(v.endswith(", decouple") for v in part.values("fx_gasBurst_white")),
            f"{pid} needs a separation effect group",
        )
    if "ModuleCommand" in fitted:
        controls = {
            "ModuleReactionWheel",
            "ModuleRCSFX",
            "ModuleDataTransmitter",
            "ModuleDockingNode",
            "ModuleScienceContainer",
            "ModuleInventoryPart",
        }
        if pid in ("famJamestown", "famJamestownAirlock"):
            controls.remove("ModuleDockingNode")
        if pid == "famJamestownAirlock":
            controls -= {"ModuleScienceContainer", "ModuleInventoryPart"}
        need(
            controls <= fitted.keys()
            and tanks.get("ElectricCharge", 0) > 0
            and tanks.get("MonoPropellant", 0) > 0,
            f"{pid} missing cabin systems or supplies",
        )
        docking = fitted.get("ModuleDockingNode")
        need(
            docking is None or (one(docking, "nodeType") == "size1"
            and part.values("node_stack_" + one(docking, "referenceAttachNode"))),
            f"{pid} missing stock-compatible docking hardware",
        )
        need(
            one(fitted["ModuleCommand"], "minimumCrew") == ("0" if pid in ("famJamestown", "famJamestownAirlock") else "1"),
            f"{pid} has an incorrect crew requirement",
        )
        rcs = fitted["ModuleRCSFX"]
        need(
            one(rcs, "resourceName") == "MonoPropellant"
            and any(e.children(one(rcs, "runningEffectName")) for e in part.children("EFFECTS")),
            f"{pid} needs working RCS propellant and effects",
        )
    if pid in ("famApolloCM", "famLOK"):
        ablator = fitted["ModuleAblator"]
        skin_limit = float(one(part, "skinMaxTemp"))
        internal_limit = float(one(part, "maxTemp"))
        need(
            tanks.get(one(ablator, "ablativeResource"), 0) > 0
            and float(one(ablator, "ablationTempThresh")) < internal_limit < skin_limit
            and float(one(ablator, "pyrolysisLossFactor")) > 0,
            f"{pid} missing reentry protection",
        )
        need(
            floats(one(part, "CoMOffset"))[1] < 0 < floats(one(part, "CoPOffset"))[1]
            and one(part, "bodyLiftOnlyAttachName") == "bottom",
            f"{pid} needs the shield-first balance for its detached cabin",
        )
        if game:
            stock_path = game / "GameData/Squad/Parts/Aero/HeatShield/HeatShield2.cfg"
            stock_limit = float(one(read_node(stock_path).children("PART")[0], "maxTemp"))
            need(
                skin_limit >= stock_limit,
                f"{pid} shield skin limit is below the stock heat shield",
            )
    if pid == "famLSAMCab":
        panel = fitted["ModuleDeployableSolarPanel"]
        need(
            one(panel, "resourceName") == "ElectricCharge" and float(one(panel, "chargeRate")) > 0,
            f"{pid} missing solar power",
        )
    if pid == "famJamestown":
        cell = fitted["ModuleResourceConverter"]
        need(
            "ModuleSAS" in fitted
            and {one(n, "ResourceName") for n in cell.children("INPUT_RESOURCE")}
            == {"LiquidFuel", "Oxidizer"}
            and [one(n, "ResourceName") for n in cell.children("OUTPUT_RESOURCE")] == ["ElectricCharge"],
            "Jamestown requires probe stability and a fuel cell",
        )
    if game:
        data = game / "GameData"
        for node in descendants(part):
            for fx in node.values("modelName"):
                need(
                    (data / (fx + ".mu")).is_file(),
                    f"{pid} missing base-game effect {fx}",
                )
            for field in ("TextureURL", "CapTextureURL", "TextureNormalURL"):
                for texture in node.values(field):
                    need(
                        any((data / (texture + ext)).is_file() for ext in (".dds", ".png", ".mbm")),
                        f"{pid} missing base-game texture {texture}",
                    )
        for iva in part.children("INTERNAL"):
            path = data / "Squad/Spaces" / one(iva, "name") / "internal.cfg"
            interior = read_node(path).children("INTERNAL")[0]
            seats = [m for m in interior.children("MODULE") if m.values("name") == ["InternalSeat"]]
            need(
                len(seats) >= int(one(part, "CrewCapacity")),
                f"{pid} missing cabin seats",
            )


def verify_tree(root, parts, game):
    node = read_node(root / "GameData/FAMSeasons/Season1/Research/TechTree.cfg").children(
        "@TechTree:FOR[FAMSeasons]"
    )[0]
    techs = {one(n, "id"): n for n in node.children("RDNode")}
    need(
        len(techs) == 6 and set(techs) == {one(p, "TechRequired") for p in parts.values()},
        "Season 1 research coverage",
    )
    seen = {"heavyRocketry"}
    while pending := set(techs) - seen:
        accessible = {t for t in pending if {one(p, "parentID") for p in techs[t].children("Parent")} <= seen}
        need(accessible, f"Unreachable research nodes {pending}")
        seen.update(accessible)
    need(
        {one(n, "parentID") for n in techs["famPolarSurvey"].children("Parent")} == {"famApollo"},
        "The American survey branch must follow Apollo Lunar Systems",
    )
    costs = {t: int(one(n, "cost")) for t, n in techs.items()}
    if game:
        stock = (
            read_node(game / "GameData/Squad/Resources/TechTree.cfg")
            .children("TechTree")[0]
            .children("RDNode")
        )
        need("heavyRocketry" in {one(n, "id") for n in stock}, "Stock anchor missing")
        icons = {one(n, "icon") for n in stock}
        positions = [floats(one(n, "pos")) for n in stock]
        for n in techs.values():
            need(one(n, "icon") in icons, "Undefined R&D icon: " + one(n, "icon"))
            pos = floats(one(n, "pos"))
            need(
                all(math.dist(pos, other) > 65 for other in positions),
                "Overlapping R&D nodes",
            )
            positions.append(pos)
    return costs


def stock_chute(game):
    if game:
        return read_node(game / "GameData/Squad/Parts/Utility/parachuteMk2-R/parachuteMk2-R.cfg").children(
            "PART"
        )[0]
    # Values from the base-game 1.12.5 Mk2-R.
    return Node(
        "PART",
        name="parachuteRadial",
        mass=0.1,
        cost=400,
        TechRequired="survivability",
        node_attach="0,0,0,0,0,-1",
    )


def stock_fixtures(game):
    squad = game / "GameData/Squad/Parts" if game else None
    fittings = {}
    for name, spec in HAB_FIXTURES.items():
        if squad:
            cfg = read_node(squad / spec.config).children("PART")[0]
            need(
                one(cfg, "name") == name and floats(one(cfg, "node_attach"))[:3] == spec.attach,
                f"{name} stock attachment differs from the Jamestown fixture",
            )
        else:
            cfg = Node("PART", name=name, mass=spec.mass, cost=spec.cost)
        fittings[name] = cfg
    return fittings


def stock_mesh(path):
    names = tuple(n.transform.name for n in objects(Mu().read(path).obj) if hasattr(n, "shared_mesh"))
    return mesh_triangles(path, names, discard_root_pose=True)


def part_mesh(data, name):
    return mesh_triangles(data / f"FAMSeasons/Season1/Parts/{name}.mu", ("Exterior",))


def verify_jamestown_fixture(data, game, host, hpose, child, cpose):
    spec = HAB_FIXTURES[child]
    anchor = local_direction(hpose[1], minus(world_point(*cpose, spec.attach), hpose[0]))
    need(
        host == "famJamestown" and math.dist(anchor, spec.position) < 1e-4,
        f"{child} must rest on its Jamestown fitting",
    )
    rotation = cpose[1]
    for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
        mounted_axis = local_direction(hpose[1], world_direction(rotation, axis))
        need(
            dot(mounted_axis, world_direction(spec.rotation, axis)) > 0.999,
            f"{child} has turned off its mounting plane",
        )
    shell = part_mesh(data, host)
    for position in (anchor, add(anchor, (0.08, 0, 0)), add(anchor, (-0.08, 0, 0))):
        need(
            abs(surface_offset(shell, position, spec.outward)) < 0.02,
            f"{child} mount needs a level backing plate",
        )


def verify_payload_clearance(pieces, data, game):
    adapter = next(p for p in pieces if key(p) in ("famPayloadAdapter", "famJamestownCargoAdapter"))
    origin = craft_pose(adapter)[0][1] - 0.33
    fairing = modules(adapter)["ModuleProceduralFairing"]
    sections = [(float(one(s, "h")), float(one(s, "r"))) for s in fairing.children("XSECTION")]
    interstage = one(fairing, "interstageCraftID")
    first = 0
    if interstage != "0":
        # The fairing meets the service section above the release ring.
        service = next(p for p in pieces if one(p, "part").rsplit("_", 1)[1] == interstage)
        first = pieces.index(service) + 3
    jamestown = key(pieces[0]) == "famJamestown"
    ground = -(PARTS["famJamestown"].height / 2 + PARTS["famHabCradle"].height)
    habitat_pose = craft_pose(pieces[0])
    for part in pieces[first : pieces.index(adapter)]:
        name = key(part)
        if name in HAB_FIXTURES:
            if game is None:
                continue
            mesh = stock_mesh(game / "GameData/Squad/Parts" / HAB_FIXTURES[name].model)
        else:
            mesh = part_mesh(data, name)
        vertices = {world_point(*craft_pose(part), v) for face in mesh for v in face}
        for x, y, z in vertices:
            height = y - origin
            segment = next(
                ((a, r, b, s) for (a, r), (b, s) in zip(sections, sections[1:]) if a <= height <= b), None
            )
            need(segment is not None, f"{name} projects past the delivery fairing")
            a, r, b, s = segment
            radius = r + (s - r) * (height - a) / (b - a)
            need(math.hypot(x, z) < radius - 0.025, f"{name} intersects the delivery fairing")
            if not jamestown:
                continue
            local = local_direction(habitat_pose[1], minus((x, y, z), habitat_pose[0]))
            lx, ly, lz = local
            need(ly >= ground - 1e-4, f"{name} extends past the landing feet")
            need(
                abs(lx) <= HAB_PORT_X + 1e-4 or math.hypot(ly - HAB_PORT_Y, lz) > 1.0,
                f"{name} blocks a horizontal docking approach",
            )


def verify_expansion_ports(base, data, game):
    model = Mu().read(data / "FAMSeasons/Season1/Parts/famJamestown.mu")
    nodes = {n.transform.name: n.transform for n in objects(model.obj)}
    docks = [m for m in base.children("MODULE") if one(m, "name") == "ModuleDockingNode"]
    expected = ["top", *(side for side, _ in HAB_PORTS)]
    need(
        [one(m, "referenceAttachNode") for m in docks] == expected,
        "Keep the original roof port and both expansion ports",
    )
    for (side, sign), dock in zip(HAB_PORTS, docks[1:]):
        position = (sign * HAB_PORT_X, HAB_PORT_Y, 0)
        direction = (sign, 0, 0)
        transform = nodes[one(dock, "nodeTransformName")]
        x, z, y = transform.localPosition
        nx, nz, ny = rotate(transform.localRotation, (0, 1, 0))
        stack = floats(one(base, "node_stack_" + side))
        need(
            math.dist((x, y, z), position) < 1e-4
            and dot((nx, ny, nz), direction) > 0.999
            and stack == (*position, *direction, 1)
            and one(dock, "nodeType") == "size1",
            f"{side} expansion port needs the standard pose and Clamp-O-Tron type",
        )
    if game:
        clamp = read_node(game / "GameData/Squad/Parts/Utility/dockingPort/dockingPort.cfg").children("PART")[
            0
        ]
        need(
            one(modules(clamp)["ModuleDockingNode"], "nodeType") == "size1",
            "Stock expansion port is incompatible",
        )


def verify_stack_join(parts, a, aside, apose, b, bside, bpose):
    na = floats(one(parts[a], "node_stack_" + aside))
    nb = floats(one(parts[b], "node_stack_" + bside))
    pa, pb = world_point(*apose, na[:3]), world_point(*bpose, nb[:3])
    da, db = world_direction(apose[1], na[3:6]), world_direction(bpose[1], nb[3:6])
    need(math.dist(pa, pb) < 1e-4 and dot(da, db) < -0.999, f"Detached stack geometry between {a} and {b}")


def verify_surface_mount(parts, data, game, host, hpose, child, cpose):
    if child not in ("parachuteRadial", "famIceCorer"):
        # Stock fittings and fin mounting poses are checked against the authored modular assembly.
        return

    def relative_point(vertex):
        return local_direction(hpose[1], minus(world_point(*cpose, vertex), hpose[0]))

    node = floats(one(parts[child], "node_attach"))
    outward = unit(local_direction(hpose[1], world_direction(cpose[1], node[3:6])))
    anchor = relative_point(node[:3])
    need(dot(outward, unit((anchor[0], 0, anchor[2]))) > 0.72, f"{child} faces into {host}")
    host_path = data / (one(parts[host].children("MODEL")[0], "model") + ".mu")
    if child == "parachuteRadial":
        model_path = game / "GameData" / STOCK_CHUTE / "model.mu" if game else None
    else:
        model_path = data / (one(parts[child].children("MODEL")[0], "model") + ".mu")
    skin = mesh_triangles(host_path, ("Exterior",))
    plate, cover = mount_samples(child, model_path)
    center = tuple(sum(sample[i] for sample in plate) / len(plate) for i in range(3))
    seating = [surface_offset(skin, relative_point(sample), outward) for sample in (*plate, center)]
    need(
        min(seating) >= -0.012 and max(seating) <= 0.14 and min(abs(depth) for depth in seating) < 0.025,
        f"{child} has a floating or buried mount on {host}",
    )
    clearance = [-surface_offset(skin, relative_point(point), outward) for point in cover]
    need(min(clearance) >= 0.025, f"{child} cover intersects {host}")


def verify_assembly(ship, parts, data, game):
    pieces = ship.children("PART")
    ids = {one(n, "part"): n for n in pieces}
    need(len(ids) == len(pieces), "Duplicate craft part identity")
    parents = {}
    for ident, n in ids.items():
        need(key(n) in parts, "Missing craft part " + ident)
        for child in n.values("link"):
            need(
                child in ids and child not in parents,
                "Broken or duplicate craft link " + child,
            )
            parents[child] = ident
        for connection in n.values("attN"):
            name, rest = connection.split(",", 1)
            other, encoded = rest.rsplit("_", 1)
            need(other in ids, "Unknown attachment " + other)
            opposite = next((a.split(",")[0] for a in ids[other].values("attN") if a.split(",")[1].rsplit("_", 1)[0] == ident), None)
            need(
                opposite is not None,
                "Attachment is not reciprocal: " + connection,
            )
            local = floats(one(parts[key(n)], "node_stack_" + name))[:3]
            need(
                math.dist(local, tuple(float(v) for v in encoded.split("|"))) < 1e-4,
                "Stale attachment offset",
            )
            verify_stack_join(
                parts, key(n), name, craft_pose(n), key(ids[other]), opposite, craft_pose(ids[other])
            )
        for srf in n.values("srfN"):
            need(srf.split(",")[1] in ids, "Missing surface-attachment parent")
    root_id = one(pieces[0], "part")
    need(
        root_id not in parents and len(parents) == len(pieces) - 1,
        "Invalid craft parent tree",
    )
    for ident, part in ids.items():
        walk = set()
        current = ident
        while current in parents:
            need(current not in walk, "Cyclic craft graph")
            walk.add(current)
            current = parents[current]
        need(current == root_id, "Disconnected craft")
        if part.values("srfN"):
            _, mount = one(part, "srfN").split(",")
            need(parents[ident] == mount, "Surface mount parent disagrees with craft tree")
            verify_surface_mount(
                parts,
                data,
                game,
                key(ids[mount]),
                craft_pose(ids[mount]),
                key(part),
                craft_pose(part),
            )
    return pieces


def craft_pose(part):
    return floats(one(part, "pos")), floats(one(part, "rot"))


def wet_mass(piece, parts):
    return (
        float(one(parts[key(piece)], "mass"))
        + float(one(piece, "modMass"))
        + sum(n * DENSITY[r] for r, n in resources(piece).items())
    )


def flight_mass(piece, parts, physics):
    cfg = parts[key(piece)]
    mass = wet_mass(piece, parts)
    seats = int((cfg.values("CrewCapacity") or [0])[0])
    if seats:
        factor = "perCommandSeatReduction" if "ModuleCommand" in modules(cfg) else "perSeatReduction"
        mass -= seats * float(one(physics, factor))
    for robot in cfg.children("MODULE"):
        if robot.values("motorizedMassPerKN"):
            mass += float(one(robot, "motorizedMassPerKN")) * float(one(robot, "maxMotorOutput"))
    return mass


def engine_data(piece, parts):
    cfg = parts[key(piece)]
    engine = modules(cfg)["ModuleEnginesFX"]
    curve = {
        float(x.split()[0]): float(x.split()[1]) for x in engine.children("atmosphereCurve")[0].values("key")
    }
    return float(one(engine, "maxThrust")), curve[0], curve[1]


def available_fuel(piece):
    r = resources(piece)
    return min(r.get("LiquidFuel", 0) / 90, r.get("Oxidizer", 0) / 110)


def verify_staging(ship, pieces, parts):
    title = one(ship, "ship")
    capsule = key(pieces[0])
    saturn = {6: {"famSaturnIC"}, 5: {"famSaturnII"}, 4: {"famSaturnIVB"}}
    expected = {
        "famLOK": {
            7: {"famN1A"},
            6: {"famN1B"},
            5: {"famN1V"},
            4: {"famBlockG"},
            3: {"famLOKService", "famLKPlatform"},
            2: {"famLK"},
        },
        "famApolloCM": {**saturn, 3: {"famApolloSM", "famLMDescent"}, 2: {"famLMAscent"}},
        "famJamestown": {**saturn, 3: {"famHabCradle"}},
        "famLSAMCab": {**saturn, 3: {"famLSAMDrive"}},
    }
    ignition = defaultdict(set)
    for piece in pieces:
        ident = key(piece)
        prefab = modules(parts[ident]).get("ModuleEnginesFX")
        if prefab:
            stored = modules(piece).get("ModuleEnginesFX", prefab)
            if stored.values("stagingEnabled") != ["False"]:
                stage = int(one(piece, "istg"))
                need(stage >= 0, f"{title} has an unstaged engine {ident}")
                ignition[stage].add(ident)
    need(ignition == {stage: {("liquidEngineMini_v2" if k == "famHabCradle" else k if k in ("famLK", "famLMAscent") else k + "Motor") for k in motors}
                      for stage, motors in expected[capsule].items()}, f"{title} has an incorrect engine stage order")
    release = next(p for p in pieces if key(p) in ("famPayloadAdapter", "famJamestownCargoAdapter"))
    need(
        one(release, "istg") == "3"
        and one(modules(release)["ModuleProceduralFairing"], "stagingEnabled") == "True"
        and "ModuleDecouple" in modules(parts[key(release)]),
        f"{title} has no stage 3 payload release",
    )
    if capsule not in ("famLOK", "famApolloCM"):
        need(
            not any(key(p) == "famLaunchTower" for p in pieces),
            f"{title} has an unexpected escape tower",
        )
        return
    root_id = one(pieces[0], "part")
    tower = next(p for p in pieces if key(p) == "famLaunchTower")
    tower_motor = modules(tower)["ModuleEnginesFX"]
    abort = tower_motor.children("ACTIONS")[0].children("ActivateAction")[0]
    need(
        one(tower_motor, "stagingEnabled") == "False"
        and one(abort, "actionGroup") == "Abort"
        and one(tower, "istg") == ("6" if capsule == "famLOK" else "5")
        and one(modules(parts["famLaunchTower"])["ModuleDecouple"], "explosiveNodeID") == "bottom",
        f"{title} must discard the tower without firing its escape motor during normal staging",
    )
    chutes = [p for p in pieces if key(p) == "parachuteRadial"]
    need(
        len(chutes) == 2
        and [p for p in pieces if one(p, "istg") == "0"] == chutes
        and all(one(p, "istg") == "0" and one(p, "srfN") == "srfAttach," + root_id for p in chutes),
        f"{title} needs two chutes on the return capsule at stage 0",
    )
    separator = next(n for n in pieces[0].values("attN") if n.startswith("bottom,"))
    service_ring = next(p for p in pieces if one(p, "part") == separator.split(",")[1].rsplit("_", 1)[0])
    need(
        key(service_ring) == ("famRing125" if capsule == "famLOK" else "famRing250")
        and one(service_ring, "istg") == "1"
        and one(
            modules(service_ring)["ModuleDecouple"].children("ACTIONS")[0].children("DecoupleAction")[0],
            "actionGroup",
        )
        == "Abort",
        f"{title} needs an independent stage 1 service release",
    )
    service = next(p for p in pieces if key(p) in ("famLOKServiceMotor", "famApolloSMMotor"))
    need(
        one(service, "istg") == one(release, "istg") and int(one(service, "sidx")) >= 0,
        f"{title} must arm the service engine at payload release, ahead of recovery",
    )
    ascent = "famLK" if capsule == "famLOK" else "famLMAscent"
    lander = next(p for p in pieces if key(p) == ascent)
    deck_ring = next(p for p in pieces if one(p, "part") in lander.values("link"))
    need(
        key(deck_ring) == "famRing125" and one(deck_ring, "istg") == "2",
        f"{title} must release its landing deck at ascent",
    )


def flight_budget(ship, pieces, parts, physics):
    title = one(ship, "ship")
    mass = sum(flight_mass(p, parts, physics) for p in pieces)
    crew_allowance = {
        "famLOK": 0.20,
        "famApolloCM": 0.30,
        "famLSAMCab": 0.30,
        "famJamestown": 0,
    }[key(pieces[0])]
    mass += crew_allowance
    price = math.ceil(sum(float(one(parts[key(p)], "cost")) + float(one(p, "modCost")) for p in pieces))
    need(mass <= 140 and len(pieces) <= (255 if key(pieces[0]) == "famJamestown" else 30),
         f"{title} exceeds its contract facility limits")
    remaining, orbital_dv = mass, 0
    ids = {one(p, "part"): p for p in pieces}
    motors = sorted((p for p in pieces if key(p).endswith("Motor") and int(one(p, "istg")) >= 4),
                    key=lambda p: int(one(p, "istg")), reverse=True)
    need(len(motors) == (4 if key(pieces[0]) == "famLOK" else 3), "Incomplete launcher")
    for i, motor in enumerate(motors):
        tank = next(p for p in pieces if one(motor, "part") in p.values("link"))
        ring = next(p for p in pieces if one(tank, "part") in p.values("link"))
        need("ModuleDecouple" in modules(parts[key(ring)]) and int(one(ring, "istg")) == int(one(motor, "istg")) - 1,
             f"{title} invalid separation above {key(motor)}")
        thrust, vac, sea = engine_data(motor, parts)
        if i == 0:
            twr = thrust * sea / vac / (mass * G0)
            need(1.25 < twr < 1.65, f"{title} invalid liftoff TWR")
        fuel = available_fuel(tank)
        need(fuel > 0, f"{key(motor)} has no attached fuel")
        orbital_dv += (sea if i == 0 else vac) * G0 * math.log(remaining / (remaining - fuel))
        thrown = [ring, tank, motor, *(ids[child] for child in motor.values("link") if one(ids[child], "attm") == "1")]
        remaining -= sum(flight_mass(p, parts, physics) for p in thrown)
    need(
        4800 <= orbital_dv <= 5750,
        f"{title} Mun insertion budget out of range: {orbital_dv:.0f}",
    )
    return title, (len(pieces), mass, twr, orbital_dv, price)


def surface_budgets(ships, parts, physics):
    totals = {}
    for ship in ships:
        pieces = ship.children("PART")
        by_id = {key(p): p for p in pieces}
        for motor, payload, kerbals, minimum, maximum in [
            ("famLKPlatform", ["famLK", "famRing125"], 1, 950, 1250),
            ("famLK", [], 1, 850, 1150),
            ("famLMDescent", ["famLMAscent", "famRing125"], 2, 950, 1250),
            ("famLMAscent", [], 2, 850, 1150),
            ("famHabCradle", ["famJamestown"], 0, 950, 1250),
            ("famLSAMDrive", ["famLSAMCab", "famRescueTank"], 3, 2250, 2600),
            ("famApolloSM", ["famApolloCM", "famRing250"], 3, 850, 1150),
            ("famLOKService", ["famLOK", "famRing125"], 2, 850, 1150),
        ]:
            if motor == "famHabCradle":
                continue  # Four Sparks and all stock/DLC fittings are budgeted in check_jamestown_budget.
            if motor + "Motor" in by_id:
                stage = by_id[motor + "Motor"]
                hardware = [p for name, p in by_id.items() if name.startswith(motor)]
            elif motor in by_id:
                stage = by_id[motor]
                hardware = [stage]
            else:
                continue
            wet = sum(flight_mass(p, parts, physics) for p in hardware + [by_id[k] for k in payload]) + kerbals * 0.1
            if motor == "famHabCradle":
                wet += sum(wet_mass(by_id[name], parts) for name in HAB_FIXTURES)
            if motor in ("famApolloSM", "famLOKService"):
                wet += sum(wet_mass(p, parts) for p in pieces if key(p) == "parachuteRadial")
            fuel = sum(available_fuel(p) for p in hardware)
            if motor == "famLSAMDrive":
                fuel += available_fuel(by_id["famRescueTank"]) - 0.2  # leave the rescue donation untouched
            thrust, vac, _ = engine_data(stage, parts)
            dv = vac * G0 * math.log(wet / (wet - fuel))
            need(
                minimum <= dv <= maximum and thrust / (wet * 1.63) > 1.5,
                f"{motor} fails its flight budget",
            )
            totals[motor] = round(dv)
            if motor == "famLSAMDrive":
                remaining = 2.0  # 180 LiquidFuel plus 220 Oxidizer at the First Crew parking milestone.
                dry = wet - fuel - 0.2
                descent = vac * G0 * math.log(wet / (dry + remaining))
                rescue = vac * G0 * math.log((dry + remaining) / (dry + 0.2))
                need(
                    descent >= 780 and rescue >= 1680,
                    "LSAM parking reserve does not support the rescue",
                )
                totals["LSAM descent before parking reserve"] = round(descent)
                totals["LSAM rescue at parking reserve"] = round(rescue)
    return totals


def verify_campaign(root, parts, costs, budgets, game):
    data = root / "GameData"
    folder = data / "FAMSeasons/Season1/Contracts"
    contracts = [read_node(p).children("CONTRACT_TYPE")[0] for p in sorted(folder.glob("[0-9]*.cfg"))]
    group = read_node(folder / "Group.cfg").children("CONTRACT_GROUP")[0]
    need(
        one(group, "name") == GROUP
        and [one(child, "name") for child in group.children("CONTRACT_GROUP")] == [SOVIET, AMERICAN],
        "Separate the Soviet and American programs in Mission Control",
    )
    need(
        [one(c, "name") for c in contracts] == ["FAMS1RedMun", "FAMS1Apollo11", "FAMS1JamestownCampaign"],
        "Expected three Season 1 missions",
    )
    site = set()
    for i, c in enumerate(contracts):
        need(
            one(c, "group") == (SOVIET if i == 0 else AMERICAN) and one(c, "maxCompletions") == "1",
            "Contract program/completion count",
        )
        parents = [
            one(n, "contractType") for n in c.children("REQUIREMENT") if one(n, "type") == "CompleteContract"
        ]
        need(parents == ([] if i == 0 else [one(contracts[i-1], "name")]), "Broken program progression")
        for n in descendants(c):
            if n.kind == "PARAMETER" and n.values("type") == ["PartValidation"]:
                need(one(n, "part") in parts, "Unknown contract part")
            if n.kind == "WAYPOINT":
                site.add((one(n, "latitude"), one(n, "longitude"), one(n, "targetBody")))
            for craft in n.values("craftURL"):
                target_parts = verify_assembly(read_node(data / craft), parts, data, game)
                need(all(available_fuel(p) == 0 for p in target_parts), "Osprey's tanks must start empty")
                need(
                    any("ModuleDockingNode" in modules(parts[key(p)]) for p in target_parts),
                    "Osprey needs a port",
                )
        craft_names = [
            ("N1-L3",),
            ("Saturn V Apollo",),
            ("Apollo 15 Survey", "Jamestown Delivery", "LSAM Delivery"),
        ][i]
        manifests = {key(part).replace("_", ".") for name in craft_names
                     for part in read_node(root / "Ships/VAB" / ("FAM S1 - " + name + ".craft")).children("PART")}
        gate = [n for n in c.children("REQUIREMENT") if one(n, "type") == "PartUnlocked"]
        need(len(gate) == 1 and sorted(gate[0].values("part")) == sorted(manifests), "Mission must require every reference part")
        facilities = {one(n, "facility"): one(n, "minLevel") for n in c.children("REQUIREMENT") if one(n, "type") == "Facility"}
        need((i != 2 or facilities.get("VehicleAssemblyBuilding") == "2") and facilities.get("LaunchPad") == "2",
             "Mission must unlock the facilities needed to build the fleet")
        price = sum(budgets["FAM S1 - " + name][-1] for name in craft_names)
        if i != 2:
            need(
                any(n.values("type") == ["NewVessel"] for n in descendants(c.children("PARAMETER")[0])),
                "Each lunar mission needs a launch objective",
            )
        need(price <= float(one(c, "advanceFunds")), "Reference builds exceed the contract advance")
    need(
        sum(costs[t] for t in (POLAR, HAB, LOGISTICS)) <= int(one(contracts[1], "rewardScience")),
        "Apollo 11 must fund the combined Jamestown research",
    )
    need(site == {("-77.0", "12.0", "Mun")}, "Inconsistent survey coordinates")
    final = contracts[-1]
    sequence = final.children("PARAMETER")[0]
    tasks = sequence.children("PARAMETER")
    need(
        one(sequence, "type") == "Sequence"
        and [one(task, "name") for task in tasks]
        == [
            "Drill",
            "CoreRecover",
            "LandBase",
            "ParkFerry",
            "StaffBase",
            "Intercept",
            "DockOsprey",
            "VerifyTransfer",
            "LandSurvivor",
            "SafeInside",
        ]
        and sequence.values("hiddenParameter") == [one(task, "name") for task in tasks[1:]],
        "Jamestown needs a single ordered campaign",
    )
    need(
        one(tasks[2], "define") == one(tasks[4], "vessel") == one(tasks[9], "vessel")
        and one(tasks[3], "define") == one(tasks[5], "vessel") == one(tasks[8], "vessel"),
        "Career must track the same habitat and LSAM through rescue",
    )
    occupancy = [n for n in descendants(final) if n.values("type") == ["FAMHabitat"]]
    need(
        len(occupancy) == 3
        and one(occupancy[1], "minimumOccupants") == "1"
        and one(occupancy[2], "occupant") == "@/survivor",
        "Missing upright or designated occupant check",
    )
    science = read_node(data / "FAMSeasons/Season1/Research/ScienceDefs.cfg").children(
        "EXPERIMENT_DEFINITION"
    )[0]
    experiment = one(science, "id")
    drill = modules(parts["famIceCorer"])["ModuleScienceExperiment"]
    research = [n for n in descendants(final) if n.values("type") == ["CollectScience"]]
    need(
        one(drill, "experimentID") == experiment
        and one(drill, "xmitDataScalar") == "0"
        and [one(n, "recoveryMethod") for n in research] == ["None", "Recover"]
        and all(one(n, "experiment") == experiment and one(n, "biome") == "Polar Crater" for n in research),
        "Survey must recover its physical polar core",
    )
    spawn = next(x for x in final.children("BEHAVIOUR") if one(x, "type") == "SpawnVessel").children(
        "VESSEL"
    )[0]
    orbit = spawn.children("ORBIT")[0]
    need(
        one(spawn.children("CREW")[0], "name") == "@/survivor"
        and one(final.children("DATA")[0], "survivor") == "NewKerbal(Female)",
        "Mismatched rescue crew",
    )
    sma, ecc = float(one(orbit, "SMA")), float(one(orbit, "ECC"))
    need(
        sma * (1 - ecc) > 210000 and sma * (1 + ecc) < 2400000 and one(orbit, "INC") == "90",
        "Unsafe rescue target orbit",
    )
    return len(contracts)


def verify_scenarios(root, parts, game):
    folder = root / SCENARIOS.relative_to(ROOT)
    data = root / "GameData"
    expected = {scenario.filename: scenario for scenario in scenarios()}
    files = {p.stem: p for p in folder.glob("FAM S1.*.sfs")}
    need(files.keys() == expected.keys(), "Expected three complete Season 1 scenarios")
    if game:
        cargo = game / "GameData/Squad/Parts/Cargo"
        chute = read_node(cargo / "Parachute/Parachute.cfg").children("PART")[0]
        pack = read_node(cargo / "Jetpack/Jetpack.cfg").children("PART")[0]
        need(one(chute, "name") == "evaChute" and one(pack, "name") == "evaJetpack", "Missing stock EVA gear")
    for title, authored in expected.items():
        scene = read_node(files[title]).children("GAME")[0]
        need(
            one(scene, "Mode") == "SCENARIO" and one(scene, "scene") == "7" and one(scene, "Title") == title,
            "Wrong scenario header",
        )
        settings = scene.children("PARAMETERS")[0].children("FLIGHT")[0]
        need(
            all(
                one(settings, n) == "True"
                for n in ("CanQuickSave", "CanQuickLoad", "CanRestart", "CanSwitchVesselsFar")
            ),
            "Scenario needs save, resume, and map switching",
        )
        banner = (folder / "banners" / (title + ".png")).read_bytes()
        need(
            banner.startswith(b"\x89PNG\r\n\x1a\n") and struct.unpack_from(">II", banner, 16) == (322, 120),
            f"Invalid menu banner for {title}",
        )
        state = scene.children("FLIGHTSTATE")[0]
        vessels = state.children("VESSEL")
        need(
            one(state, "activeVessel") == "0"
            and len(vessels) == len(authored.flights)
            and float(one(state, "UT")) == authored.epoch,
            "Wrong starting fleet",
        )
        need(len({one(v, "pid") for v in vessels}) == len(vessels), "Duplicate scenario vessel")
        seen_parts, assigned = set(), []
        for vessel, start in zip(vessels, authored.flights):
            name = one(vessel, "name")
            need(name == start.craft.title, "Wrong scenario vessel order")
            need(float(one(vessel.children("ORBIT")[0], "EPH")) == authored.epoch, f"Wrong epoch for {name}")
            snapshots = vessel.children("PART")
            need(
                all(
                    vessel.children(k)
                    for k in ("DISCOVERY", "CTRLSTATE", "ACTIONGROUPS", "FLIGHTPLAN", "VESSELMODULES")
                ),
                f"{name} missing stock vessel state",
            )
            need(
                snapshots and one(vessel, "root") == "0" and one(vessel, "ref") == one(snapshots[0], "uid"),
                f"{name} needs a control reference",
            )
            for index, part in enumerate(snapshots):
                pid = one(part, "persistentId")
                need(pid not in seen_parts, "Duplicate scenario part")
                seen_parts.add(pid)
                kind = one(part, "name").replace(".", "_")
                cfg = parts[kind]
                parent = int(one(part, "parent"))
                need(parent == 0 if index == 0 else 0 <= parent < index, f"{name} has a broken parts tree")
                pose = snapshot_pose(part)
                for connection in part.values("attN"):
                    side, peer_index = connection.split(",")
                    peer = int(peer_index)
                    if peer >= 0:
                        need(peer < len(snapshots), f"{name} invalid peer index")
                        opposite = next((a.split(",")[0] for a in snapshots[peer].values("attN")
                                         if int(a.split(",")[1]) == index), None)
                        need(
                            peer < len(snapshots)
                            and f"{opposite}, {index}" in snapshots[peer].values("attN"),
                            f"{name} has a one-way stack connection",
                        )
                        linked = snapshots[peer]
                        verify_stack_join(
                            parts, kind, side, pose, one(linked, "name").replace(".", "_"), opposite, snapshot_pose(linked)
                        )
                if one(part, "attm") == "1":
                    need(
                        one(part, "srfN") == f"srfAttach, {parent}",
                        f"{kind} points at the wrong mounting parent",
                    )
                    host = snapshots[parent]
                    verify_surface_mount(
                        parts, data, game, one(host, "name"), snapshot_pose(host), kind, pose
                    )
                fitted = modules(part)
                if kind != "parachuteRadial" and kind not in HAB_FIXTURES:
                    verify_saturn_steering(part)
                    need(fitted.keys() == modules(cfg).keys(), f"{name} lacks {kind} module state")
                    capacity = resources(cfg)
                    need(resources(part).keys() == capacity.keys(), f"{name} lacks {kind} tanks")
                    need(
                        all(0 <= amount <= capacity[r] for r, amount in resources(part).items()),
                        "Invalid tank fill",
                    )
                if "ModuleJettison" in fitted:
                    need(
                        one(fitted["ModuleJettison"], "stagingEnabled") == "False",
                        f"{kind} has a staged shroud",
                    )
                if kind in ("famApolloSMMotor", "famLOKServiceMotor"):
                    stage = 3 if getattr(start.location, "at_pad", False) else 2
                    if name == "Apollo 24 Osprey":
                        stage = -1
                    need(
                        int(one(part, "istg")) == stage
                        and one(fitted["ModuleEnginesFX"], "stagingEnabled") == str(stage >= 0),
                        f"{name} has incorrect service engine staging",
                    )
                crew = part.values("crew")
                need(
                    len(crew) <= int((cfg.values("CrewCapacity") or ["0"])[0]),
                    f"{name} has more crew than seats",
                )
                assigned.extend(crew)
            verify_scenario_vessel(vessel, start, parts)
        guide = scene.children("SCENARIO")[0]
        need(
            one(guide, "name") == "FAMScenarioObjectives" and one(guide, "scene") == "7",
            f"{title} is missing its checklist",
        )
        plans = guide.children("OPERATION") or [guide]
        need(len(plans) == len(authored.operations), f"{title} has the wrong number of operations")
        by_name = {one(v, "name"): v for v in vessels}
        if "Jamestown" in by_name:
            habitat = by_name["Jamestown"]
            orbit = habitat.children("ORBIT")[0]
            need(abs(float(one(orbit, "INC")) - 90) < 0.1 and float(one(orbit, "ECC")) < 1e-4,
                 "Jamestown needs a circular polar approach to Shackleton")
            payload = habitat.children("PART")
            physics = read_node(game / "Physics.cfg")
            wet = sum(flight_mass(part, parts, physics) for part in payload)
            fuel = sum(available_fuel(part) for part in payload)
            sparks = [p for p in payload if key(p) == "liquidEngineMini_v2"]
            need(len(sparks) == 4, "Jamestown needs four working descent engines")
            thrust, isp, _ = engine_data(sparks[0], parts)
            limited_thrust = thrust * sum(float(one(modules(p)["ModuleEnginesFX"], "thrustPercentage")) / 100
                                          for p in sparks)
            spent, reserve = polar_descent(float(one(orbit, "SMA")), MUN_RADIUS, float(one(by_name["Falcon"], "alt")),
                                           wet, wet - fuel, limited_thrust, G0 * isp)
            need(reserve >= 200, "Keep 200 m/s for steering, hover or a divert on an aligned polar descent")
            print(f"Jamestown polar descent to the survey shelf (finite-thrust model): "
                  f"{spent:,.0f} m/s used, {reserve:,.0f} m/s remaining")
        for plan, operation in zip(plans, authored.operations):
            need(
                one(plan, "mission") == operation.mission
                and one(plan, "completed") == "0"
                and one(plan, "focus") == operation.focus
                and one(plan, "milestone") == operation.milestone
                and one(plan, "fromPad") == str(operation.from_pad).title(),
                f"{title} has invalid campaign progress",
            )
            tracked = {}
            crew_roles = dict(operation.expected_crew)
            for name in operation.vessels:
                for part in by_name[name].children("PART"):
                    role = OBJECTIVE_ASSETS.get(one(part, "name"))
                    if role:
                        crew = (
                            [k.name for k in crew_roles[role]] if role in crew_roles else part.values("crew")
                        )
                        need(role not in tracked, f"Duplicate objective role {role}")
                        tracked[role] = one(part, "persistentId"), crew
            assets = plan.children("ASSET")
            need(
                len(assets) == len(tracked)
                and {one(a, "role"): (one(a, "partId"), a.values("crew")) for a in assets} == tracked,
                "Checklist must track the actual spacecraft and crews",
            )
        verify_scenario_roster(scene, assigned)
    return len(files)


def snapshot_pose(part):
    return floats(one(part, "position")), floats(one(part, "rotation"))


def verify_mount_regressions(root, parts, game):
    source = root / "saves/scenarios/FAM S1.2 - Apollo 11.sfs"
    vessel = read_node(source).children("GAME")[0].children("FLIGHTSTATE")[0].children("VESSEL")[0]
    snapshots = vessel.children("PART")
    host = snapshot_pose(snapshots[0])
    chute = next(part for part in snapshots if one(part, "name") == "parachuteRadial")
    position, rotation = snapshot_pose(chute)
    q = math.sqrt(0.5)
    # These geometry mutations exercise the actual checks on the extracted release.
    bad = [
        (((-1.0125, -0.035, 0), (0, -q, 0, q)), "faces into"),  # Original Apollo pose
        ((add(position, scale(world_direction(rotation, (0, 0, -1)), 0.2)), rotation), "floating"),
    ]
    for pose, failure in bad:
        try:
            verify_surface_mount(parts, root / "GameData", game, "famApolloCM", host, "parachuteRadial", pose)
        except ValueError as error:
            need(failure in str(error), f"Wrong regression failure for {failure}: {error}")
        else:
            raise ValueError(f"Attachment audit missed the {failure} chute")


def verify_scenario_vessel(vessel, start, parts):
    name = one(vessel, "name")
    snapshots = vessel.children("PART")
    kinds = [one(p, "name") for p in snapshots]
    need(kinds == [p.kind.replace("_", ".") for p in start.craft.pieces], f"{name} needs its complete reference craft")
    need("ModuleCommand" in modules(snapshots[0]), f"{name} cannot be controlled")
    need(snapshots[0].values("crew") == [k.name for k in start.crew], f"{name} has incorrect starting crew")
    orbit = vessel.children("ORBIT")[0]
    sit = one(vessel, "sit")
    pad = getattr(start.location, "at_pad", False)
    need(int(one(orbit, "REF")) == (KERBIN if pad else MUN), f"{name} starts at the wrong body")
    if pad:
        need(
            sit == "PRELAUNCH"
            and one(vessel, "landed") == "True"
            and one(vessel, "launchedFrom") == one(vessel, "landedAt") == "LaunchPad"
            and abs(float(one(vessel, "lat")) - PAD_LAT) < 1e-6
            and abs(float(one(vessel, "lon")) - PAD_LON) < 1e-6
            and abs(float(one(vessel, "alt")) - float(one(vessel, "hgt")) - PAD_HEIGHT) < 0.001,
            f"{name} must be upright on the stock pad",
        )
        need(
            one(vessel, "stg") == str(max(p.stage for p in start.craft.pieces) + 1)
            and [int(one(p, "istg")) for p in snapshots] == [p.stage for p in start.craft.pieces],
            f"{name} lost the VAB liftoff and ascent sequence",
        )
        engines = [m for p in snapshots for m in p.children("MODULE") if one(m, "name") == "ModuleEnginesFX"]
        need(all(one(m, "EngineIgnited") == "False" for m in engines), "Pad engines must start shut down")
        adapter = snapshots[kinds.index("famPayloadAdapter")]
        fairing = modules(adapter)["ModuleProceduralFairing"]
        svc = next(p for p in snapshots if one(p, "name") in ("famLOKServiceBus", "famApolloSMBus"))
        need(
            one(fairing, "interstageCraftID") == one(svc, "cid")
            and len(fairing.children("XSECTION")) == 4
            and one(fairing, "stagingEnabled") == "True",
            f"{name} needs its attached payload fairing",
        )
        lowest = start.craft.sizing[-1]
        end = snapshots[kinds.index(lowest.kind + "Motor")]
        floor = snapshot_pose(end)[0][1] - PARTS[lowest.kind].height / 2
        need(abs(floor + float(one(vessel, "hgt"))) < 1e-4, f"{name} must sit at pad height")
        tower = snapshots[kinds.index("famLaunchTower")]
        motor = modules(tower)["ModuleEnginesFX"]
        need(
            one(motor, "stagingEnabled") == "False"
            and one(motor.children("ACTIONS")[0].children("ActivateAction")[0], "actionGroup") == "Abort",
            "Scenario escape motor must be abort-only",
        )
    if sit in ("LANDED", "PRELAUNCH"):
        lat, lon = (math.radians(float(one(vessel, k))) for k in ("lat", "lon"))
        up = world_direction(floats(one(vessel, "rot")), (0, 1, 0))
        radial = (math.cos(lat) * math.cos(lon), math.sin(lat), math.cos(lat) * math.sin(lon))
        need(
            math.dist(up, radial) < 1e-5
            and float(one(vessel, "hgt")) > 0
            and one(vessel, "skipGroundPositioning") == "False",
            f"{name} needs an upright ground pose",
        )
    else:
        a, e = (float(one(orbit, k)) for k in ("SMA", "ECC"))
        need(
            sit == "ORBITING" and a * (1 - e) > MUN_RADIUS + 15000 and a * (1 + e) < 2400000,
            f"{name} needs a stable starting orbit",
        )
    if kinds[0] in ("famApolloCM", "famLOK") and name != "Apollo 24 Osprey":
        recovery = [p for p in snapshots if one(p, "istg") in ("0", "1")]
        need(
            [one(p, "name") for p in recovery[:2]] == ["parachuteRadial", "parachuteRadial"]
            and [one(p, "istg") for p in recovery] == ["0", "0", "1"]
            and all(one(p, "parent") == "0" for p in recovery)
            and one(recovery[-1], "name") in ("famRing125", "famRing250"),
            f"{name} needs a service release and chute-only final stage",
        )
    if name == "Apollo 24 Osprey":
        need(
            "famApolloSMBus" in kinds and all(available_fuel(p) == 0 for p in snapshots),
            "Osprey starts with empty tanks",
        )
    if name == "Falcon":
        need("famIceCorer" in kinds, "Falcon needs the polar sampler")
        latitude = math.radians(float(one(vessel, "lat")))
        site_latitude = math.radians(SITE_LAT)
        longitude_offset = math.radians(float(one(vessel, "lon")) - SITE_LON)
        cosine = math.sin(latitude) * math.sin(site_latitude) + (
            math.cos(latitude) * math.cos(site_latitude) * math.cos(longitude_offset)
        )
        range_to_site = MUN_RADIUS * math.acos(max(-1, min(1, cosine)))
        need(80 < range_to_site < 1200, "Leave room to land the habitat within the survey site")
    # Both renderers must carry the same arrangement and fuel as the referenced stack.
    for part, piece in zip(snapshots, start.craft.pieces):
        cfg = parts[piece.kind]
        if piece.kind != "parachuteRadial":
            for name, amount in resources(cfg).items():
                fill = piece.propellant_fraction if name in ("LiquidFuel", "Oxidizer") else 1
                need(
                    math.isclose(resources(part)[name], amount * fill, abs_tol=1e-3),
                    "Unexpected scenario fuel fill",
                )


def verify_scenario_roster(scene, assigned):
    roster = scene.children("ROSTER")[0].children("KERBAL")
    names = {one(k, "name") for k in roster}
    seated = {one(k, "name") for k in roster if one(k, "state") == "Assigned"}
    cast = {k.name: k for k in SEASON_ONE_CAST}
    need(
        len(assigned) == len(seated)
        and set(assigned) == seated
        and names == seated | cast.keys()
        and len(names) == len(roster),
        "Incorrect scenario cast roster",
    )
    for k in roster:
        member = cast.get(one(k, "name"))
        if member:
            need(
                one(k, "trait") == member.trait
                and one(k, "gender") == member.gender
                and float(one(k, "brave")) == member.courage
                and float(one(k, "dumb")) == member.stupidity,
                "Incorrect character profile",
            )
        gear = k.children("INVENTORY")[0].children("STOREDPARTS")[0].children("STOREDPART")
        items = {one(item, "partName"): item.children("PART")[0] for item in gear}
        need(
            items.keys() == {"evaChute", "evaJetpack"}
            and resources(items["evaJetpack"]).get("EVA Propellant", 0) > 0,
            "Scenario crew needs EVA gear",
        )


def verify_cast(root):
    config = root / "GameData/FAMSeasons/Season1/Crew/Cast.cfg"
    profiles = read_node(config).children("FAM_CHARACTER")
    expected = {kerbal.name: kerbal for kerbal in SEASON_ONE_CAST}
    need(
        len(profiles) == len(expected) and {one(member, "name") for member in profiles} == expected.keys(),
        "The release must include the full Season 1 cast",
    )
    textures = set()
    for profile in profiles:
        member = expected[one(profile, "name")]
        need(
            one(profile, "head") == member.head,
            f"Wrong appearance mapping for {member.name}",
        )
        texture = (root / "GameData" / (member.head + ".png")).read_bytes()
        need(
            texture.startswith(b"\x89PNG\r\n\x1a\n") and struct.unpack_from(">II", texture, 16) == (512, 512),
            f"Invalid head texture for {member.name}",
        )
        textures.add(texture)
    need(len(textures) == len(expected), "Each character needs a distinct head texture")


def verify(root=ROOT, game=None):
    verify_cast(root)
    if game:
        need((game / "GameData/Squad").is_dir(), "Supply the KSP installation root")
    game_data = root / "GameData/FAMSeasons/Season1"
    plugin = (game_data.parent / "Plugins/FAMSeasons.dll").read_bytes()
    need(
        plugin[:2] == b"MZ"
        and b"BSJB" in plugin
        and b"FAMHabitatFactory" in plugin
        and b"FAMStagePolicy" in plugin,
        "Missing compiled habitat parameter or staging policy",
    )
    parts = {}
    nozzles = {}
    for path in sorted((game_data / "Parts").glob("*.cfg")):
        p = read_node(path).children("PART")[0]
        ident = one(p, "name")
        need(ident not in parts, "Duplicate part " + ident)
        parts[ident] = p
        nozzles[ident] = check_model(p, root)
        verify_part_systems(p, game)
    from build_review import verify_review, stock_configs
    verify_review(root, game)
    need(
        nozzles.get("famN1AMotor") == 30 and nozzles.get("famSaturnICMotor") == 5,
        "First-stage engine geometry",
    )
    costs = verify_tree(root, parts, game)
    installed_parts = dict(parts, **stock_configs(game))
    ships = [read_node(p) for p in sorted((root / "Ships/VAB").glob("FAM S1 - *.craft"))]
    need(len(ships) == 6, "Expected the six playable Season 1 craft")
    physics = read_node(game / "Physics.cfg")
    budgets = {}
    for ship in ships:
        assembly = verify_assembly(ship, installed_parts, root / "GameData", game)
        if not any(key(p).endswith("CargoAdapter") or key(p) == "famPayloadAdapter" for p in assembly):
            continue
        if key(assembly[0]) != "famJamestown":
            verify_payload_clearance(assembly, root / "GameData", game)
        verify_staging(ship, assembly, installed_parts)
        title, budget = flight_budget(ship, assembly, installed_parts, physics)
        budgets[title] = budget
    local_dv = surface_budgets(ships, installed_parts, physics)
    count = verify_campaign(root, installed_parts, costs, budgets, game)
    starts = verify_scenarios(root, installed_parts, game)
    verify_mount_regressions(root, installed_parts, game)
    print(
        f"{len(parts)} part models, {len(costs)} new R&D nodes, {count} linked contracts, "
        f"{len(ships)} VAB craft, {len(budgets)} audited launch staging sequences, {starts} scenario entries"
    )
    print(
        "Attachment audit passed on the exported models, staged craft, and saves. It rejected the old and floating chutes."
    )
    for title, (n, mass, twr, dv, price) in budgets.items():
        print(
            f"  {title}: {n} parts, {mass:.1f} t, launch TWR {twr:.2f}, launcher delta-v {dv:,.0f} m/s, {price:,} funds"
        )
    print("  Vacuum flight budgets (m/s): " + ", ".join(f"{k} {v}" for k, v in sorted(local_dv.items())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    verify(args.root, args.ksp_root)
