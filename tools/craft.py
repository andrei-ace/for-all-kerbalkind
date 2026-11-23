"""Assemble the four VAB craft and the private Apollo 24 contract target."""

from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from math import hypot, pi
from zlib import crc32

from attachments import minus, surface_pose, world_direction
from config import Node
from hardware import loaded_resources, part_config
from parts import HAB_FIXTURES, PARTS, SEASON, SHIPS


def vec(values):
    return ",".join(f"{v:.7g}" for v in values)


@dataclass
class Piece:
    kind: str
    stage: int
    parent: int | None
    position: tuple
    rotation: tuple = (0, 0, 0, 1)
    surface: bool = False
    connections: dict = field(default_factory=dict)
    propellant_fraction: float = 1
    settings: tuple = ()
    rigid_attachment: bool = False
    autostrut: str = "Off"


def seed_interface_modules(part, config):
    definitions = config.children("MODULE")
    stateful = {"ModuleDockingNode", "ModuleRoboticServoPiston", "ModuleRoboticRotationServo"}
    bare_spark = config.values("name") == ["liquidEngineMini_v2"] and part.children("MODULE")
    if not bare_spark and not any(module.values("name")[0] in stateful for module in definitions):
        return
    saved = part.children("MODULE")
    part.entries = [entry for entry in part.entries if not isinstance(entry, Node) or entry.kind != "MODULE"]
    # A new stock docking node fills its list of accepted sizes in OnLoad.
    # Keep the prefab module order so every port on a multi-port part gets that call.
    for definition in definitions:
        name = definition.values("name")[0]
        state = next((node for node in saved if node.values("name") == [name]), None)
        if state is None:
            state = Node("MODULE", name=name, isEnabled="True")
        else:
            saved.remove(state)
        if name == "ModuleDockingNode" and not state.values("state"):
            state.add("state", "Ready").add("dockUId", 0).add("dockNodeIdx", 0)
        part.child(state)
    for state in saved:
        part.child(state)


