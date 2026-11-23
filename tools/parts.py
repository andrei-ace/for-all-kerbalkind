"""Season 1 part dimensions in metres, dry tonnes, kN, seconds and KSP funds.

Model coordinates are centred vertically, with the attach planes at ±height/2.
Propellant is given in tonnes of 9:11 liquid fuel and oxidizer.
"""

from dataclasses import dataclass
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "GameData" / "FAMSeasons"
SEASON = PACK / "Season1"
ART = ROOT / "art/season-1/seed"
SHIPS = ROOT / "Ships" / "VAB"


@dataclass(frozen=True)
class Part:
    id: str
    title: str
    role: str
    tech: str
    height: float
    radius: float
    top_radius: float
    dry: float
    cost: int
    description: str
    fuel: float = 0
    thrust: float = 0
    vacuum: int = 0
    sea: int = 0
    engines: int = 0
    crew: int = 0
    internal: str = ""


BOOST = "famMunLaunch"
L3 = "famSovietL3"
APOLLO = "famApollo"
POLAR = "famPolarSurvey"
HAB = "famHabitation"
LOGISTICS = "famMunLogistics"

# The east and west expansion faces in habitat-local KSP axes.
HAB_PORT_X = 2.38
HAB_PORT_Y = -0.15
HAB_PORTS = (("west", -1), ("east", 1))
# The stock Clamp-O-Trons and their bearings seat on these planes.
AIRLOCK_LENGTH = 1.12
AIRLOCK_SIDE = (0, -1.515, HAB_PORT_Y)  # Blender XYZ
REAR_DOCK_SEAT = 1.799
ROOF_DOCK_SEAT = 0.80
DOCK_DEPTH = 0.2828832
END_DOCK_SEAT = HAB_PORT_X - DOCK_DEPTH
STAIR_CLIP = "jamestownStairs"
STAIR_GROUP = "stairs"
STAIR_TREAD_COUNT = 4
STAIR_DURATION = 2.4
STAIR_FOLD = -137  # Blender degrees about the transverse hinge
REVIEW_PAD_Z = 0.05  # frame-local foot plane at zero piston stroke
REVIEW_DOCK_HEIGHT = 1.85
REVIEW_LIFT = 0.75
REVIEW_CARRIER_SEAT = REVIEW_PAD_Z + 0.08
PAD_DEPTH = 0.10
JACK_BOTTOM, JACK_TOP = -0.420726, 0.643867  # stock 1P2 stack faces
JACK_SEAT = REVIEW_PAD_Z + PAD_DEPTH + JACK_TOP - JACK_BOTTOM
JACKS = tuple((x, y, JACK_SEAT) for x in (-1.12, 1.12) for y in (-1.83, 1.83))
SERVO_DEPTH = 0.21796  # stock F-12 flush servo stack height
# The four cradle bells are centered below the tank pods. The foot plane is y = -height/2.
# Horizontal bearing seats. The two end mating faces retain their expansion coordinates.
STATION_SEATS = {
    "west": (-(END_DOCK_SEAT - SERVO_DEPTH), 0, -1, 0),
    "east": (END_DOCK_SEAT - SERVO_DEPTH, 0, 1, 0),
    "rear": (0, REAR_DOCK_SEAT - SERVO_DEPTH, 0, 1),
    "airlock": (0, AIRLOCK_SIDE[1], 0, -1),
}

HAB_BELL_X = 1.49
HAB_BELL_Z = 0.77
HAB_BELL_CLEARANCE = 0.21
# Roof pads take stock surface hardware. The ladder uses the service-side wall.
HAB_SOLAR = (1.10, 0.88, 0.03)
HAB_ANTENNA = (-1.38, 0.88, 0.13)
HAB_LADDER = (0.34, -0.31, 0.90)


@dataclass(frozen=True)
class StockFixture:
    config: str
    model: str
    mass: float
    cost: int
    position: tuple
    rotation: tuple
    attach: tuple
    outward: tuple


HALF_TURN = sqrt(0.5)
HAB_FIXTURES = {
    "solarPanels5": StockFixture(
        "Electrical/radialFlatSolarPanel/radialFlatSolarPanel.cfg",
        "Electrical/radialFlatSolarPanel/model.mu",
        0.005,
        75,
        HAB_SOLAR,
        (-HALF_TURN, 0, 0, HALF_TURN),
        (0, 0, 0),
        (0, 1, 0),
    ),
    "SurfAntenna": StockFixture(
        "Utility/DirectAntennas/C16S.cfg",
        "Utility/DirectAntennas/SurfAntenna.mu",
        0.015,
        300,
        HAB_ANTENNA,
        (0, 0, 0, 1),
        (0, -0.05, 0),
        (0, 1, 0),
    ),
    "ladder1": StockFixture(
        "Utility/ladderRadial/ladderRadial.cfg",
        "Utility/ladderRadial/model.mu",
        0.005,
        100,
        HAB_LADDER,
        (0, HALF_TURN, 0, HALF_TURN),
        (0, 0, 0),
        (0, 0, 1),
    ),
}

