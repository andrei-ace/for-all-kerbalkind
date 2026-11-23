"""Season 1 Mission Control contracts; vessel keys are stable across names and saves."""

from config import Node
from parts import APOLLO, L3, LOGISTICS, SEASON, SHIPS
from config import read_node

GROUP = "FAMSeasonOne"
SOVIET = GROUP + "Soviet"
AMERICAN = GROUP + "American"
AGENCY = "Kerbin World-Firsts Record-Keeping Society"
SITE_LAT, SITE_LON = -77.0, 12.0
BASE = "FAMS1Jamestown"
FERRY = "FAMS1RescueFerry"
OSPREY = "Apollo 24 Osprey"


def parameter(kind, name, title=None, **fields):
    node = Node("PARAMETER", name=name, type=kind, **fields)
    if title:
        node.add("title", title)
    return node


def group(name, title, *conditions, define=None, vessel=None, after=True, duration=None):
    step = parameter(
        "VesselParameterGroup",
        name,
        title,
        completeInSequence=str(after).lower(),
        disableOnStateChange="true",
    )
    if define:
        step.add("define", define)
    if vessel:
        step.add("vessel", vessel)
    if duration:
        step.add("duration", duration)
    for condition in conditions:
        step.child(condition)
    return step


def hardware(part, absent=False):
    node = parameter(
        "PartValidation", part + ("Absent" if absent else "Aboard"), part=part, minCount=int(not absent)
    )
    if absent:
        node.add("maxCount", 0)
    return node


def crew(minimum, maximum=None):
    node = parameter("HasCrew", "Crew", minCrew=minimum)
    if maximum is not None:
        node.add("maxCrew", maximum)
    return node


def state(situation, body="Mun"):
    return parameter("ReachState", situation.title(), targetBody=body, situation=situation)


def stock(name, quantity):
    return parameter("HasResource", name, resource=name, minQuantity=quantity)


def at_site():
    return parameter(
        "VisitWaypoint",
        "AtShackleton",
        "Within 1.2 km of the Shackleton survey marker",
        index=0,
        horizontalDistance=1200,
        hideOnCompletion="false",
    )


def site_marker():
    waypoint = Node(
        "WAYPOINT",
        name="Shackleton survey site",
        targetBody="Mun",
        icon="sample",
        latitude=SITE_LAT,
        longitude=SITE_LON,
        altitude=0,
    )
    return Node("BEHAVIOUR", name="Shackleton", type="WaypointGenerator").child(waypoint)


def docking(name, first, second, title):
    return (
        parameter("Docking", name, title, completeInSequence="true")
        .add("vessel", first)
        .add("vessel", second)
    )


def requirement(kind, name, **values):
    return Node("REQUIREMENT", name=name, type=kind, **values)


def mission(key, title, tech, previous, description, synopsis, completed, advance, reward, science):
    c = Node(
        "CONTRACT_TYPE",
        name=key,
        group=SOVIET if key == "FAMS1RedMun" else AMERICAN,
        title=title,
        agent=AGENCY,
        targetBody="Mun",
        description=description,
        synopsis=synopsis,
        completedMessage=completed,
        maxCompletions=1,
        maxSimultaneous=1,
        minExpiry=0,
        maxExpiry=0,
        deadline=0,
        advanceFunds=advance,
        rewardFunds=reward,
        rewardScience=science,
        rewardReputation=8,
    )
    c.child(requirement("TechResearched", "SeasonResearch", tech=tech))
    if previous:
        c.child(requirement("CompleteContract", "PreviousFlight", contractType=previous))
    craft_names = {
        "FAMS1RedMun": ("N1-L3",),
        "FAMS1Apollo11": ("Saturn V Apollo",),
        "FAMS1JamestownCampaign": ("Apollo 15 Survey", "Jamestown Delivery", "LSAM Delivery"),
    }[key]
    manifest = set()
    for name in craft_names:
        craft = read_node(SHIPS / ("FAM S1 - " + name + ".craft"))
        manifest.update(piece.values("part")[0].rsplit("_", 1)[0] for piece in craft.children("PART"))
    gate = requirement("PartUnlocked", "FlightHardware", checkOnActiveContract="false")
    for part in sorted(manifest):
        gate.add("part", part)
    c.child(gate)
    return c