class Craft:
    def __init__(self, title, description, root, kind="Ship"):
        self.title, self.description, self.kind = title, description, kind
        self.pieces = [Piece(root, -1, None, (0, 0, 0))]
        self.tip = 0

    def below(self, kind, stage=-1):
        parent = self.pieces[self.tip]
        distance = (PARTS[parent.kind].height + PARTS[kind].height) / 2
        x, y, z = parent.position
        idx = len(self.pieces)
        part = Piece(kind, stage, self.tip, (x, y - distance, z))
        parent.connections["bottom"] = idx
        part.connections["top"] = self.tip
        self.pieces.append(part)
        self.tip = idx

    def parachutes(self):
        for azimuth in (-pi / 4, 3 * pi / 4):
            self.surface_mount("parachuteRadial", 0, -0.09, azimuth, stage=0)

    def surface_mount(self, kind, parent, height, azimuth, stage=-1):
        base = self.pieces[parent]
        contact, rotation = surface_pose(base.kind, kind, height, azimuth)
        position = tuple(a + b for a, b in zip(base.position, contact))
        self.pieces.append(Piece(kind, stage, parent, position, rotation, True))

    def escape_tower(self, stage):
        root = self.pieces[0]
        tower = Piece(
            "famLaunchTower", stage, 0, (0, (PARTS[root.kind].height + PARTS["famLaunchTower"].height) / 2, 0)
        )
        root.connections["top"] = len(self.pieces)
        tower.connections["bottom"] = 0
        self.pieces.append(tower)

    def jamestown_fixtures(self):
        for kind, fixture in HAB_FIXTURES.items():
            position = minus(fixture.position, world_direction(fixture.rotation, fixture.attach))
            self.pieces.append(Piece(kind, -1, 0, position, fixture.rotation, True))

    def fairing(self):
        adapter = next(p for p in self.pieces if p.kind == "famPayloadAdapter")
        origin = adapter.position[1] - 0.33
        orbiter = next((p for p in self.pieces if p.kind in ("famApolloSM", "famLOKService")), None)
        radius = {"famLOK": 1.49, "famApolloCM": 1.86, "famJamestown": 2.82, "famLSAMCab": 2.02}[
            self.pieces[0].kind
        ]
        if orbiter:
            shape = PARTS[orbiter.kind]
            top = orbiter.position[1] - shape.height / 2 + 0.55 - origin
            end = shape.radius
        else:
            # The LSAM's wide roof array must clear the fairing's taper.
            closeout = 0.95 if self.pieces[0].kind == "famLSAMCab" else 0.68
            top = self.pieces[0].position[1] + PARTS[self.pieces[0].kind].height / 2 + closeout - origin
            end = 0.15
        return orbiter, [(0, 1.25), (0.63, radius), (top - 1.15, radius), (top, end)]

    def fairing_state(self, ids):
        interstage, profile = self.fairing()
        target_id = ids[self.pieces.index(interstage)] if interstage else 0
        fairing = Node(
            "MODULE",
            name="ModuleProceduralFairing",
            isEnabled="True",
            interstageCraftID=target_id,
            nArcs=2,
            ejectionForce=60,
            useClamshell="True",
            stagingEnabled="True",
            fsm="st_idle",
        )
        for h, r in profile:
            fairing.child(Node("XSECTION", h=f"{h:.5f}", r=f"{r:.5f}"))
        return fairing, sum(pi * (r + s) * hypot(b - a, s - r) for (a, r), (b, s) in pairwise(profile))

    @staticmethod
    def abort_action(piece):
        if piece.kind.removesuffix("Review") == "famLaunchTower":
            return "ModuleEnginesFX", "ActivateAction"
        if piece.parent == 0 and piece.kind.startswith("famRing") and piece.stage == 1:
            return "ModuleDecouple", "DecoupleAction"
        return None

    def render(self, configs=None, sizing=None):
        configs = configs or {}
        sizing = sizing or getattr(self, "sizing", self.pieces)
        bottom = min(p.position[1] - PARTS[p.kind].height / 2 for p in sizing if p.kind in PARTS)
        top = max(p.position[1] + PARTS[p.kind].height / 2 for p in sizing if p.kind in PARTS)
        radius = max(
            PARTS[p.kind].radius
            * (1.6 if PARTS[p.kind].role.endswith("frame") or p.kind == "famHabCradle" else 1)
            for p in sizing
            if p.kind in PARTS
        )
        if any(p.kind == "famPayloadAdapter" for p in sizing):
            radius = max(radius, max(r for _, r in self.fairing()[1]))
        origin = 1 - bottom
        vessel_id = crc32(self.title.encode())
        # KSP normalizes underscores in PART names to periods before appending the craft ID.
        ids = [
            f"{p.kind.replace('_', '.')}_{crc32(f'{self.title}/{i}'.encode())}"
            for i, p in enumerate(self.pieces)
        ]
        craft = Node(
            "",
            ship=self.title,
            version="1.12.5",
            description=self.description,
            type="VAB",
            size=vec((radius * 2, top - bottom, radius * 2)),
            steamPublishedFileId=0,
            persistentId=vessel_id,
            rot="0,0,0,1",
            missionFlag="Squad/Flags/default",
            vesselType=self.kind,
        )
        per_stage = Counter()
        for i, p in enumerate(self.pieces):
            cfg = configs.get(p.kind)
            if cfg is None and p.kind in PARTS:
                cfg = part_config(PARTS[p.kind])
            x, y, z = p.position
            pos = (x, y + origin, z)
            parent_pos = self.pieces[p.parent].position if p.parent is not None else (0, 0, 0)
            relative = tuple(x - y for x, y in zip(p.position, parent_pos)) if p.parent is not None else pos
            part = Node(
                "PART",
                part=ids[i],
                partName="Part",
                persistentId=crc32(ids[i].encode()),
                pos=vec(pos),
                attPos="0,0,0",
                attPos0=vec(relative),
                rot=vec(p.rotation),
                attRot="0,0,0,1",
                attRot0=vec(p.rotation),
                mir="1,1,1",
                symMethod="Radial",
                autostrutMode=p.autostrut,
                rigidAttachment=str(p.rigid_attachment),
                istg=p.stage,
                resPri=0,
                dstg=0,
                sidx=per_stage[p.stage] if p.stage >= 0 else -1,
                sqor=-1,
                sepI=-1,
                attm=int(p.surface),
                modCost=0,
                modMass=0,
                modSize="0,0,0",
            )
            per_stage[p.stage] += 1
            for j, child in enumerate(self.pieces):
                if child.parent == i:
                    part.add("link", ids[j])
            for attach, other in p.connections.items():
                local = cfg.values("node_stack_" + attach)[0].split(",")[:3]
                coordinates = "|".join(f"{float(axis):g}" for axis in local)
                part.add("attN", f"{attach},{ids[other]}_{coordinates}")
            if p.surface:
                part.add("srfN", "srfAttach," + ids[p.parent])
            for kind in ("EVENTS", "ACTIONS", "PARTDATA"):
                part.child(Node(kind))
            if cfg is not None:
                if any(m.values("name") == ["ModuleProceduralFairing"] for m in cfg.children("MODULE")):
                    fairing, area = self.fairing_state([ident.rsplit("_", 1)[1] for ident in ids])
                    part.set("modMass", f"{area * 0.01:.5f}")
                    part.set("modCost", f"{area * 8:.3f}")
                    part.child(fairing)
                if binding := self.abort_action(p):
                    module_name, action_name = binding
                    action = Node(
                        action_name,
                        actionGroup="Abort",
                        wasActiveBeforePartWasAdjusted="False",
                    )
                    part.child(
                        Node(
                            "MODULE",
                            name=module_name,
                            isEnabled="True",
                            stagingEnabled="False" if module_name == "ModuleEnginesFX" else "True",
                        ).child(Node("ACTIONS").child(action))
                    )
                for tank in loaded_resources(cfg, p.propellant_fraction):
                    part.child(
                        tank.add("flowState", "True")
                        .add("isTweakable", "True")
                        .add("hideFlow", "False")
                        .add("isVisible", "True")
                        .add("flowMode", "Both")
                    )
            for settings in p.settings:
                part.child(settings)
            if cfg is not None:
                seed_interface_modules(part, cfg)
            craft.child(part)
        return craft