CATALOG = [
    Part(
        "famN1A",
        "N1 Block A",
        "n1",
        BOOST,
        6.30,
        1.875,
        1.56,
        4.8,
        9400,
        "Thirty small bells share the work of lifting the tapered N1. The outer ring fires around a second cluster of six.",
        26.5,
        930,
        309,
        287,
        30,
    ),
    Part(
        "famN1B",
        "N1 Block B",
        "n1",
        BOOST,
        4.20,
        1.56,
        1.25,
        2.55,
        4900,
        "An eight-engine second stage with an open lattice interstage.",
        10.9,
        375,
        335,
        282,
        8,
    ),
    Part(
        "famN1V",
        "N1 Block V",
        "n1",
        BOOST,
        2.80,
        1.25,
        0.94,
        1.14,
        2900,
        "The four-engine upper stage completes ascent carrying the lunar train.",
        4.2,
        149,
        344,
        268,
        4,
    ),
    Part(
        "famBlockG",
        "L3 Block G Transfer Stage",
        "n1",
        L3,
        2.50,
        0.94,
        0.94,
        0.70,
        1900,
        "A restartable transfer stage for departure from Kerbin and insertion into Mun orbit.",
        2.9,
        75,
        352,
        240,
        1,
    ),
    Part(
        "famSaturnIC",
        "Saturn V S-IC",
        "saturn",
        BOOST,
        7.20,
        1.875,
        1.875,
        5.40,
        10400,
        "Five bell engines and the black roll pattern mark the first stage of the Saturn V.",
        38,
        1090,
        306,
        283,
        5,
    ),
    Part(
        "famSaturnII",
        "Saturn V S-II",
        "saturn",
        BOOST,
        4.65,
        1.875,
        1.25,
        2.7,
        5400,
        "A five-engine upper stage with a tapered forward interstage.",
        13.8,
        470,
        349,
        245,
        5,
    ),
    Part(
        "famSaturnIVB",
        "Saturn V S-IVB",
        "saturn",
        BOOST,
        3.40,
        1.25,
        1.25,
        1.30,
        3100,
        "Its single restartable engine can finish a parking orbit and send the payload to the Mun.",
        6.8,
        144,
        354,
        238,
        1,
    ),
    Part(
        "famRing375",
        "LV-375 Separation Ring",
        "ring",
        BOOST,
        0.18,
        1.875,
        1.875,
        0.16,
        270,
        "A 3.75 m separation joint. The arrow side releases on staging.",
    ),
    Part(
        "famRing250",
        "LV-250 Separation Ring",
        "ring",
        BOOST,
        0.16,
        1.25,
        1.25,
        0.10,
        160,
        "A lightweight 2.5 m separation joint for payloads and upper stages.",
    ),
    Part(
        "famRing125",
        "LV-125 Separation Ring",
        "ring",
        BOOST,
        0.13,
        0.625,
        0.625,
        0.045,
        90,
        "A compact separation ring for crew ships and lander ascent stages.",
    ),
    Part(
        "famPayloadAdapter",
        "Mun Payload Adapter",
        "adapter",
        BOOST,
        0.88,
        1.25,
        0.88,
        0.19,
        520,
        "A load-bearing truss with a configurable clamshell fairing. Stage in vacuum to release both the panels and the payload.",
    ),
    Part(
        "famLaunchTower",
        "Crew Escape Tower",
        "tower",
        BOOST,
        2.35,
        0.44,
        0.08,
        0.24,
        650,
        "An abort-only escape motor above a lattice tower. On a normal ascent, staging releases the tower with its separator.",
    ),
    Part(
        "famLOK",
        "L3 LOK Orbital Cabin",
        "lok",
        L3,
        1.90,
        0.94,
        0.41,
        1.18,
        2100,
        "Two seats, an orbital compartment, a nose docking port and an ablative return shell. Fit parachutes before launch.",
        crew=2,
        internal="mk1CabinInternal",
    ),
    Part(
        "famLOKService",
        "L3 LOK Service Section",
        "service",
        L3,
        1.75,
        0.94,
        0.94,
        0.56,
        1200,
        "Electrical supply and orbital propulsion for the LOK. Separate at the return cabin's ring before entry.",
        0.92,
        20,
        342,
        195,
        1,
    ),
    Part(
        "famLK",
        "L3 LK Single-Pilot Lander",
        "lk",
        L3,
        1.56,
        0.70,
        0.36,
        0.56,
        1450,
        "A single pilot flies under the spherical pressure shell. A separate ascent engine returns the cabin to the LOK.",
        0.26,
        7,
        333,
        184,
        1,
        1,
        "landerCabinSmallInternal",
    ),
    Part(
        "famLKPlatform",
        "L3 LK Braking and Landing Frame",
        "lkframe",
        L3,
        1.12,
        0.83,
        0.68,
        0.38,
        950,
        "A stock-scale combined braking stage and four-foot landing frame for the LK.",
        0.57,
        12,
        335,
        168,
        1,
    ),
    Part(
        "famApolloCM",
        "Apollo Command Module",
        "cm",
        APOLLO,
        1.65,
        1.25,
        0.48,
        1.75,
        2850,
        "A three-seat return capsule with a nose docking collar and built-in ablative shield. Fit two radial parachutes.",
        crew=3,
        internal="Mk1-3",
    ),
    Part(
        "famApolloSM",
        "Apollo Service Module",
        "service",
        APOLLO,
        2.25,
        1.25,
        1.25,
        0.85,
        1700,
        "A deep-throttling service engine, electrical supply and reserve propellant for the return to Kerbin.",
        1.25,
        26,
        345,
        198,
        1,
    ),
    Part(
        "famLMAscent",
        "Apollo LM Ascent Stage",
        "lm",
        APOLLO,
        1.52,
        0.90,
        0.42,
        0.87,
        1850,
        "Two pilots stand behind the forward windows. The ascent engine lifts the cabin off the descent platform.",
        0.38,
        10,
        341,
        188,
        1,
        2,
        "landerCabinInternals",
    ),
    Part(
        "famLMDescent",
        "Apollo LM Descent Stage",
        "lmframe",
        APOLLO,
        1.15,
        1.08,
        0.80,
        0.65,
        1200,
        "Foil blankets cover an octagonal descent stage with four wide landing pads.",
        0.84,
        18.5,
        342,
        170,
        1,
    ),
    Part(
        "famIceCorer",
        "Shackleton Polar Core Sampler",
        "corer",
        POLAR,
        0.46,
        0.19,
        0.16,
        0.045,
        240,
        "A surface-mounted auger that stores one physical core. Carry the core back to Kerbin for the expedition.",
    ),
    Part(
        "famJamestown",
        "Jamestown Habitat",
        "hab",
        HAB,
        2.70,
        1.25,
        0.91,
        2.75,
        4800,
        "A four-berth shelter with a side airlock, probe control and two horizontal Clamp-O-Tron expansion ports.",
        crew=4,
        internal="crewCabinInternals",
    ),
    Part(
        "famHabCradle",
        "Jamestown Landing Platform",
        "cradle",
        HAB,
        1.40,
        1.35,
        1.25,
        1.12,
        1950,
        "Four landing engines and wide, fixed feet support the habitat. Leave the platform and airlock stairs attached after touchdown.",
        1.55,
        28,
        346,
        185,
        4,
    ),
    Part(
        "famLSAMCab",
        "LSAM Flight Deck",
        "lsam",
        LOGISTICS,
        1.82,
        1.04,
        0.50,
        1.18,
        2500,
        "A three-seat reusable ferry cabin with wide landing windows, a stock-compatible nose port and a roof array.",
        crew=3,
        internal="Mk1-3",
    ),
    Part(
        "famLSAMDrive",
        "LSAM Reusable Propulsion Deck",
        "lsamframe",
        LOGISTICS,
        1.52,
        1.15,
        0.98,
        0.85,
        1900,
        "Four engines feed from exposed serviceable tanks. This propulsion deck stays with the ferry on ascent.",
        2.70,
        39,
        351,
        198,
        4,
    ),
    Part(
        "famRescueTank",
        "LSAM Rescue Reserve",
        "reserve",
        LOGISTICS,
        0.36,
        0.99,
        0.98,
        0.15,
        280,
        "A small stackable tank for the LSAM's rescue load. Transfer fuel and oxidizer through the docking collar.",
        0.45,
    ),
]

PARTS = {part.id: part for part in CATALOG}
CAPSULES = {"cm", "lok"}
CREWED_LANDERS = {"lk", "lm", "lsam"}
FRAMES = {"lkframe", "lmframe", "cradle", "lsamframe"}
DOCKING = CAPSULES | CREWED_LANDERS | {"hab"}
