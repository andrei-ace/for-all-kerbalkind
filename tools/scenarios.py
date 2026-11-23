"""Author the Season 1 campaigns in KSP's stock scenario save format."""

from collections import Counter
from dataclasses import dataclass, replace
from math import cos, pi, radians, sin
from uuid import NAMESPACE_URL, uuid5
from zlib import crc32

from copy import deepcopy

from config import Node
from contracts import SITE_LAT, SITE_LON
from craft import Craft, fleet, rescue_target, vec
from crew import (
    ALEXEI,
    BUZZ,
    DANIELLE,
    ED,
    ELLEN,
    LOK_PILOT,
    MICHAEL,
    MOLLY,
    NEIL,
    SEASON_ONE_CAST,
    TRACY,
    WUBBO,
    Crew,
)
from hardware import loaded_resources, part_config, resource
from parts import HAB_FIXTURES, PARTS, ROOT

SCENARIOS = ROOT / "saves" / "scenarios"
KERBIN = 1
KERBIN_RADIUS = 600_000
MUN = 2
MUN_RADIUS = 200_000
# The stock LaunchPad location and deck height from a KSP 1.12.5 prelaunch save.
PAD_LAT, PAD_LON, PAD_HEIGHT = -0.0972078, -74.5576741, 72.486
EPOCH = 20_000
SHACKLETON_DAYLIGHT = 47_797
FLAG = "Squad/Flags/default"
OBJECTIVE_ASSETS = {
    "famLK": "lander",
    "famLMAscent": "lander",
    "famLKPlatformFrame": "descent",
    "famLMDescentFrame": "descent",
    "famLOK": "orbiter",
    "famApolloCM": "orbiter",
    "famLOKServiceBus": "service",
    "famApolloSMBus": "service",
    "famIceCorer": "corer",
    "famJamestown": "habitat",
    "famLSAMCab": "ferry",
    "famLSAMDriveTank": "drive",
    "famRescueTank": "tank",
}


def stable_number(label):
    return crc32(label.encode())


@dataclass(frozen=True)
class Orbit:
    semimajor_axis: float
    inclination: float = 0
    longitude: float = 0
    anomaly: float = 0
    eccentricity: float = 0
    argument: float = 0
    body: int = MUN

    def altitude(self):
        eccentric_anomaly = self.anomaly
        e = self.eccentricity
        for _ in range(10):
            eccentric_anomaly -= (eccentric_anomaly - e * sin(eccentric_anomaly) - self.anomaly) / (
                1 - e * cos(eccentric_anomaly)
            )
        body_radius = KERBIN_RADIUS if self.body == KERBIN else MUN_RADIUS
        return self.semimajor_axis * (1 - e * cos(eccentric_anomaly)) - body_radius

    def node(self, epoch):
        return Node(
            "ORBIT",
            SMA=self.semimajor_axis,
            ECC=self.eccentricity,
            INC=self.inclination,
            LPE=self.argument,
            LAN=self.longitude,
            MNA=self.anomaly,
            EPH=epoch,
            REF=self.body,
        )


@dataclass(frozen=True)
class Surface:
    latitude: float = SITE_LAT
    longitude: float = SITE_LON
    altitude: float = 2_200
    at_pad: bool = False
    heading: float = 0

    def rotation(self):
        # Body-fixed axes. At zero longitude local up points along +X and forward points north.
        a, b = radians(self.latitude) / 2, radians(-self.longitude) / 2
        x, y, z, w = (
            -(cos(a) - sin(a)) / 2,
            -(cos(a) + sin(a)) / 2,
            (sin(a) - cos(a)) / 2,
            (cos(a) + sin(a)) / 2,
        )
        x, y, z, w = (
            cos(b) * x + sin(b) * z,
            cos(b) * y + sin(b) * w,
            cos(b) * z - sin(b) * x,
            cos(b) * w - sin(b) * y,
        )
        c, s = cos(radians(self.heading) / 2), sin(radians(self.heading) / 2)
        return vec((c * x - s * z, c * y + s * w, c * z + s * x, c * w - s * y))

    def orbit(self, altitude):
        # A landed vessel still needs an ORBIT reference. KSP positions it with the saved
        # latitude/longitude, then places its feet on the terrain when unpacking it.
        return Orbit(
            ((KERBIN_RADIUS if self.at_pad else MUN_RADIUS) + altitude) / 2,
            abs(self.latitude),
            self.longitude,
            pi,
            0.9997,
            90 if self.latitude < 0 else 270,
            body=KERBIN if self.at_pad else MUN,
        )


