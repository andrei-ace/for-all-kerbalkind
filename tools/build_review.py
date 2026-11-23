"""Build and check the modular Season 1 flight hardware."""

import argparse
from copy import deepcopy
from dataclasses import replace
from math import dist, log
from pathlib import Path
from shutil import copy2

from attachments import rotate, world_direction
from config import Node, read_node
from craft import Craft, Piece, fleet, rescue_target
from hardware import add_rcs, module, part_config, resource
from modular_models import (
    AIRLOCK,
    AIRLOCK_MASS,
    AIRLOCK_RELEASE,
    AIRLOCK_RELEASE_HEIGHT,
    CARGO,
    CARGO_PIVOT,
    DOCK,
    FRAME,
    HULL,
    PAD,
    PISTON,
    POD,
    PODS,
    RADIO,
    ROBOTICS,
    ROOF_DOCK_FACE,
    SERVO,
    SOLAR_MODELS,
    TAIL_FINS,
    airlock_piece,
    cargo_fairing,
    hab_docks,
    hab_stock_fittings,
    jack_pair,
    jamestown_cargo_position,
    roll_servo,
    tail_fins,
    write_splits,
)
from parts import (
    AIRLOCK_LENGTH,
    AIRLOCK_SIDE,
    ART,
    END_DOCK_SEAT,
    HAB,
    HAB_PORT_Y,
    HAB_PORTS,
    JACKS,
    PARTS,
    REAR_DOCK_SEAT,
    REVIEW_LIFT,
    ROOF_DOCK_SEAT,
    ROOT,
    STATION_SEATS,
    STAIR_CLIP,
    STAIR_GROUP,
    STAIR_TREAD_COUNT,
)
from vendor.mu import Mu
from verify import (
    G0,
    available_fuel,
    craft_pose,
    engine_data,
    flight_mass,
    key,
    modules,
    need,
    one,
    skips_staging,
    stock_chute,
    stock_fixtures,
    verify_saturn_steering,
    verify_stack_join,
    wet_mass,
)

ADDON = "FAMSeasons/Season1"
PREFIX = "FAM S1 - "
STOCK_ENGINE = "liquidEngineMini_v2"
STOCK_PARTS = {
    STOCK_ENGINE: "Engine/liquidEngine48-7S_v2/liquidEngine48-7S_v2.cfg",
    DOCK: "Utility/dockingPort/dockingPort.cfg",
    "solarPanels3": "Electrical/3x2SolarPanels/3x2SolarPanels.cfg",
    "solarPanels4": "Electrical/1x6SolarPanels/1x6SolarPanels.cfg",
    "HighGainAntenna5_v2": "Utility/DirectAntennas/HG-5_v2.cfg",
    AIRLOCK_RELEASE: "Coupling/Separator_1.cfg",
}


def segments(kind):
    role = PARTS[kind].role
    if kind == "famJamestown":
        return (HULL,)
    if role in ("n1", "saturn"):
        return kind + "Tank", kind + "Motor"
    if role == "service":
        return kind + "Bus", kind + "Motor"
    if role in ("lkframe", "lmframe", "lsamframe"):
        return kind + "Frame", kind + "Tank", kind + "Motor"
    return (FRAME if kind == "famHabCradle" else kind,)


def names(items):
    return ["famJamestown" if item == HULL else item for item in items]


def node_at(cfg, side, value, size):
    x, z, y = value
    direction = 1 if side == "top" else -1
    key = "node_stack_" + side
    coordinates = f"{x:g}, {y:g}, {z:g}, 0, {direction}, 0, {size}"
    if cfg.values(key):
        cfg.set(key, coordinates)
    else:
        cfg.add(key, coordinates)


def fin_config(ident, saturn):
    return (
        Node(
            "PART",
            name=ident,
            module="Part",
            author="FAM Seasons",
            title=("S-IC Swept Tail Fin" if saturn else "Block A Grid Fin"),
            description="First-stage stabilizer with an operational stock control surface.",
            manufacturer="Jamestown Flight Works",
            category="Aero",
            subcategory=0,
            TechRequired=PARTS["famSaturnIC" if saturn else "famN1A"].tech,
            entryCost=900,
            cost=180,
            scale=1,
            rescaleFactor=1,
            attachRules="0,1,0,0,0",
            node_attach="0, 0, 0, 1, 0, 0",
            CoMOffset="-0.28, 0, 0",
            CoLOffset="-0.28, 0, 0",
            CoPOffset="-0.28, 0, 0",
            mass=0.066 if saturn else 0.056,
            crashTolerance=12,
            maxTemp=2400,
            bulkheadProfiles="srf",
            dragModelType="none",
            maximum_drag=0.02,
            minimum_drag=0.02,
            angularDrag=5,
            tags="fam season 1 rocket fin control",
        )
        .child(Node("MODEL", model=f"{ADDON}/Parts/{ident}"))
        .child(
            Node(
                "MODULE",
                name="ModuleControlSurface",
                transformName="obj_ctrlSrf",
                useInternalDragModel="True",
                dragCoeff=0.5,
                deflectionLiftCoeff=0.62 if saturn else 0.48,
                ctrlSurfaceRange=12,
                ctrlSurfaceArea=0.90,
                actuatorSpeed=25,
            )
        )
    )


