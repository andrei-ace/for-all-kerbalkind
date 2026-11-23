"""Paint original face textures for the two stock KSP head UV layouts."""

from dataclasses import dataclass
from math import exp, sin
from random import Random

from crew import ALEIDA, DANIELLE, ED, ELLEN, GORDO, KAREN, MARGO, MOLLY, OCTAVIO, TRACY
from parts import ROOT
from PIL import Image, ImageColor, ImageDraw, ImageFilter

SIZE = 512


@dataclass(frozen=True)
class Appearance:
    skin: str
    hair: str
    sweep: int
    hairline: int
    curl: int = 0
    frames: bool = False
    moustache: bool = False


APPEARANCE = {
    ED: Appearance("#bccc80", "#8d6d43", 28, -22),
    GORDO: Appearance("#aabc73", "#5e3526", -19, -5, 4),
    TRACY: Appearance("#c1cc86", "#c39553", 20, 1, 15),
    KAREN: Appearance("#aebb74", "#835637", -8, 0, 6),
    MARGO: Appearance("#bcc88a", "#5a3328", -8, 15, 3, frames=True),
    ELLEN: Appearance("#a7ba7e", "#54372e", 24, 2, 5),
    DANIELLE: Appearance("#74844c", "#332927", 1, 10, 16),
    OCTAVIO: Appearance("#86965c", "#302724", -15, -2, 7, moustache=True),
    ALEIDA: Appearance("#a1ad69", "#352923", 4, -2, 13),
    MOLLY: Appearance("#c1c986", "#604333", -31, 12, 12),
}


def shaded(color, light):
    return tuple(max(0, min(255, round(channel + light))) for channel in color)


def paint(crew, style):
    female = crew.gender == "Female"
    seed = sum(ord(c) for c in crew.name)
    rng = Random(seed)
    skin = ImageColor.getrgb(style.skin)
    hair = ImageColor.getrgb(style.hair)
    eyes = (199, 281) if female else (211, 303)
    eye_height = 222 if female else 267
    jaw = 435 if female else 424

    face = Image.new("RGB", (SIZE, SIZE))
    pixels = []
    for y in range(SIZE):
        jaw_shade = 36 * max(0, (y - jaw + 40) / 40) ** 2
        orbital_y = exp(-(((y - eye_height) / 32) ** 2))
        for x in range(SIZE):
            sockets = sum(exp(-(((x - eye) / 27) ** 2)) for eye in eyes)
            light = 11 * exp(-(((x - 250) / 145) ** 2)) - 27 * orbital_y * sockets
            pixels.append(shaded(skin, light - jaw_shade + rng.uniform(-2, 2)))
    face.putdata(pixels)

    edge = [
        282
        - 119 * exp(-(((x - 249) / 128) ** 4))
        + style.hairline
        + style.sweep * sin((x - 248) / 127)
        + (style.curl / 4) * sin((x + seed) / 9)
        for x in range(SIZE)
    ]
    if female:
        edge = [height - 11 for height in edge]
    hair_mask = Image.new("L", face.size)
    mask = ImageDraw.Draw(hair_mask)
    mask.polygon(
        [
            (0, 0),
            (511, 0),
            *[(x, round(edge[x])) for x in range(511, -1, -4)],
            (0, round(edge[0])),
        ],
        fill=255,
    )
    if female:
        # These separate UV islands are used by the stock female hair meshes.
        mask.rectangle((0, 435, 330, 511), fill=255)
        mask.ellipse((0, 395, 175, 511), fill=255)

    strands = Image.new("RGB", face.size, shaded(hair, -11))
    brush = ImageDraw.Draw(strands)
    for x in range(-90, 604, 2):
        winding = style.curl * rng.uniform(0.45, 1.1)
        points = [
            (round(x + style.sweep * (y / 310) + winding * sin(y / 29 + x / 64)), y)
            for y in range(0, SIZE + 4, 4)
        ]
        brush.line(points, fill=shaded(hair, rng.uniform(-15, 27)), width=rng.choice((1, 1, 2)))
    light = Image.new("L", face.size)
    ImageDraw.Draw(light).ellipse((71, 65, 433, 193), fill=58)
    strands = Image.composite(
        Image.new("RGB", face.size, shaded(hair, 36)),
        strands,
        light.filter(ImageFilter.GaussianBlur(31)),
    )
    face.paste(strands, mask=hair_mask.filter(ImageFilter.GaussianBlur(1.2)))

    art = ImageDraw.Draw(face)
    if female:
        # The mouth is in its own UV island near the right edge.
        art.ellipse((404, 365, 513, 514), fill=(94, 25, 31))
    else:
        art.rectangle((0, 425, 511, 511), fill=(24, 17, 19))
        art.rounded_rectangle((4, 430, 151, 511), radius=38, fill=(113, 39, 46))
        art.rounded_rectangle((156, 431, 368, 511), radius=34, fill=(243, 236, 212))
        art.ellipse((391, 430, 511, 526), fill=(163, 45, 55))
    for x in eyes:
        top = eye_height - (19 if female else 25)
        art.arc((x - 21, top, x + 21, top + 22), 183, 350, shaded(hair, -8), width=4)
        if style.frames:
            art.rounded_rectangle(
                (x - 27, eye_height - 16, x + 27, eye_height + 19),
                radius=9,
                outline=(85, 53, 34),
                width=4,
            )
    if style.frames:
        art.arc((225, 211, 256, 227), 190, 345, fill=(85, 53, 34), width=3)
    if style.moustache:
        art.arc((225, 321, 285, 350), 185, 355, fill=shaded(hair, 15), width=5)
    return face


if __name__ == "__main__":
    for kerbal, appearance in APPEARANCE.items():
        path = ROOT / "GameData" / (kerbal.head + ".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        paint(kerbal, appearance).save(path, optimize=True)