@dataclass(frozen=True)
class Start:
    craft: Craft
    location: Orbit | Surface
    crew: tuple[Crew, ...] = ()
    active_engine: str = ""


@dataclass(frozen=True)
class Operation:
    mission: str
    focus: str
    milestone: str
    vessels: tuple[str, ...]
    expected_crew: tuple = ()
    from_pad: bool = False


@dataclass(frozen=True)
class Scenario:
    filename: str
    description: str
    flights: tuple[Start, ...]
    operations: tuple[Operation, ...]
    epoch: int = EPOCH


def orbiter(title, cabin, separator, service):
    craft = Craft(title, "", cabin)
    craft.parachutes()
    craft.below(separator, 1)
    craft.below(service, 2)
    return craft


def lander(title, cabin, deck, corer=False):
    craft = Craft(title, "", cabin, "Lander")
    craft.pieces[0].stage = 0
    craft.below("famRing125", 0)
    craft.below(deck)
    if corer:
        craft.surface_mount("famIceCorer", 0, -0.13, 0)
    return craft


def habitat():
    craft = Craft("Jamestown", "", "famJamestown", "Base")
    craft.below("famHabCradle")
    craft.jamestown_fixtures()
    return craft


def ferry():
    craft = Craft("LSAM", "", "famLSAMCab", "Lander")
    craft.below("famRescueTank")
    craft.below("famLSAMDrive")
    return craft


def scenarios():
    n1, saturn, *_ = fleet()
    n1.title, saturn.title = "Red Mun", "Apollo 11"
    pad = Surface(PAD_LAT, PAD_LON, PAD_HEIGHT, at_pad=True)
    falcon = lander("Falcon", "famLMAscent", "famLMDescent", corer=True)
    # Stock Mun terrain sampled across the landing footprint at local daylight.
    # The survey deck stays clear of the future habitat target.
    survey_site = Surface(-77.01, 11.2302, 6038.80)
    campaigns = (
        Scenario(
            "FAM S1.1 - Red Mun",
            "Soviet program. Launch the complete N1-L3 from Kerbin, insert into Mun orbit and put one pilot "
            "on the surface. Reunite in orbit and fly both Kerbals home.",
            (Start(n1, pad, (LOK_PILOT, ALEXEI)),),
            (
                Operation(
                    "red-mun",
                    "Red Mun",
                    "",
                    (n1.title,),
                    (("orbiter", (LOK_PILOT,)), ("lander", (ALEXEI,))),
                    from_pad=True,
                ),
            ),
        ),
        Scenario(
            "FAM S1.2 - Apollo 11",
            "American program. Launch Saturn V from Kerbin, send Eagle to the Mun and leave Columbia "
            "with its command pilot. Redock, reunite the crew and complete Kerbin re-entry.",
            (Start(saturn, pad, (MICHAEL, NEIL, BUZZ)),),
            (
                Operation(
                    "apollo-11",
                    "Apollo 11",
                    "",
                    (saturn.title,),
                    (("orbiter", (MICHAEL,)), ("lander", (NEIL, BUZZ))),
                    from_pad=True,
                ),
            ),
        ),
        Scenario(
            "FAM S1.3 - Jamestown Campaign",
            "American program. Start on the Mun aboard Falcon. Open the sampler on the side of the landing deck, "
            "choose Drill a regolith core, and keep the experiment. Follow the Mission Checklist to return the core, "
            "establish and crew Jamestown, and rescue Ellyn from Apollo 24 in the same flight save.",
            (
                Start(falcon, survey_site, (ED, MOLLY)),
                Start(
                    orbiter("Endeavour", "famApolloCM", "famRing250", "famApolloSM"),
                    Orbit(232_000, 90, SITE_LON, 4.4),
                    (WUBBO,),
                    "famApolloSM",
                ),
                Start(habitat(), Orbit(234_000, 90, SITE_LON, 4.1), active_engine="famHabCradle"),
                Start(ferry(), Orbit(231_000, 90, SITE_LON, 4.2), (TRACY, DANIELLE), "famLSAMDrive"),
                Start(rescue_target(), Orbit(295_000, 90, SITE_LON, 1.25, 0.16, 30), (ELLEN,)),
            ),
            (
                Operation("into-the-crater", "Falcon", "Return the Shackleton core", ("Falcon", "Endeavour")),
                Operation("jamestown", "Jamestown", "Establish Jamestown", ("Jamestown",)),
                Operation("first-crew", "LSAM", "Establish Jamestown", ("Jamestown", "LSAM")),
                Operation("apollo-24", "LSAM", "Rescue Apollo 24", ("Jamestown", "LSAM", "Apollo 24 Osprey")),
            ),
            epoch=SHACKLETON_DAYLIGHT,
        ),
    )


    return tuple(replace(campaign, flights=tuple(flight_kit(f) for f in campaign.flights)) for campaign in campaigns)


