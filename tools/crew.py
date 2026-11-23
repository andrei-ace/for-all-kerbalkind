"""Kerbal roster profiles for the Season 1 cast and mission crews."""

from dataclasses import dataclass

from config import Node
from parts import SEASON


@dataclass(frozen=True)
class Crew:
    name: str
    trait: str = "Pilot"
    gender: str = "Male"
    courage: float = 0.65
    stupidity: float = 0.25

    @property
    def head(self):
        return f"FAMSeasons/Season1/Crew/Heads/{self.name.split()[0]}"


# Principal characters in Apple's Season 1 cast credits, in mod-created roles.
ED = Crew("Eddwin Kerman", courage=0.95)
GORDO = Crew("Gordo Kerman", courage=0.9, stupidity=0.35)
TRACY = Crew("Tracie Kerman", gender="Female", courage=0.86)
KAREN = Crew("Karrin Kerman", "Scientist", "Female", 0.74, 0.18)
MARGO = Crew("Margo Kerman", "Engineer", "Female", 0.67, 0.08)
ELLEN = Crew("Ellyn Kerman", gender="Female", courage=0.85, stupidity=0.17)
DANIELLE = Crew("Danni Kerman", "Engineer", "Female", 0.88, 0.12)
OCTAVIO = Crew("Oktavio Kerman", "Engineer", courage=0.78, stupidity=0.19)
ALEIDA = Crew("Alayda Kerman", "Engineer", "Female", 0.78, 0.07)
MOLLY = Crew("Mollie Kerman", gender="Female", courage=0.96)
SEASON_ONE_CAST = (
    ED,
    GORDO,
    TRACY,
    KAREN,
    MARGO,
    ELLEN,
    DANIELLE,
    OCTAVIO,
    ALEIDA,
    MOLLY,
)

CAST_ROLES = {
    ED: ("Edward Baldwin", "Test pilot and lunar commander"),
    GORDO: ("Gordo Stevens", "Apollo pilot and Jamestown crew"),
    TRACY: ("Tracy Stevens", "Pilot in the first women astronaut class"),
    KAREN: ("Karen Baldwin", "Civilian operations and crew support"),
    MARGO: ("Margo Madison", "Mission Control flight engineer"),
    ELLEN: ("Ellen Waverly", "Apollo pilot and stranded Apollo 24 survivor"),
    DANIELLE: ("Danielle Poole", "Engineer and Jamestown crewmember"),
    OCTAVIO: ("Octavio Rosales", "Ground operations and maintenance"),
    ALEIDA: ("Aleida Rosales", "Engineering student and future mission controller"),
    MOLLY: ("Molly Cobb", "Test pilot and polar survey astronaut"),
}

# The Apollo 11 and Soviet landing crews have separate historical counterparts.
ALEXEI = Crew("Aleksei Kerman", courage=0.93)
LOK_PILOT = Crew("Lev Kerman")
NEIL = Crew("Niel Kerman", courage=0.91)
BUZZ = Crew("Buz Kerman", "Engineer", courage=0.89)
MICHAEL = Crew("Mikel Kerman", courage=0.82)
WUBBO = Crew("Wubbo Kerman", courage=0.81)


def write_cast():
    root = Node("")
    for kerbal in SEASON_ONE_CAST:
        character, role = CAST_ROLES[kerbal]
        root.child(
            Node(
                "FAM_CHARACTER",
                name=kerbal.name,
                counterpart=character,
                role=role,
                trait=kerbal.trait,
                gender=kerbal.gender,
                brave=kerbal.courage,
                dumb=kerbal.stupidity,
                head=kerbal.head,
            )
        )
    root.write(SEASON / "Crew/Cast.cfg")