def jamestown_lights(charge_per_second):
    return module("ModuleLight", lightName="jamestownFlood", lightMeshRendererName="Exterior lamp lenses",
                  useAnimationDim="False", useAutoDim="True", useResources="True",
                  resourceAmount=charge_per_second, lightBrightenSpeed=2.5, lightDimSpeed=2.5)


def cargo_configs():
    airlock = (
        Node(
            "PART",
            name=AIRLOCK,
            module="Part",
            author="FAM Seasons",
            title="Jamestown Dockable Airlock",
            manufacturer="Jamestown Flight Works",
            description="A crew airlock with probe control, batteries and monopropellant thrusters for assembly. "
                        "Two boarding lamps light the stairs.",
            category="Utility",
            subcategory=0,
            attachRules="1,0,1,1,0",
            node_stack_bottom=f"0, {-AIRLOCK_LENGTH / 2:g}, 0, 0, -1, 0, 1",
            scale=1, rescaleFactor=1,
            mass=AIRLOCK_MASS,
            cost=720,
            CrewCapacity=1,
            vesselType="Probe",
            crashTolerance=14,
            maxTemp=2000,
            bulkheadProfiles="size1",
            tags="fam season 1 hab docking airlock",
        )
        .child(Node("MODEL", model=f"{ADDON}/Parts/{AIRLOCK}"))
        .child(Node("INTERNAL", name="crewCabinInternals"))
        .child(module("ModuleAnimateGeneric", animationName=STAIR_CLIP, startEventGUIName="Deploy Stairs",
                      endEventGUIName="Stow Stairs", actionGUIName="Toggle Stairs",
                      allowAnimationWhileShielded="False", stagingEnabled="False"))
        .child(resource("ElectricCharge", 75))
        .child(module("ModuleCommand", minimumCrew=0).child(Node("RESOURCE", name="ElectricCharge", rate=0.018)))
        .child(module("ModuleSAS", SASServiceLevel=2))
        .child(
            module("ModuleReactionWheel", PitchTorque=0.36, YawTorque=0.36, RollTorque=0.36)
            .child(Node("RESOURCE", name="ElectricCharge", rate=0.025))
        )
        .child(
            module(
                "ModuleDataTransmitter", antennaType="DIRECT", antennaPower=1000000, packetInterval=0.6,
                packetSize=1, packetResourceCost=2, requiredResource="ElectricCharge",
            )
        )
    )
    add_rcs(airlock, capacity=12, thrust=0.08)
    airlock.child(jamestown_lights(0.02))
    adapter = part_config(CARGO)
    adapter.set("title", CARGO.title)
    adapter.children("MODEL")[0].set("model", f"{ADDON}/Parts/{CARGO.id}")
    modules(adapter)["ModuleProceduralFairing"].set("pivot", f"0,{CARGO_PIVOT:g},0")
    for cfg in (airlock, adapter):
        if cfg.values("TechRequired"):
            cfg.set("TechRequired", HAB)
        else:
            cfg.add("TechRequired", HAB)
    tank = part_config(POD)
    tank.set("TechRequired", HAB)
    tank.set("title", POD.title)
    tank.children("MODEL")[0].set("model", f"{ADDON}/Parts/{POD.id}")
    pad = Node("PART", name=PAD, module="Part", author="FAM Seasons", title="Jamestown Landing Footpad",
               manufacturer="Jamestown Flight Works", description="A broad contact shoe for a hydraulic landing leg.",
               category="Ground", subcategory=0, TechRequired=HAB, cost=35, mass=0.014,
               rescaleFactor=1, attachRules="1,0,1,0,0", node_stack_top="0,0,0,0,1,0,0",
               crashTolerance=18, breakingForce=200, breakingTorque=200, maxTemp=1700,
               bulkheadProfiles="size0", tags="fam jamestown review landing piston foot pad")
    pad.child(Node("MODEL", model=f"{ADDON}/Parts/{PAD}"))
    return {CARGO.id: adapter, AIRLOCK: airlock, POD.id: tank, PAD: pad}