def flight_kit(start):
    from build_review import STOCK_ENGINE, review_craft

    if hasattr(start.craft, "sizing"):
        return start
    motor = start.active_engine
    if motor == "famHabCradle":
        motor = STOCK_ENGINE
    elif motor in PARTS and PARTS[motor].role in ("n1", "saturn", "service", "lkframe", "lmframe", "lsamframe"):
        motor += "Motor"
    craft = review_craft(start.craft)
    if start.craft.pieces[0].kind == "famJamestown" and isinstance(start.location, Orbit):
        for piece in craft.pieces:
            for setting in piece.settings:
                if setting.values("name") == ["ModuleAnimateGeneric"]:
                    setting.set("animTime", 0)
                    setting.set("animSwitch", "True")
    return replace(start, craft=craft, active_engine=motor)


def loadout(kerbal, seat_index=-1):
    node = Node(
        "KERBAL",
        name=kerbal.name,
        gender=kerbal.gender,
        type="Crew",
        trait=kerbal.trait,
        brave=kerbal.courage,
        dumb=kerbal.stupidity,
        state="Assigned" if seat_index >= 0 else "Available",
        idx=seat_index,
        veteran="False",
        extraXP=0,
    )
    node.child(Node("CAREER_LOG", flight=0))
    node.child(Node("FLIGHT_LOG", flight=0))
    gear = Node(
        "INVENTORY",
        name="ModuleInventoryPart",
        isEnabled="True",
        inventory="evaChute,evaJetpack",
    )
    slots = Node("STOREDPARTS")
    for slot, name in enumerate(("evaChute", "evaJetpack")):
        stored = Node(
            "STOREDPART",
            slotIndex=slot,
            partName=name,
            quantity=1,
            stackCapacity=1,
            variantName="",
        )
        snapshot = Node(
            "PART",
            name=name,
            cid=0,
            uid=0,
            mid=0,
            launchID=0,
            parent=0,
            position="0,0,0",
            rotation="0,0,0,1",
            mirror="1,1,1",
            symMethod="Radial",
            persistentId=stable_number(f"{kerbal.name}/{name}"),
        )
        if name == "evaJetpack":
            snapshot.child(resource("EVA Propellant", 5).add("flowState", "True").add("isTweakable", "False"))
        slots.child(stored.child(snapshot))
    return node.child(gear.child(slots))