def moon_landing(soviet):
    if soviet:
        c = mission(
            "FAMS1RedMun",
            "S1.1  Red Mun",
            L3,
            None,
            "The first pilot to step onto the Mun will fly alone for the last few kilometres. Send two in the LOK, then move one into the LK.",
            "Land an LK pilot, redock in Mun orbit and recover both crew on Kerbin.",
            "The LK crew is home after the Soviet landing.",
            40000,
            45000,
            50,
        )
        orbiter, lander, key, landed = "famLOK", "famLK", "FAMS1LOK", 1
    else:
        c = mission(
            "FAMS1Apollo11",
            "S1.2  Apollo 11",
            APOLLO,
            "FAMS1RedMun",
            "Apollo will leave a pilot in the command module while two crewmates take the lunar module to the surface.",
            "Keep the command module in orbit, land two Kerbals and bring all three home.",
            "Apollo is home. The program can now research the survey and habitat hardware.",
            42000,
            48000,
            240,
        )
        orbiter, lander, key, landed = "famApolloCM", "famLMAscent", "FAMS1Columbia", 2
    c.child(requirement("TechResearched", "RecoverySystems", tech="survivability"))
    c.child(requirement("Facility", "LaunchPad", facility="LaunchPad", minLevel=2))
    c.child(requirement("Facility", "EVATraining", facility="AstronautComplex", minLevel=2))
    lander_key = key + "Lander"
    c.child(
        group(
            "Launch",
            "Launch the complete lunar stack into Kerbin orbit",
            parameter("NewVessel", "NewLaunch"),
            hardware(orbiter),
            hardware(lander),
            state("ORBITING", "Kerbin"),
            crew(landed + 1, landed + 1),
            after=False,
        )
    )
    c.child(
        group(
            "ParkOrbiter",
            "Park the crewed orbiter independently in Mun orbit",
            hardware(orbiter),
            hardware(lander, absent=True),
            state("ORBITING"),
            crew(1, 1),
            define=key,
        )
    )
    c.child(
        group(
            "LandCrew",
            "Touch down with the landing crew",
            hardware(lander),
            state("LANDED"),
            crew(landed, landed),
            define=lander_key,
        )
    )
    c.child(group("Ascend", "Return the same lander to Mun orbit", state("ORBITING"), vessel=lander_key))
    c.child(docking("Reunite", key, lander_key, "Dock the returning lander to the waiting orbiter"))
    c.child(
        group(
            "BringThemHome",
            "Recover the return cabin and its full crew on Kerbin",
            hardware(orbiter),
            crew(landed + 1, landed + 1),
            parameter("ReturnHome", "KerbinSurface"),
            parameter("RecoverVessel", "RecoverCabin"),
            vessel=key,
        )
    )
    return c


def core_experiment(recovery):
    return parameter(
        "CollectScience",
        "Core" + recovery,
        targetBody="Mun",
        biome="Polar Crater",
        situation="SrfLanded",
        experiment="famPolarCore",
        recoveryMethod=recovery,
    )