def configure(game, folder, bases):
    folder.mkdir(parents=True, exist_ok=True)
    approved = ROOT / "art/season-1/modular/parts"
    for texture in approved.glob("*.png"):
        copy2(texture, folder / texture.name)
    for model in approved.glob("*.mu"):
        copy2(model, folder / model.name)
    configs = {}
    for kind in bases:
        part = PARTS[kind]
        models = segments(kind)
        if len(models) == 1:
            fractions = (1,)
        elif len(models) == 2:
            fractions = (0.63, 0.37)
        else:
            fractions = (0.43, 0.23, 0.34)
        for index, (model, ident, fraction) in enumerate(zip(models, names(models), fractions)):
            frame = model == FRAME
            drawing = folder / (model + ".mu")
            if not (approved / drawing.name).is_file():
                copy2(ART / drawing.name, drawing)
            nodes = {o.transform.name: o.transform.localPosition for o in Mu().read(drawing).obj.children}
            structural = frame or (model.endswith("Frame") and model != kind)
            split = len(models) > 1
            carries_motor = not frame and (not split or model.endswith("Motor"))
            data = replace(
                part,
                dry=0.56 if frame else round((part.dry - (AIRLOCK_MASS if model == HULL else 0)) * fraction, 5),
                cost=850 if frame else round(part.cost * fraction),
                thrust=part.thrust if carries_motor else 0,
                fuel=part.fuel if not frame and not structural and not (split and carries_motor) else 0,
            )
            cfg = part_config(data)
            cfg.set("name", ident)
            cfg.set("TechRequired", part.tech)
            title = "Jamestown Landing Frame" if frame else part.title
            if split:
                suffix = model.removeprefix(kind)
                title += {"Bus": " Bus", "Motor": " Engine", "Tank": " Tank", "Frame": " Frame"}[suffix]
            cfg.set("title", title)
            cfg.children("MODEL")[0].set("model", f"{ADDON}/Parts/{model}")
            cfg.set("tags", "fam season 1 " + title.lower())
            if model == HULL:
                # The review hull uses separate stock ports and solar arrays.
                replace_modules = {"ModuleDeployableSolarPanel", "ModuleDockingNode"}
                cfg.entries = [
                    e for e in cfg.entries
                    if not isinstance(e, Node) or not replace_modules.intersection(e.values("name"))
                ]
                node_at(cfg, "top", (0, 0, ROOF_DOCK_SEAT), 1)
                for side, (x, y, dx, dy) in STATION_SEATS.items():
                    field = "node_stack_" + side
                    value = f"{x:g}, {HAB_PORT_Y:g}, {y:g}, {dx}, 0, {dy}, 1"
                    (cfg.set if cfg.values(field) else cfg.add)(field, value)
                cfg.child(module("FAMDockControls"))
            if frame:
                cfg.set("description", "Four hydraulic leg sockets, four independent descent tank mounts "
                        "and two floodlights for landing.")
                cfg.set("category", "Structural")
                cfg.child(module("FAMBaseLift", dockingStroke=REVIEW_LIFT))
                cfg.child(jamestown_lights(0.04))
                node_at(cfg, "bottom", nodes["deliveryMount"], 2)
                for i in range(1, 5):
                    node_at(cfg, f"pod{i}", nodes[f"pod{i}Mount"], 0)
                    node_at(cfg, f"jack{i}", nodes[f"jack{i}Mount"], 1)
            if split:
                excluded = {"FAMStagePolicy"}
                if "interstage" not in nodes:
                    excluded.add("ModuleJettison")
                if not carries_motor:
                    excluded.add("ModuleGimbal")
                cfg.entries = [
                    e
                    for e in cfg.entries
                    if not isinstance(e, Node) or not excluded.intersection(e.values("name"))
                ]
                if "interstage" in nodes:
                    cfg.child(Node("MODULE", name="FAMStagePolicy", stagingEnabled="False",
                                   jettisonWithLowerStage="True", stageServiceEngine=str(part.role == "service")))
                if carries_motor and part.role == "saturn" and kind not in TAIL_FINS:
                    gimbal = modules(cfg)["ModuleGimbal"]
                    gimbal.add("useGimbalResponseSpeed", "True")
                    if kind == "famSaturnII":
                        # Once the S-IC fins leave, the five-engine cluster steers the wide payload.
                        gimbal.set("gimbalRange", 4)
                        gimbal.add("gimbalResponseSpeed", 10)
                        gimbal.add("gimbalLimiter", 100)
                    else:
                        gimbal.add("gimbalResponseSpeed", 16)
                        gimbal.add("gimbalLimiter", 55)
                    gimbal.add("enableRoll", "False")
                if structural:
                    cfg.set("category", "Structural")
                joint_size = 3 if kind == "famSaturnII" else 1
                if index:
                    marker = next(
                        n for n in ("frameMount", "fuelMount", "tankMount", "serviceMount") if n in nodes
                    )
                    node_at(cfg, "top", nodes[marker], joint_size)
                if index < len(models) - 1:
                    marker = "fuelMount" if structural else "engineMount"
                    node_at(cfg, "bottom", nodes[marker], joint_size)
            cfg.write(folder / (ident + ".cfg"))
            configs[ident] = cfg
    for stage, ident in TAIL_FINS.items():
        if stage in bases:
            cfg = fin_config(ident, saturn=stage == "famSaturnIC")
            cfg.write(folder / (ident + ".cfg"))
            configs[ident] = cfg
    for ident, cfg in cargo_configs().items():
        cfg.write(folder / (ident + ".cfg"))
        configs[ident] = cfg
    configs.update(stock_configs(game))
    return configs


