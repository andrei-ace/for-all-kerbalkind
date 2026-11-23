"""Build model-only Season 1 kits for the Blender review."""

from dataclasses import dataclass, replace
from math import cos, pi, sin, sqrt
from pathlib import Path
from shutil import copyfile

from attachments import STOCK_CHUTE
from craft import Craft, fleet
from models import (
    Surface,
    booster,
    control_fin,
    equipment,
    fin_skirt,
    finish_model,
    jamestown_airlock,
    jamestown_cradle,
    jamestown_foot,
    jamestown_hull_review,
    jamestown_pod,
    landing_frame,
    model,
    node,
    profile_radius,
)
from parts import (
    AIRLOCK_LENGTH,
    AIRLOCK_SIDE,
    ART,
    DOCK_DEPTH,
    END_DOCK_SEAT,
    HAB_FIXTURES,
    HAB_PORT_Y,
    HAB_PORTS,
    JACK_BOTTOM,
    JACK_TOP,
    JACKS,
    PARTS,
    REAR_DOCK_SEAT,
    REVIEW_CARRIER_SEAT,
    ROOF_DOCK_SEAT,
    SERVO_DEPTH,
    STATION_SEATS,
    Part,
)

FRAME = "famJamestownFrame"
HULL = "famJamestownReviewHull"
AIRLOCK = "famJamestownAirlock"
AIRLOCK_MASS = 0.26
AIRLOCK_RELEASE = "Separator_1"
AIRLOCK_RELEASE_MODEL = "Coupling/Assets/Separator_1.mu"
AIRLOCK_RELEASE_HEIGHT = 0.10
DOCK = "dockingPort2"
DOCK_MODEL = "Utility/dockingPort/dockingPort.mu"
ROOF_DOCK_FACE = ROOF_DOCK_SEAT + DOCK_DEPTH
CARGO = replace(
    PARTS["famPayloadAdapter"],
    id="famJamestownCargoAdapter",
    title="Jamestown Cargo Adapter",
    height=1.48,
    dry=0.24,
    cost=730,
    description="A tapered fairing carries the airlock above the folded Jamestown habitat.",
)
CARGO_PIVOT = 0.11 - CARGO.height / 2
ROBOTICS = "SquadExpansion/Serenity/Parts/Robotics"
SERVO, PISTON = "rotoServo_02", "piston_02"
SERVO_MODEL = f"{ROBOTICS}/Assets/RotoServo_02.mu"
PISTON_MODEL = f"{ROBOTICS}/Assets/piston_02.mu"
PAD = "famJamestownFootpad"
PODS = tuple((x, y, 1.38) for x in (-1.64, 1.64) for y in (-1.40, 1.40))
POD = Part(
    "famJamestownDescentTank", "Jamestown Descent Tank", "jamestownPod", "start",
    0.78, 0.27, 0.27, 0.0625, 150, "An exposed descent tank with a stack mount for a stock Spark.", 0.50,
)
SPARK = "Engine/liquidEngine48-7S_v2/SparkV2.mu"
ARRAY = "Electrical/3x2SolarPanels/model.mu"
ARRAY_LONG = "Electrical/1x6SolarPanels/model.mu"
SOLAR_MODELS = {ARRAY: "solarPanels3", ARRAY_LONG: "solarPanels4"}
RADIO = "Utility/DirectAntennas/HGAntenna_v2.mu"
CHUTE_MODEL = STOCK_CHUTE.removeprefix("Squad/Parts/") + "/model.mu"
RADIO_MOUNT = (1.36, 1.30, 0.37)
ARRAYS = tuple((x, side * (1.30 if x == 0 else 1.26), 0.72) for side in (-1, 1) for x in (-1.15, 0, 1.15))
TAIL_FINS = {"famSaturnIC": "famSaturnControlFin", "famN1A": "famN1ControlFin"}


@dataclass(frozen=True)
class Piece:
    name: str
    position: tuple
    separation: float = 0
    stock: str = ""
    rotation: tuple = (1, 0, 0, 0)  # Blender wxyz