def part_state(start, index, launch_id, ids, stage_order, configs):
    piece = start.craft.pieces[index]
    ident = ids[index]
    config = configs[piece.kind]
    dry_mass = config.values("mass")[0]
    part = Node(
        "PART",
        name=piece.kind.replace("_", "."),
        cid=ident,
        uid=ident,
        mid=ids[0],
        persistentId=stable_number(f"part/{ident}"),
        launchID=launch_id,
        parent=piece.parent if piece.parent is not None else 0,
        position=vec(piece.position),
        rotation=vec(piece.rotation),
        mirror="1,1,1",
        symMethod="Radial",
        istg=piece.stage,
        resPri=0,
        dstg=0,
        sqor=-1,
        sepI=-1,
        sidx=stage_order,
        attm=int(piece.surface),
        srfN=f"srfAttach, {piece.parent}" if piece.surface else ", -1",
        mass=dry_mass,
        shielded="False",
        temp=285,
        tempExt=285,
        state=0,
        attached="True",
        flag=FLAG,
        rTrf="_default",
        autostrutMode=piece.autostrut,
        rigidAttachment=str(piece.rigid_attachment),
        modCost=0,
        modMass=0,
    )
    for side in (field.removeprefix("node_stack_") for field, _ in
                 (entry for entry in config.entries if isinstance(entry, tuple)) if field.startswith("node_stack_")):
        part.add("attN", f"{side}, {piece.connections.get(side, -1)}")
    if index == 0:
        for kerbal in start.crew:
            part.add("crew", kerbal.name)
    binding = start.craft.abort_action(piece)
    for definition in config.children("MODULE"):
        name = definition.values("name")[0]
        module = Node(
            "MODULE",
            name=name,
            isEnabled="True",
            stagingEnabled=definition.values("stagingEnabled")[0]
            if definition.values("stagingEnabled")
            else "True",
        )
        settings = next((setting for setting in piece.settings if setting.values("name") == [name]), None)
        if settings:
            for setting in settings.entries:
                if isinstance(setting, Node):
                    module.child(deepcopy(setting))
                elif setting[0] not in ("name", "isEnabled"):
                    if module.values(setting[0]):
                        module.set(*setting)
                    else:
                        module.add(*setting)
        if name == "ModuleParachute":
            module.add("persistentState", "STOWED").add("animTime", 0)
        elif name == "ModuleEnginesFX":
            enabled = str(piece.kind == start.active_engine).title()
            if piece.stage < 0:
                module.set("stagingEnabled", "False")
            module.add("EngineIgnited", enabled).add("staged", enabled).add("currentThrottle", 0)
        elif name == "ModuleDockingNode":
            module.add("state", "Ready").add("dockUId", 0)
        elif name == "ModuleDeployableSolarPanel" and not module.values("deployState"):
            module.add("deployState", "EXTENDED")
        elif name == "ModuleJettison" and "bottom" not in piece.connections and not module.values("isJettisoned"):
            module.add("isJettisoned", "True")
        elif name == "ModuleProceduralFairing":
            module, area = start.craft.fairing_state(ids)
            part.set("modMass", f"{area * 0.01:.5f}")
            part.set("modCost", f"{area * 8:.3f}")
        if binding and binding[0] == name:
            module.child(
                Node("ACTIONS").child(
                    Node(binding[1], actionGroup="Abort", wasActiveBeforePartWasAdjusted="False")
                )
            )
        part.child(module)
    for tank in loaded_resources(config, piece.propellant_fraction):
        part.child(tank.add("flowState", "True"))
    return part


def vessel_state(start, launch_id, group, epoch, configs):
    craft = start.craft
    name = craft.title
    ids = [stable_number(f"{group}/{name}/{index}") for index, _ in enumerate(craft.pieces)]
    surface = isinstance(start.location, Surface)
    pad = surface and start.location.at_pad
    height = -min(p.position[1] - PARTS[p.kind].height / 2 for p in craft.sizing if p.kind in PARTS)
    altitude = start.location.altitude + (height if pad else 0) if surface else start.location.altitude()
    orbit = start.location.orbit(altitude) if surface else start.location
    last_stage = max(piece.stage for piece in craft.pieces)
    last_stage_is_lit = any(
        piece.kind == start.active_engine and piece.stage == last_stage for piece in craft.pieces
    )
    vessel = Node(
        "VESSEL",
        pid=uuid5(NAMESPACE_URL, f"FAMSeasons/{group}/{name}").hex,
        persistentId=stable_number(f"vessel/{group}/{name}"),
        name=name,
        type=craft.kind,
        sit="PRELAUNCH" if pad else "LANDED" if surface else "ORBITING",
        landed=str(surface).title(),
        skipGroundPositioning="False",
        splashed="False",
        met=0,
        lct=epoch,
        lastUT=epoch,
        root=0,
        lat=start.location.latitude if surface else 0,
        lon=start.location.longitude if surface else 0,
        alt=f"{altitude:.9g}",
        hgt=height if surface else -1,
        nrm="0,1,0",
        rot=start.location.rotation() if surface else "0,0,0,1",
        stg=last_stage if last_stage >= 0 and last_stage_is_lit else last_stage + 1,
        prst="False",
        ref=ids[0],
        ctrl="True",
        altDispState="AGL" if surface else "ASL",
    )
    if pad:
        vessel.add("landedAt", "LaunchPad").add("displaylandedAt", "#autoLOC_6002112").add(
            "launchedFrom", "LaunchPad"
        )
    vessel.child(orbit.node(epoch))
    # MainMenu saves the initial flight before it ever unpacks the vessels.
    vessel.child(Node("ACTIONGROUPS"))
    vessel.child(
        Node(
            "DISCOVERY",
            state=-1,
            lastObservedTime=0,
            lifetime="Infinity",
            refTime="Infinity",
            size=2,
        )
    )
    vessel.child(Node("FLIGHTPLAN"))
    vessel.child(
        Node(
            "CTRLSTATE",
            pitch=0,
            yaw=0,
            roll=0,
            trimPitch=0,
            trimYaw=0,
            trimRoll=0,
            mainThrottle=0,
        )
    )
    vessel.child(Node("VESSELMODULES"))
    stage_counts = Counter()
    for i, piece in enumerate(craft.pieces):
        vessel.child(
            part_state(
                start,
                i,
                launch_id,
                ids,
                stage_counts[piece.stage] if piece.stage >= 0 else -1,
                configs,
            )
        )
        stage_counts[piece.stage] += 1
    return vessel