def stock_configs(game):
    configs = dict(stock_fixtures(game), parachuteRadial=stock_chute(game))
    squad = game / "GameData/Squad/Parts"
    for kind, path in STOCK_PARTS.items():
        cfg = read_node(squad / path).children("PART")[0]
        if cfg.values("name") != [kind]:
            raise ValueError(f"Unexpected stock part at {path}")
        configs[kind] = cfg
    for kind in (PISTON, SERVO):
        cfg_path = game / "GameData" / ROBOTICS / (kind + ".cfg")
        if not cfg_path.is_file():
            raise ValueError(f"Jamestown's Sandbox review craft require Breaking Ground in {game}. Missing {cfg_path}")
        configs[kind] = read_node(cfg_path).children("PART")[0]
    return configs


def setup_pods(pieces, frame, stage):
    for i, (x, z, top) in enumerate(PODS, 1):
        px, py, pz = pieces[frame].position
        tank_index = len(pieces)
        tank = Piece(POD.id, -1, frame, (px + x, py + top - POD.height / 2, pz + z), propellant_fraction=0.88)
        engine = Piece(
            STOCK_ENGINE,
            stage,
            tank_index,
            (px + x, py + top - POD.height, pz + z),
            settings=(
                Node(
                    "MODULE",
                    name="ModuleEnginesFX",
                    isEnabled="True",
                    thrustPercentage=35,
                    stagingEnabled="True",
                ),
                Node(
                    "MODULE",
                    name="ModuleJettison",
                    isEnabled="True",
                    isJettisoned="True",
                    stagingEnabled="False",
                ),
                Node("MODULE", name="ModulePartVariants", isEnabled="True", selectedVariant="Bare"),
            ),
        )
        pieces[frame].connections[f"pod{i}"] = tank_index
        tank.connections.update(top=frame, bottom=tank_index + 1)
        engine.connections["top"] = tank_index
        pieces.extend((tank, engine))


def fixture_part(fixture, kind, parent, connections):
    x, z, y = fixture.position
    w, qx, qz, qy = fixture.rotation
    return Piece(kind, -1, parent, (x, y, z), (-qx, -qy, -qz, w), connections=connections)