def write_splits(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    copyfile(ART / "livery.png", directory / "livery.png")

    def write(skin, root):
        finish_model(root, skin).write(directory / (root.transform.name + ".mu"))

    def component(part_id, suffix):
        return Surface(), node(part_id + suffix)

    frame = Surface(), node(FRAME)
    hull = Surface(), node(HULL)
    airlock = Surface(), node(AIRLOCK)
    jamestown_hull_review(*hull, PARTS["famJamestown"], ARRAYS, RADIO_MOUNT)
    write(*hull)
    jamestown_cradle(*frame, PARTS["famHabCradle"], pod_mounts=PODS)
    write(*frame)
    jamestown_airlock(*airlock)
    write(*airlock)
    pad = Surface(), node(PAD)
    jamestown_foot(*pad)
    write(*pad)
    tank = Surface(), node(POD.id)
    jamestown_pod(*tank, POD)
    write(*tank)
    model(CARGO).write(directory / (CARGO.id + ".mu"))
    for stage, name in TAIL_FINS.items():
        fin = Surface(), node(name)
        control_fin(*fin, grid=stage == "famN1A")
        write(*fin)
    for part in PARTS.values():
        if part.role in ("n1", "saturn", "service"):
            tank = component(part.id, "Tank" if part.role != "service" else "Bus")
            motor = component(part.id, "Motor")
            generate = equipment if part.role == "service" else booster
            generate(*tank, part, motor=motor)
            write(*tank)
            write(*motor)
        elif part.role in ("lkframe", "lmframe", "lsamframe"):
            structure = component(part.id, "Frame")
            tank = component(part.id, "Tank")
            motor = component(part.id, "Motor")
            landing_frame(*structure, part, fuel=tank, motor=motor)
            write(*structure)
            write(*tank)
            write(*motor)


def tail_fins(stage):
    part = PARTS[stage]
    profile = fin_skirt(part)
    saturn = part.role == "saturn"
    z = profile[-1][0] - (0.28 if saturn else 0.145)
    radius = profile_radius(profile, z)
    for i in range(4):
        azimuth = (pi / 4 if saturn else 0) + i * pi / 2
        yaw = azimuth + pi  # The blade extends along its local -X axis.
        yield Piece(
            TAIL_FINS[stage],
            (radius * cos(azimuth), radius * sin(azimuth), z),
            rotation=(cos(yaw / 2), 0, 0, sin(yaw / 2)),
        )


def hab_stock_fittings():
    result = []
    for index, (x, y, z) in enumerate(ARRAYS, 1):
        yaw = pi / 4 if y < 0 else -pi / 4
        tilt = pi / 21 if y > 0 else -pi / 18
        cy, sy, ct, st = cos(yaw), sin(yaw), cos(tilt), sin(tilt)
        result.append(
            Piece(
                f"OX-4{'L' if x == 0 else 'W'} {index}",
                (x, y, z),
                stock=ARRAY_LONG if x == 0 else ARRAY,
                rotation=(cy * ct, -sy * st, cy * st, sy * ct),
            )
        )
    h = sqrt(0.5)
    result.append(Piece("HighGainAntenna5_v2", RADIO_MOUNT, stock=RADIO, rotation=(h, 0, 0, h)))
    result.append(Piece("ladder1", (-0.87, 1.565, -0.57), stock=HAB_FIXTURES["ladder1"].model,
                        rotation=(h, 0, 0, -h)))
    return result


def airlock_piece(packed=False):
    if packed:
        height = ROOF_DOCK_FACE + AIRLOCK_RELEASE_HEIGHT + DOCK_DEPTH + AIRLOCK_LENGTH / 2
        return Piece(AIRLOCK, (0, 0, height))
    x, y, z = AIRLOCK_SIDE
    h = sqrt(0.5)
    return Piece(AIRLOCK, (x, y - SERVO_DEPTH - 2 * DOCK_DEPTH - AIRLOCK_LENGTH / 2, z), rotation=(h, h, 0, 0))


def hab_docks(packed):
    h = sqrt(0.5)
    ports = {
        port: Piece(port + " Clamp-O-Tron", (sign * END_DOCK_SEAT, 0, HAB_PORT_Y),
                    stock=DOCK_MODEL, rotation=(0.5, 0.5, sign * 0.5, sign * 0.5))
        for port, sign in HAB_PORTS
    }
    ports["top"] = Piece("Roof Clamp-O-Tron", (0, 0, ROOF_DOCK_SEAT), stock=DOCK_MODEL)
    ports["rear"] = Piece("Rear Clamp-O-Tron", (0, REAR_DOCK_SEAT, HAB_PORT_Y), stock=DOCK_MODEL,
                          rotation=(h, -h, 0, 0))
    ports["airlock"] = Piece("Front Clamp-O-Tron", (0, AIRLOCK_SIDE[1] - SERVO_DEPTH, HAB_PORT_Y), stock=DOCK_MODEL, rotation=(h, h, 0, 0))
    x, y, z = airlock_piece(packed).position
    ports["collar"] = (
        Piece("Airlock Clamp-O-Tron", (x, y, z - AIRLOCK_LENGTH / 2), stock=DOCK_MODEL,
              rotation=(0, 0, 1, 0))
        if packed else
        Piece("Airlock Clamp-O-Tron", (x, y + AIRLOCK_LENGTH / 2, z), stock=DOCK_MODEL,
              rotation=(0, 0, h, h))
    )
    return ports


def roll_servo(side="airlock"):
    x, y, _, _ = STATION_SEATS[side]
    orientation = hab_docks(False)[side].rotation
    return Piece(side + " roll servo", (x, y, HAB_PORT_Y), stock=SERVO_MODEL, rotation=orientation)


def jack_pair(index, frame_z):
    x, y, top = JACKS[index]
    origin = frame_z + top + JACK_BOTTOM
    piston = Piece(f"Lift cylinder {index + 1}", (x, y, origin), -0.65, PISTON_MODEL, (0, 1, 0, 0))
    foot = Piece(PAD, (x, y, origin - JACK_TOP), -0.82)
    return piston, foot


def hab_kit(packed=False):
    frame_z = -(PARTS["famJamestown"].height + PARTS["famHabCradle"].height) / 2
    result = [Piece(HULL, (0, 0, 0)), Piece(FRAME, (0, 0, frame_z), -0.50)]
    result.extend(roll_servo(side) for side in STATION_SEATS)
    for index in range(len(JACKS)):
        result.extend(jack_pair(index, frame_z))
    for index, (x, y, top) in enumerate(PODS, 1):
        zz = frame_z + top
        result.append(Piece(POD.id, (x, y, zz - POD.height / 2), -1.08))
        result.append(Piece(f"Spark {index}", (x, y, zz - POD.height), -1.66, SPARK))
    if packed:
        ring_z = ROOF_DOCK_FACE + AIRLOCK_RELEASE_HEIGHT / 2
        result.append(Piece(AIRLOCK_RELEASE, (0, 0, ring_z), stock=AIRLOCK_RELEASE_MODEL))
    return [*result, airlock_piece(packed), *hab_docks(packed).values(), *hab_stock_fittings()]


def jamestown_cargo_position():
    frame_z = -(PARTS["famJamestown"].height + PARTS["famHabCradle"].height) / 2
    return frame_z + REVIEW_CARRIER_SEAT - CARGO.height / 2


def cargo_fairing():
    # Axial height and panel radius from the stock fairing pivot, in metres.
    # The landing gear sets the barrel width. The upper shroud is a shallow frustum
    # with a separate, short conical cap over the roof-stowed airlock.
    return [
        (0, 1.25),
        (0.22, 1.37),
        (0.80, 2.05),
        (1.19, 2.50),
        (1.43, 2.58),
        (3.15, 2.56),
        (3.73, 2.49),
        (5.96, 1.60),
        (7.10, 0.075),
    ]


def launchers():
    result = []
    for craft, offset in zip(fleet()[:2], (-3.1, 3.1)):
        stages = [
            p
            for p in craft.pieces
            if p.stage >= 4 and PARTS.get(p.kind) and PARTS[p.kind].role in ("n1", "saturn", "ring")
        ]
        stages.reverse()
        bottom = stages[0].position[1] - PARTS[stages[0].kind].height / 2
        gap = 0
        for item in stages:
            pose = (offset, 0, item.position[1] - bottom)
            if PARTS[item.kind].role == "ring":
                result.append(Piece(item.kind, pose, gap))
            else:
                result.append(Piece(item.kind + "Motor", pose, gap))
                if item.kind in TAIL_FINS:
                    for fin in tail_fins(item.kind):
                        location = tuple(a + b for a, b in zip(pose, fin.position))
                        result.append(Piece(fin.name, location, gap, rotation=fin.rotation))
                gap += 0.43
                result.append(Piece(item.kind + "Tank", pose, gap))
            gap += 0.15
    return result


def orbiter(offset, cabin, ring, service):
    ring_z = -(PARTS[cabin].height + PARTS[ring].height) / 2
    service_z = ring_z - (PARTS[ring].height + PARTS[service].height) / 2
    components = [
        Piece(cabin, (offset, 0, 0), 0.9),
        Piece(ring, (offset, 0, ring_z), 0.50),
        Piece(service + "Bus", (offset, 0, service_z), 0.14),
        Piece(service + "Motor", (offset, 0, service_z), -0.23),
    ]
    if cabin == "famApolloCM":
        recovery = Craft("Columbia", "", cabin)
        recovery.parachutes()
        for index, chute in enumerate(recovery.pieces[1:], 1):
            x, y, z = chute.position
            qx, qy, qz, qw = chute.rotation
            components.append(Piece(f"Mk2-R {index}", (offset + x, z, y), 0.9,
                                    CHUTE_MODEL, (qw, -qx, -qz, -qy)))
    return components


def lander(offset, cabin, middle, platform):
    ring_z = -(PARTS[cabin].height + PARTS[middle].height) / 2
    frame_z = ring_z - (PARTS[middle].height + PARTS[platform].height) / 2
    return [
        Piece(cabin, (offset, 0, 0), 0.92),
        Piece(middle, (offset, 0, ring_z), 0.52),
        Piece(platform + "Frame", (offset, 0, frame_z), 0.16),
        Piece(platform + "Tank", (offset, 0, frame_z), -0.30),
        Piece(platform + "Motor", (offset, 0, frame_z), -0.70),
    ]


def kits():
    return {
        "jamestown": hab_kit(),
        "jamestown-packed": [*hab_kit(packed=True), Piece(CARGO.id, (0, 0, jamestown_cargo_position()))],
        "launchers": launchers(),
        "soviet": [
            *orbiter(-1.9, "famLOK", "famRing125", "famLOKService"),
            *lander(1.9, "famLK", "famRing125", "famLKPlatform"),
        ],
        "apollo": [
            *orbiter(-2.2, "famApolloCM", "famRing250", "famApolloSM"),
            *lander(2.2, "famLMAscent", "famRing125", "famLMDescent"),
        ],
        "lsam": lander(0, "famLSAMCab", "famRescueTank", "famLSAMDrive"),
    }