def scenario_state(scenario, configs):
    game = Node(
        "GAME",
        version="1.12.5",
        Title=scenario.filename,
        Description=scenario.description,
        linkURL="",
        linkCaption="",
        Mode="SCENARIO",
        Status=1,
        Seed=stable_number(scenario.filename) >> 1,
        scene=7,
        editor="None",
        flag=FLAG,
        launchID=len(scenario.flights) + 1,
        modded="True",
    )
    settings = Node("PARAMETERS", preset="Normal")
    settings.child(
        Node(
            "FLIGHT",
            CanQuickSave="True",
            CanQuickLoad="True",
            CanAutoSave="True",
            CanUseMap="True",
            CanSwitchVesselsNear="True",
            CanSwitchVesselsFar="True",
            CanTimeWarpHigh="True",
            CanTimeWarpLow="True",
            CanEVA="True",
            CanIVA="True",
            CanBoard="True",
            CanRestart="True",
            CanLeaveToEditor="False",
            CanLeaveToTrackingStation="True",
            CanLeaveToSpaceCenter="True",
            CanLeaveToMainMenu="True",
        )
    )
    settings.child(
        Node(
            "DIFFICULTY",
            EnableCommNet="False",
            MissingCrewsRespawn="False",
            ReentryHeatScale=1,
        )
    )
    settings.child(
        Node(
            "AdvancedParams",
            EnableKerbalExperience="False",
            ResourceTransferObeyCrossfeed="False",
        )
    )
    game.child(settings)
    state = Node(
        "FLIGHTSTATE",
        version="1.12.5",
        UT=scenario.epoch,
        activeVessel=0,
        mapViewFiltering=-1026,
        commNetUIModeTracking="None",
        commNetUIModeFlight="None",
    )
    roster = Node("ROSTER")
    objectives = Node("SCENARIO", name="FAMScenarioObjectives", scene=7, fleet="modular")
    vessels = {}
    for i, flight in enumerate(scenario.flights, 1):
        vessel = vessel_state(flight_kit(flight), i, scenario.filename, scenario.epoch, configs)
        state.child(vessel)
        vessels[flight.craft.title] = vessel
        for seat_index, kerbal in enumerate(flight.crew):
            roster.child(loadout(kerbal, seat_index))
    for operation in scenario.operations:
        destination = objectives
        if len(scenario.operations) > 1:
            destination = Node("OPERATION")
            objectives.child(destination)
        write_operation(operation, vessels, destination)
    assigned = {kerbal.name for flight in scenario.flights for kerbal in flight.crew}
    for kerbal in SEASON_ONE_CAST:
        if kerbal.name not in assigned:
            roster.child(loadout(kerbal))
    return game.child(state).child(roster).child(objectives)


def write_operation(operation, vessels, node):
    node.add("mission", operation.mission).add("focus", operation.focus).add("milestone", operation.milestone)
    node.add("fromPad", str(operation.from_pad).title()).add("completed", 0)
    node.add("siteLatitude", SITE_LAT).add("siteLongitude", SITE_LON)
    overrides = dict(operation.expected_crew)
    for vessel in operation.vessels:
        for part in vessels[vessel].children("PART"):
            role = OBJECTIVE_ASSETS.get(part.values("name")[0])
            if role:
                asset = Node("ASSET", role=role, partId=part.values("persistentId")[0])
                names = (
                    [member.name for member in overrides[role]] if role in overrides else part.values("crew")
                )
                for name in names:
                    asset.add("crew", name)
                node.child(asset)


def write_scenarios(configs):
    for scenario in scenarios():
        scenario_state(scenario, configs).write(SCENARIOS / (scenario.filename + ".sfs"))