def review_craft(original, *, roof_stowed_airlock=False):
    title = original.title
    ship = Craft(title, original.description, original.pieces[0].kind, original.kind)
    ship.sizing = original.pieces
    ship.pieces = []
    ranges = {}
    habitat = original.pieces[0].kind == "famJamestown"
    cargo = habitat and any(p.kind == "famPayloadAdapter" for p in original.pieces)
    for i, part in enumerate(original.pieces):
        if habitat and i != 0 and part.surface and part.parent == 0:
            continue
        if cargo and part.kind == "famPayloadAdapter":
            ids = (CARGO.id,)
        elif part.kind not in PARTS:
            ids = (part.kind,)
        else:
            ids = names(segments(part.kind))
        first = len(ship.pieces)
        last = first + len(ids) - 1
        ranges[i] = range(first, last + 1)
        for j, ident in enumerate(ids, first):
            motor = j == last
            axial_booster_joint = part.kind in PARTS and (
                PARTS[part.kind].role in ("n1", "saturn", "adapter")
                or (PARTS[part.kind].role == "ring" and part.stage >= 4)
            )
            new = replace(
                part,
                kind=ident,
                connections={},
                stage=part.stage if motor and ident != FRAME else -1,
                rigid_attachment=axial_booster_joint,
                autostrut="Grandparent" if axial_booster_joint else "Off",
            )
            if ident == "famSaturnIITank":
                new.autostrut = "Root"
            if j != first:
                new.parent = j - 1
                new.connections["top"] = j - 1
                ship.pieces[j - 1].connections["bottom"] = j
            ship.pieces.append(new)
    for i, original_part in enumerate(original.pieces):
        if i not in ranges:
            continue
        span = ranges[i]
        head, tail = ship.pieces[span.start], ship.pieces[span.stop - 1]
        if original_part.parent is not None:
            parent = ranges[original_part.parent]
            attaches_above_parent = original_part.connections.get("bottom") == original_part.parent
            head.parent = parent.start if original_part.surface or attaches_above_parent else parent.stop - 1
        for side, child in original_part.connections.items():
            target = ranges[child]
            if side == "top":
                head.connections[side] = target.stop - 1
            else:
                tail.connections[side] = target.start
        if head.kind == FRAME:
            setup_pods(ship.pieces, span.start, stage=3 if cargo else 0)
            for index in range(len(JACKS)):
                piston, foot = jack_pair(index, head.position[1])
                anchor = len(ship.pieces)
                head.connections[f"jack{index + 1}"] = anchor
                leg = fixture_part(piston, PISTON, span.start, {"bottom": span.start, "top": anchor + 1})
                leg.settings = (module("ModuleRoboticServoPiston", isEnabled="True", targetExtension=0,
                                       traverseVelocity=0.08, servoIsLocked="True"),)
                ship.pieces.extend((leg, fixture_part(foot, PAD, anchor, {"top": anchor})))
        if original_part.kind in TAIL_FINS:
            px, py, pz = tail.position
            for fin in tail_fins(original_part.kind):
                x, z, y = fin.position
                w, _, _, q = fin.rotation
                ship.pieces.append(
                    Piece(fin.name, -1, span.stop - 1, (px + x, py + y, pz + z), (0, -q, 0, w), surface=True)
                )
    if habitat:
        roof_stowed = cargo or roof_stowed_airlock
        ports = hab_docks(packed=roof_stowed)
        collar = ports.pop("collar")
        for side, fixture in ports.items():
            parent = 0
            socket = side
            if side in STATION_SEATS:
                parent = len(ship.pieces)
                ship.pieces[0].connections[side] = parent
                servo = fixture_part(roll_servo(side), SERVO, 0, {"bottom": 0})
                servo.settings = (module("ModuleRoboticRotationServo", isEnabled="True", targetAngle=0,
                                         traverseVelocity=5, servoIsLocked="True"),)
                ship.pieces.append(servo)
                socket = "top"
            ship.pieces[parent].connections[socket] = len(ship.pieces)
            ship.pieces.append(fixture_part(fixture, DOCK, parent, {"bottom": parent}))
        mount = ship.pieces[0].connections["top"]
        if not roof_stowed:
            mount = ship.pieces[ship.pieces[0].connections["airlock"]].connections["top"]
        if roof_stowed:
            separator = len(ship.pieces)
            ship.pieces[mount].connections["top"] = separator
            ship.pieces.append(
                Piece(
                    AIRLOCK_RELEASE, -1, mount, (0, ROOF_DOCK_FACE + AIRLOCK_RELEASE_HEIGHT / 2, 0),
                    connections={"bottom": mount},
                    settings=(Node(
                        "MODULE", name="ModuleDecouple", isEnabled="True", stagingEnabled="False",
                        ejectionForcePercent=5,
                    ),),
                )
            )
            mount = separator
        collar_index = len(ship.pieces)
        ship.pieces[mount].connections["top"] = collar_index
        ship.pieces.append(fixture_part(collar, DOCK, mount, {"top": mount, "bottom": collar_index + 1}))
        airlock = fixture_part(airlock_piece(packed=roof_stowed), AIRLOCK, collar_index, {"bottom": collar_index})
        airlock.settings = (module("ModuleAnimateGeneric", isEnabled="True", animTime=0 if roof_stowed else 1,
                                   animSwitch=str(roof_stowed)),)
        ship.pieces.append(airlock)
        is_outpost = not roof_stowed
        for fixture in hab_stock_fittings():
            x, z, y = fixture.position
            w, qx, qz, qy = fixture.rotation
            deployable = {
                **dict.fromkeys(SOLAR_MODELS, "ModuleDeployableSolarPanel"),
                RADIO: "ModuleDeployableAntenna",
            }.get(fixture.stock)
            settings = (
                (
                    Node(
                        "MODULE",
                        name=deployable,
                        isEnabled="True",
                        deployState="EXTENDED" if is_outpost else "RETRACTED",
                        animTime=int(is_outpost),
                    ),
                )
                if deployable
                else ()
            )
            ship.pieces.append(
                Piece(
                    SOLAR_MODELS.get(fixture.stock, fixture.name),
                    -1,
                    0,
                    (x, y, z),
                    (-qx, -qy, -qz, w),
                    surface=True,
                    settings=settings,
                )
            )
    if cargo:
        ship.description = (
            "Launch the folded kit and transfer to Mun orbit. Stage to release the fairing and habitat. "
            "Choose Release roof airlock on the habitat, or Decouple on the TS-12. "
            "Let the ring clear, then fly the airlock to the front port using its RCS. "
            "Control from the habitat's roof port for powered descent."
        )
        ship.fairing = lambda: (None, cargo_fairing())
    elif any(p.kind == "famPayloadAdapter" for p in original.pieces):
        interstage, profile = original.fairing()
        target = ship.pieces[ranges[original.pieces.index(interstage)].start] if interstage else None
        ship.fairing = lambda: (target, profile)
    return ship


def review_fleet():
    ships = fleet()
    outpost = deepcopy(ships[2])
    outpost.title = PREFIX + "Jamestown Outpost"
    outpost.description = "The modular habitat and descent kit ready for inspection."
    adapter = next(i for i, piece in enumerate(outpost.pieces) if piece.kind == "famPayloadAdapter")
    outpost.pieces = outpost.pieces[:adapter]
    outpost.pieces[1].connections.pop("bottom")
    outpost.pieces[1].stage = 0
    delivery = ships[2].pieces
    x, old_center, z = delivery[adapter].position
    shift = jamestown_cargo_position() - old_center - (CARGO.height - PARTS["famPayloadAdapter"].height) / 2
    delivery[adapter].position = (x, jamestown_cargo_position(), z)
    for piece in delivery[adapter + 1 :]:
        x, y, z = piece.position
        piece.position = (x, y + shift, z)
    survey = deepcopy(ships[1])
    survey.title = PREFIX + "Apollo 15 Survey"
    survey.description = "Fly the Apollo stack to Shackleton and recover the polar core from Falcon."
    cabin = next(i for i, piece in enumerate(survey.pieces) if piece.kind == "famLMAscent")
    survey.surface_mount("famIceCorer", cabin, -0.13, 0)
    return [*ships, outpost, survey]