def jamestown_campaign():
    c = mission(
        "FAMS1JamestownCampaign",
        "S1.3  Jamestown Campaign",
        LOGISTICS,
        "FAMS1Apollo11",
        "Survey Shackleton with the Apollo lander and bring the core home. Deliver Jamestown to level ground "
        "with the stairs attached and board through the side airlock. Keep a pilot and fuel in the LSAM for Apollo 24. "
        "Osprey will wait in a stable polar Mun orbit while you build the base.",
        "Survey, establish and crew Jamestown, then rescue Apollo 24 using the same LSAM.",
        "The crew is safe at Jamestown and Osprey has propellant again.",
        135000,
        180000,
        165,
    )
    c.child(requirement("Facility", "AssemblyBuilding", facility="VehicleAssemblyBuilding", minLevel=2))
    c.child(requirement("Facility", "FuelTransfer", facility="ResearchAndDevelopment", minLevel=2))
    c.child(requirement("Facility", "LaunchPad", facility="LaunchPad", minLevel=2))
    c.child(requirement("Facility", "EVATraining", facility="AstronautComplex", minLevel=2))
    c.child(requirement("TechResearched", "RecoverySystems", tech="survivability"))
    c.child(Node("DATA", type="Kerbal", survivor="NewKerbal(Female)", hidden="true"))
    c.child(site_marker())
    target = Node(
        "VESSEL",
        name=OSPREY,
        craftURL="FAMSeasons/Season1/Contracts/Assets/Osprey.craft",
        vesselType="Ship",
        targetBody="Mun",
        owned="true",
    )
    target.child(Node("ORBIT", SMA=295000, ECC=0.16, INC=90, LPE=30, LAN=12, MNA=1.25, EPH=0, REF=2))
    target.child(Node("CREW", name="@/survivor", gender="Female", count=1, addToRoster="true"))
    c.child(Node("BEHAVIOUR", name="SpawnOsprey", type="SpawnVessel").child(target))
    tasks = (
        group(
            "Drill",
            "Drill a core at the Shackleton marker",
            hardware("famIceCorer"),
            state("LANDED"),
            at_site(),
            crew(1),
            core_experiment("None"),
        ),
        core_experiment("Recover"),
        group(
            "LandBase",
            "Land Jamestown upright and powered for 30 seconds",
            hardware("famJamestown"),
            crew(0, 0),
            state("LANDED").add("maxSpeed", 0.5).add("speedMode", "Surface"),
            at_site(),
            parameter("FAMHabitat", "StandUpright", "Habitat axis within 15 degrees of vertical"),
            stock("ElectricCharge", 100),
            define=BASE,
            duration="30s",
        ),
        group(
            "ParkFerry",
            "Park the crewed LSAM with 180 LiquidFuel and 220 Oxidizer",
            hardware("famLSAMCab"),
            hardware("famLSAMDriveTank"),
            hardware("famJamestown", absent=True),
            state("LANDED"),
            crew(2),
            stock("LiquidFuel", 180),
            stock("Oxidizer", 220),
            parameter("Rendezvous", "NearHabitat", vessel=BASE, distance=200),
            define=FERRY,
        ),
        group(
            "StaffBase",
            "Board Jamestown and keep a pilot in the parked LSAM",
            hardware("famJamestown"),
            state("LANDED"),
            at_site(),
            parameter("FAMHabitat", "Resident", "A Kerbal inside the habitat", minimumOccupants=1),
            vessel=BASE,
        ),
        group(
            "Intercept",
            "Reach Osprey in Mun orbit",
            state("ORBITING"),
            parameter("Rendezvous", "NearOsprey", vessel=OSPREY, distance=150),
            vessel=FERRY,
        ),
        docking("DockOsprey", FERRY, OSPREY, "Dock the LSAM with Apollo 24"),
        group(
            "VerifyTransfer",
            "Undock with 18 LiquidFuel and 22 Oxidizer in Osprey",
            hardware("famApolloSMBus"),
            hardware("famLSAMCab", absent=True),
            stock("LiquidFuel", 18),
            stock("Oxidizer", 22),
            state("ORBITING"),
            vessel=OSPREY,
        ),
        group(
            "LandSurvivor",
            "Land beside Jamestown with the rescued Kerbal",
            hardware("famLSAMCab"),
            state("LANDED"),
            at_site(),
            parameter("Rendezvous", "NearBase", vessel=BASE, distance=200),
            parameter("HasCrew", "Survivor", kerbal="@/survivor"),
            vessel=FERRY,
        ),
        group(
            "SafeInside",
            "Board Jamestown with the rescued Kerbal",
            hardware("famJamestown"),
            state("LANDED"),
            at_site(),
            parameter(
                "FAMHabitat",
                "SurvivorInside",
                "The survivor inside the upright habitat",
                minimumOccupants=1,
                occupant="@/survivor",
            ),
            vessel=BASE,
        ),
    )
    sequence = parameter("Sequence", "JamestownOperations", "Survey, establish and rescue")
    for i, task in enumerate(tasks):
        if i:
            sequence.add("hiddenParameter", task.values("name")[0])
        sequence.child(task)
    return c.child(sequence)


def write_contracts():
    folder = SEASON / "Contracts"
    group_config = Node(
        "CONTRACT_GROUP",
        name=GROUP,
        displayName="For All Mankind - Season 1",
        minVersion="2.11.0",
        agent=AGENCY,
        maxSimultaneous=1,
    )
    group_config.child(Node("CONTRACT_GROUP", name=SOVIET, displayName="Soviet Program"))
    group_config.child(Node("CONTRACT_GROUP", name=AMERICAN, displayName="American Program"))
    group_config.write(folder / "Group.cfg")
    contracts = [moon_landing(True), moon_landing(False), jamestown_campaign()]
    for i, c in enumerate(contracts, 1):
        c.write(folder / f"{i:02d}-{c.values('name')[0]}.cfg")