def saturn_stack(ship, transfer_fill=1, booster_fuel=34):
    for name, stage in (
        ("famPayloadAdapter", 3),
        ("famSaturnIVB", 4),
        ("famRing250", 4),
        ("famSaturnII", 5),
        ("famRing375", 5),
        ("famSaturnIC", 6),
    ):
        ship.below(name, stage)
    next(p for p in ship.pieces if p.kind == "famSaturnIVB").propellant_fraction = transfer_fill
    booster = next(p for p in ship.pieces if p.kind == "famSaturnIC")
    booster.propellant_fraction = booster_fuel / PARTS[booster.kind].fuel


def fleet():
    n1 = Craft(
        "FAM S1 - N1-L3",
        "Seat two in the LOK. Stage the lunar train in Mun orbit at zero throttle to release the spacecraft and arm their engines. Turn and dock nose-to-nose with the LK.",
        "famLOK",
    )
    n1.parachutes()
    n1.escape_tower(6)
    for name, stage in (
        ("famRing125", 1),
        ("famLOKService", 3),
        ("famRing125", 3),
        ("famLK", 2),
        ("famRing125", 2),
        ("famLKPlatform", 3),
        ("famPayloadAdapter", 3),
        ("famBlockG", 4),
        ("famRing250", 4),
        ("famN1V", 5),
        ("famRing250", 5),
        ("famN1B", 6),
        ("famRing375", 6),
        ("famN1A", 7),
    ):
        n1.below(name, stage)

    apollo = Craft(
        "FAM S1 - Saturn V Apollo",
        "Seat three in the command module. Stage the lunar train at zero throttle to release the spacecraft and arm their engines. Turn and dock with the LM. Add the corer for Apollo 15.",
        "famApolloCM",
    )
    apollo.parachutes()
    apollo.escape_tower(5)
    for name, stage in (
        ("famRing250", 1),
        ("famApolloSM", 3),
        ("famRing125", 3),
        ("famLMAscent", 2),
        ("famRing125", 2),
        ("famLMDescent", 3),
    ):
        apollo.below(name, stage)
    saturn_stack(apollo)

    hab = Craft(
        "FAM S1 - Jamestown Delivery",
        "Clear every seat. Deliver the habitat to Shackleton using probe control. Separate the S-IVB in Mun orbit "
        "and land on four pads with the airlock stairs attached and both end ports clear.",
        "famJamestown",
        "Base",
    )
    hab.below("famHabCradle", 3)
    hab.jamestown_fixtures()
    saturn_stack(hab, booster_fuel=38)
    lsam = Craft(
        "FAM S1 - LSAM Delivery",
        "Seat at least two in the LSAM. Deliver the crew to Jamestown, leave a pilot and reserve propellant aboard, then reuse the same propulsion deck for Apollo 24.",
        "famLSAMCab",
        "Lander",
    )
    lsam.below("famRescueTank")
    lsam.below("famLSAMDrive", 3)
    saturn_stack(lsam, transfer_fill=0.6)
    return [n1, apollo, hab, lsam]


def rescue_target():
    target = Craft("Apollo 24 Osprey", "Stranded command ship for the Apollo 24 rescue.", "famApolloCM")
    target.below("famApolloSM", -1)
    target.pieces[-1].propellant_fraction = 0
    return target


def write_fleet():
    for ship in fleet():
        ship.render().write(SHIPS / (ship.title + ".craft"))
    rescue_target().render().write(SEASON / "Contracts" / "Assets" / "Osprey.craft")