def check_jamestown_budget(saved, configs, game):
    physics = read_node(game / "Physics.cfg")
    masses = [flight_mass(part, configs, physics) for part in saved]
    wet = sum(masses)
    by_kind = {key(p): i for i, p in enumerate(saved)}
    if CARGO.id not in by_kind:
        usable = sum(available_fuel(p) for p in saved)
        sparks = [p for p in saved if key(p) == STOCK_ENGINE]
        thrust, isp, _ = engine_data(sparks[0], configs)
        thrust *= sum(float(one(modules(p)["ModuleEnginesFX"], "thrustPercentage")) / 100 for p in sparks)
        dv = isp * G0 * log(wet / (wet - usable))
        twr = thrust / (1.63 * wet)
        # The map's 580 m/s starts in a 14 km orbit. Keep 100 m/s after an
        # 870 m/s high-latitude approach from the campaign's 34 km orbit.
        need(len(sparks) == 4 and abs(thrust - 28) < 0.01 and 870 + 100 <= dv < 1150 and twr > 1.5,
             "Jamestown must have balanced Mun descent thrust and landing reserves at its shipped fill")
        print(f"Jamestown Outpost: {wet:.3f} t, {thrust:.0f} kN, {twr:.2f} Mun TWR, {dv:,.0f} m/s vacuum")
        return
    fairing = modules(saved[by_kind[CARGO.id]])["ModuleProceduralFairing"]
    sections = [(float(one(s, "h")), float(one(s, "r"))) for s in fairing.children("XSECTION")]
    need(sections == cargo_fairing(), "Jamestown's VAB fairing differs from the packed Blender assembly")
    (barrel_h, barrel_r), (cap_h, cap_r), (tip_h, tip_r) = sections[-3:]
    need(max(r for _, r in sections) <= 2.60 and 0.59 < cap_r / barrel_r < 0.69
         and 0.60 < (tip_h - cap_h) / cap_r < 0.82 and 0 < tip_r <= 0.12
         and 0.30 < (barrel_r - cap_r) / (cap_h - barrel_h) < 0.47,
         "Keep the packed barrel, shallow upper taper and short conical cap of the delivery reference")
    remaining = wet
    stage_dv = []
    for stage, ring in (("IC", "famRing375"), ("II", "famRing250"), ("IVB", CARGO.id)):
        tank, motor = (by_kind[f"famSaturn{stage}{section}"] for section in ("Tank", "Motor"))
        thrust, vacuum, sea = engine_data(saved[motor], configs)
        fuel = available_fuel(saved[tank])
        isp = sea if stage == "IC" else vacuum
        increment = isp * G0 * log(remaining / (remaining - fuel))
        stage_dv.append(increment)
        if stage == "IC":
            twr = thrust * sea / vacuum / (remaining * G0)
            first_stage_vacuum = increment * vacuum / sea
            remaining -= sum(m for p, m in zip(saved, masses) if key(p) == TAIL_FINS["famSaturnIC"])
        remaining -= masses[tank] + masses[motor] + masses[by_kind[ring]]
    dv = sum(stage_dv)
    vacuum_total = first_stage_vacuum + sum(stage_dv[1:])
    # Community map, in vacuum m/s. Allow 400 beyond the map's 3,400 for ascent.
    # The transfer stage carries the packed outpost, including its undrained descent tanks.
    need(1.25 < twr < 1.65 and dv < 5750 and first_stage_vacuum + stage_dv[1] >= 3900,
         "Jamestown's first two stages must cover 3,800 m/s to orbit with at least 100 m/s to spare")
    need(stage_dv[2] >= 860 + 310 + 400 + 340,
         "The loaded S-IVB needs 400 m/s for circularization and targeting, then transfer, polar capture and reserve")
    print(f"Jamestown Delivery: {wet:.3f} t, {twr:.2f} liftoff TWR, {dv:,.0f} m/s launcher "
          f"(S-IC {stage_dv[0]:,.0f}, S-II {stage_dv[1]:,.0f}, S-IVB {stage_dv[2]:,.0f}; "
          f"all-vacuum {vacuum_total:,.0f})")


def verify_review(root, game):
    ships = review_fleet()
    bases = {p.kind for ship in ships for p in ship.pieces if p.kind in PARTS}
    expected = {ident for kind in bases for ident in names(segments(kind))}
    expected.update({*TAIL_FINS.values(), AIRLOCK, CARGO.id, POD.id, PAD})
    shrouded = {
        kind + "Motor" for kind in bases
        if PARTS[kind].role in ("n1", "saturn", "service") and kind not in TAIL_FINS
    }
    parts_dir = root / f"GameData/{ADDON}/Parts"
    configs = stock_configs(game)
    need(
        {p.stem for p in parts_dir.glob("*.cfg")} == expected, "Missing or obsolete flight part configs"
    )
    for ident in expected:
        cfg = read_node(parts_dir / (ident + ".cfg")).children("PART")[0]
        need(one(cfg, "name") == ident, f"Wrong review part name for {ident}")
        need(
            one(cfg, "category").lower() != "none" and one(cfg, "TechRequired") in {part.tech for part in PARTS.values()}
            and not any(v.lower() == "true" for v in cfg.values("TechHidden")),
            f"{ident} is hidden from the Sandbox parts catalog",
        )
        configs[ident] = cfg
        model_url = one(cfg.children("MODEL")[0], "model")
        need(model_url.startswith(f"{ADDON}/Parts/"), f"Wrong review model location for {ident}")
        model_path = root / "GameData" / (model_url + ".mu")
        if ident in ("famJamestown", FRAME, AIRLOCK, PAD, POD.id, CARGO.id):
            editable_export = ROOT / "art/season-1/modular/parts" / model_path.name
            need(editable_export.read_bytes() == model_path.read_bytes(),
                 f"{ident} in the review game differs from the mesh used to render the gallery")
        model = Mu().read(model_path)
        nodes = {o.transform.name: o for o in model.obj.children}
        if ident in TAIL_FINS.values():
            control = modules(cfg)["ModuleControlSurface"]
            pivot = nodes[one(control, "transformName")]
            need(any(hasattr(o, "shared_mesh") for o in pivot.children), f"{ident} has no moving blade")
        if ident in (AIRLOCK, "famJamestown"):
            systems = modules(cfg)
            need("ModuleDockingNode" not in systems, f"{ident} must use separate stock docking ports")
            if ident == "famJamestown":
                need("FAMDockControls" in systems, "The four covered docking servos must be accessible from the hull")
        if ident == AIRLOCK:
            systems = modules(cfg)
            need(
                one(systems["ModuleCommand"], "minimumCrew") == "0"
                and "ModuleRCSFX" in systems
                and sum(o.transform.name == "rcsJet" for o in model.obj.children) == 12,
                "The airlock must maneuver independently",
            )
            hinge = nodes[STAIR_GROUP]
            clip = model.obj.animation.clips[0]
            need(one(systems["ModuleAnimateGeneric"], "animationName") == clip.name == STAIR_CLIP,
                 "The detachable airlock must own the stair control")
            steps = [o for o in hinge.children if o.transform.name.startswith("stairTread")]
            curve = next(c for c in clip.curves if c.path == STAIR_GROUP and c.property == "m_LocalRotation.x")
            need(len(steps) == STAIR_TREAD_COUNT and all(any(hasattr(o, "collider") for o in step.children)
                 for step in steps) and abs(curve.keys[0].value) > 0.9 and abs(curve.keys[-1].value) < 1e-5
                 and any(o.transform.name == "Ground shoe" and hasattr(o, "collider") for o in hinge.children),
                 "The four tread colliders and ground shoe must fold through the airlock hinge")
        if ident == FRAME:
            need(STAIR_GROUP not in nodes and "ModuleAnimateGeneric" not in modules(cfg)
                 and "FAMBaseLift" in modules(cfg) and all(f"jack{i}Mount" in nodes for i in range(1, 5)),
                 "The frame must carry the lift cylinders and the airlock must carry its own stairs")
        if "ModuleGimbal" in modules(cfg):
            pivot = nodes["gimbal"]
            tip = rotate(pivot.transform.localRotation, (0, 1, 0))
            need(dist(tip, (0, 0, -1)) < 1e-5, f"{ident} gimbal points away from its thrust axis")
            need(all(o.transform.localRotation == (1, 0, 0, 0) for o in pivot.children), f"{ident} jet axes differ")
        if ident in ("famSaturnIITank", "famSaturnIIMotor"):
            joint = "node_stack_bottom" if ident.endswith("Tank") else "node_stack_top"
            need(int(one(cfg, joint).split(",")[-1]) == 3, "The S-II engine plate needs matching 3.75 m nodes")
        if ident == "famSaturnIIMotor":
            gimbal = modules(cfg)["ModuleGimbal"]
            throw = float(one(gimbal, "gimbalRange")) * float(one(gimbal, "gimbalLimiter")) / 100
            need(3.5 <= throw <= 5 and one(gimbal, "useGimbalResponseSpeed") == "True",
                 "The S-II needs at least 3.5 degrees of damped steering after the S-IC fins separate")
        need(("interstage" in nodes) == (ident in shrouded), f"{ident} has the wrong shroud geometry")
        if ident in shrouded:
            shroud = modules(cfg)["ModuleJettison"]
            need(
                one(shroud, "jettisonName") == "interstage"
                and one(shroud, "bottomNodeName") == "bottom"
                and one(shroud, "checkBottomNode") == "True"
                and skips_staging(shroud)
                and one(modules(cfg)["FAMStagePolicy"], "jettisonWithLowerStage") == "True",
                f"{ident} shroud must follow the lower attachment without staging",
            )
    vab = root / "Ships/VAB"
    expected_ships = [review_craft(ship) for ship in ships]
    need(
        {p.stem for p in vab.glob(f"{PREFIX}*.craft")} == {ship.title for ship in expected_ships},
        "Missing or obsolete Sandbox review craft",
    )
    for ship in expected_ships:
        saved = read_node(vab / (ship.title + ".craft")).children("PART")
        need(len(saved) == len(ship.pieces), f"{ship.title} part count changed")
        by_id = {one(p, "part"): p for p in saved}
        need(len(by_id) == len(saved), f"{ship.title} has duplicate parts")
        if key(saved[0]) == "famJamestown":
            check_jamestown_budget(saved, configs, game)
            stock_ports = {index for index, part in enumerate(saved) if key(part) == DOCK}
            hull_ports = ship.pieces[0].connections
            need(
                len(stock_ports) == 6
                and hull_ports["top"] in stock_ports
                and all(ship.pieces[hull_ports[side]].kind == SERVO
                        and ship.pieces[hull_ports[side]].connections["top"] in stock_ports
                        for side in STATION_SEATS),
                f"{ship.title} is missing a stock Clamp-O-Tron on a hatch or airlock",
            )
            frame = next(piece for piece in ship.pieces if piece.kind == FRAME)
            for i in range(1, 5):
                jack = ship.pieces[frame.connections[f"jack{i}"]]
                need(jack.kind == PISTON and ship.pieces[jack.connections["top"]].kind == PAD,
                     "The moving top of each installed hydraulic cylinder must carry a footpad")
            tunnel = next(part for part in saved if key(part) == AIRLOCK)
            need(float(one(modules(tunnel)["ModuleAnimateGeneric"], "animTime")) == int("Outpost" in ship.title),
                 "Jamestown must pack the stairs on the roof and deploy them on the landed airlock")
        for index, (piece, part) in enumerate(zip(ship.pieces, saved)):
            kind = key(part)
            need(kind == piece.kind and kind in configs, f"{ship.title} cannot resolve {kind}")
            need(int(one(part, "istg")) == piece.stage, f"{ship.title} has a stale stage for {kind}")
            prefab = [one(m, "name") for m in configs[kind].children("MODULE")]
            if "ModuleDockingNode" in prefab:
                saved_modules = part.children("MODULE")
                need(
                    [one(m, "name") for m in saved_modules] == prefab
                    and all(one(m, "state") == "Ready" for m in saved_modules
                            if one(m, "name") == "ModuleDockingNode"),
                    f"{kind} must load all of its stock docking ports",
                )
            for side, other in piece.connections.items():
                opposite = next(name for name, paired in ship.pieces[other].connections.items() if paired == index)
                target = saved[other]
                prefix = f"{side},{one(target, 'part')}_"
                need(any(n.startswith(prefix) for n in part.values("attN")), f"{kind} is missing its {side} joint")
                verify_stack_join(configs, kind, side, craft_pose(part), key(target), opposite, craft_pose(target))
            verify_saturn_steering(part)
            if kind in TAIL_FINS.values():
                motor = ship.pieces[piece.parent]
                _, parent_id = one(part, "srfN").split(",")
                parent = by_id[parent_id]
                pos, rotation = craft_pose(part)
                center, _ = craft_pose(parent)
                offset = tuple(a - b for a, b in zip(pos, center))
                footprint = tuple(a - b for a, b in zip(piece.position, motor.position))
                outward = world_direction(rotation, (-1, 0, 0))
                need(
                    key(parent) == motor.kind
                    and one(part, "istg") == "-1"
                    and dist(offset, footprint) < 1e-4
                    and dist(outward, world_direction(piece.rotation, (-1, 0, 0))) < 1e-4,
                    f"{ship.title} has a misaligned {kind}",
                )
    print(f"{len(expected)} flight part configs and {len(ships)} complete VAB craft verified")


def build_review(game, output):
    ships = review_fleet()
    configs = configure(
        game,
        output / f"GameData/{ADDON}/Parts",
        sorted({p.kind for ship in ships for p in ship.pieces if p.kind in PARTS}),
    )
    vab = output / "Ships/VAB"
    vab.mkdir(parents=True, exist_ok=True)
    for base in ships:
        ship = review_craft(base)
        ship.render(configs, sizing=base.pieces).write(vab / (ship.title + ".craft"))
        print(f"{ship.title} ({len(ship.pieces)} parts)")
    target = review_craft(rescue_target())
    target.render(configs).write(output / "GameData/FAMSeasons/Season1/Contracts/Assets/Osprey.craft")
    verify_review(output, game)
    return configs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ksp-root", type=Path, required=True)
    p.add_argument("--output", type=Path, default=ROOT)
    args = p.parse_args()
    build_review(args.ksp_root, args.output)


if __name__ == "__main__":
    main()
