"""Draw the Season 1 fleet and animated intro from the packaged VAB craft and scenarios.

Requires Pillow, NumPy, ffmpeg, a C compiler, and a licensed KSP + Breaking Ground install.
Example: python3 tools/preview.py --ksp-root /path/to/KSP
"""

import argparse
import ctypes
import filecmp
from fnmatch import fnmatchcase
from functools import lru_cache
from math import cos, pi, sin
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from parts import ROOT
from preview_geometry import Fleet, key, rotation, transform, unit, value

W, H, AA = 944, 512, 2
FRAMES, OVERLAP = 78, 7
Y, X = np.mgrid[:H, :W]


@lru_cache
def font(size, bold=False, title=False):
    mac = Path("/System/Library/Fonts")
    family = mac / ("Supplemental/DIN Alternate Bold.ttf" if title else "Avenir Next.ttc")
    if family.is_file():
        return ImageFont.truetype(str(family), size, index=2 if bold and not title else 0)
    return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold or title else "DejaVuSans.ttf", size)


def axis_rot(axis, angle):
    xyz = [0.0, 0.0, 0.0]
    xyz[axis] = sin(angle / 2)
    return rotation((*xyz, cos(angle / 2)))


def load_raster(work):
    target = work / "raster.so"
    subprocess.run(["cc", "-O3", "-dynamiclib" if sys.platform == "darwin" else "-shared",
                    "-fPIC", str(Path(__file__).with_name("preview_raster.c")), "-o", str(target)], check=True)
    painter = ctypes.CDLL(str(target)).paint
    painter.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                        ctypes.c_int, ctypes.c_int]
    painter.restype = None
    return painter


def load_fleet(release, game):
    global n1, saturn, cargo, lk, eagle, columbia, falcon, hab, lsam, osprey, port_heights
    fleet = Fleet(release, game)
    red = fleet.scenario(1)["Red Mun"]
    apollo = fleet.scenario(2)["Apollo 11"]
    campaign = fleet.scenario(3)
    n1 = fleet.craft(red)
    saturn = fleet.craft(apollo)
    cargo = fleet.craft(fleet.vab("Jamestown Delivery"))
    outpost = fleet.vab("Jamestown Outpost")
    names = [key(p) for p in outpost.children("PART")]
    if names.count("dockingPort2") < 4 or names.count("liquidEngineMini_v2") != 4:
        raise ValueError("Jamestown needs its four stock Sparks and lateral docking stations")
    hab = fleet.craft(outpost, origin="famJamestown")
    parts = red.children("PART")
    cabin = next(i for i, p in enumerate(parts) if key(p) == "famLK")
    frame = next(i for i, p in enumerate(parts) if key(p) == "famLKPlatformFrame")
    keep = {cabin, int(value(parts[frame], "parent"))}
    keep.update(i for i, p in enumerate(parts) if key(p).startswith("famLKPlatform"))
    lk = fleet.craft(red, keep, origin="famLK")
    eagle_index = next(i for i, p in enumerate(apollo.children("PART")) if key(p) == "famLMAscent")
    eagle = fleet.craft(apollo, {eagle_index}, origin="famLMAscent")
    apollo_parts = apollo.children("PART")
    service = {i for i, part in enumerate(apollo_parts)
               if key(part) in ("famApolloCM", "famApolloSMBus", "famApolloSMMotor", "parachuteRadial")}
    service.add(next(i for i, p in enumerate(apollo_parts) if key(p) == "famRing250" and value(p, "parent") == "0"))
    columbia = fleet.craft(apollo, service, origin="famApolloCM")
    falcon = fleet.craft(campaign["Falcon"], origin="famLMAscent")
    lsam = fleet.craft(campaign["LSAM"], origin="famLSAMCab")
    osprey = fleet.craft(campaign["Apollo 24 Osprey"], origin="famApolloCM")
    port_heights = {k: float(value(fleet.configs[k][1], "node_stack_top").split(",")[1])
                    for k in ("famLSAMCab", "famApolloCM", "famLMAscent")}
    return fleet


def on_floor(mesh):
    return -min(pts[..., 1].min() for pts, _, _, _ in mesh)


def posed(mesh, origin, angle=None, pivot=(0, 0, 0)):
    r = np.eye(3) if angle is None else angle
    return [( transform(points - pivot, r) + origin, uv, transform(normals, r), tex)
            for points, uv, normals, tex in mesh]


class Camera:
    def __init__(self, eye, center, scale):
        self.eye = unit(eye)
        self.right = unit(np.cross(self.eye, (0, 1, 0)))
        self.up = np.cross(self.right, self.eye)
        self.matrix = np.column_stack((self.right, -self.up, self.eye))
        self.center = np.array([*center, 0])
        self.scale = np.array([scale, scale, 1])

    def screen(self, pts):
        return transform(pts, self.matrix.T) * self.scale + self.center

    def render(self, batches, sun, size=(W, H)):
        width, height = size
        light = unit(sun)
        out = np.zeros((height * AA, width * AA, 4), dtype=np.uint8)
        z = np.full(out.shape[:2], -np.inf, dtype=np.float32)
        for pts, uv, normals, tex in batches:
            px = self.screen(pts)
            px[..., :2] *= AA
            triangles = np.ascontiguousarray(np.concatenate((px, uv), axis=-1), dtype=np.float32)
            tint = np.ascontiguousarray(
                .41 + .58 * np.maximum(0, np.einsum("ij,j->i", normals, light)) + .12 * np.maximum(0, np.einsum("ij,j->i", normals, self.eye)),
                dtype=np.float32
            )
            raster(out.ctypes.data, z.ctypes.data, width * AA, height * AA, triangles.ctypes.data,
                   tint.ctypes.data, len(tint), tex.ctypes.data, tex.shape[1], tex.shape[0])
        return Image.fromarray(out).resize(size, Image.Resampling.LANCZOS)


def noise(seed, levels, strength=.53):
    rng = np.random.default_rng(seed)
    field = np.zeros((H, W), np.float32)
    amplitude = 1
    for size in levels:
        patch = Image.fromarray(rng.integers(0, 256, (size, size * 2), dtype=np.uint8))
        field += amplitude * (np.asarray(patch.resize((W, H), Image.Resampling.BICUBIC)) / 255 - .5)
        amplitude *= strength
    return field


def disc(canvas, cx, cy, radius, world, seed):
    rx, ry = (X - cx) / radius, (Y - cy) / radius
    r2 = rx * rx + ry * ry
    mask = np.clip((1 - np.sqrt(r2)) * radius + 0.3, 0, 1)[..., None]
    normal = np.sqrt(np.maximum(0, 1 - r2))
    illumination = np.clip(-rx * .48 - ry * .59 + normal * .63, .06, 1)
    texture_field = noise(seed, (7, 15, 34, 77))
    if world == "mun":
        surface = np.array((133, 144, 150)) + texture_field[..., None] * 105
        surface = surface * (0.22 + .78 * illumination[..., None])
    else:
        tide = np.clip((texture_field + .027) * 15, 0, 1)[..., None]
        land = np.array((98, 116, 87))
        water = np.array((29, 84, 124))
        surface = land * tide + water * (1 - tide)
        cloud = np.clip(noise(seed + 1, (11, 28, 58, 120)) * 2.4 - .04, 0, .8)[..., None]
        surface = surface * (1 - cloud) + np.array((201, 213, 209)) * cloud
        surface *= (0.24 + .85 * illumination[..., None])
        surface += (1 - normal[..., None]) ** 5 * np.array((14, 31, 47))
    canvas[:] = canvas * (1 - mask) + surface * mask


def baseplate(phase):
    seed = phase + 11
    launch = phase in (0, 2)
    surface = phase in (1, 4)
    w = np.exp(-(((X - 704) / 480) ** 2 + ((Y - (410 if launch else 230)) / 371) ** 2))
    base = np.array((5, 11, 20)) + w[..., None] * (np.array((28, 52, 66)) if launch else np.array((12, 23, 37)))
    if launch:
        a = np.clip((Y - 187) / 240, 0, 1) ** 1.4
        glow = np.exp(-((X - 770) / 540) ** 2) * a
        colors = np.array((85, 67, 44)) if phase == 0 else np.array((79, 58, 47))
        base += glow[..., None] * colors
        clouds = noise(22 + phase, (6, 13, 30, 62), .39)
        atmospheric = np.clip(clouds * .58 - .025, 0, 1) * np.exp(-((Y - 335) / 87) ** 2)
        base += atmospheric[..., None] * np.array((66, 78, 76))
    elif surface:
        disc(base, 826 if phase == 1 else 846, 105, 26 if phase == 1 else 34, "kerbin", seed)
    else:
        disc(base, 876 if phase == 3 else 891, 640, 288 if phase == 3 else 315, "mun", seed)
        if phase == 5:
            disc(base, 833, 95, 36, "kerbin", seed + 10)

    img = Image.fromarray(np.uint8(np.clip(base, 0, 255))).convert("RGBA")
    brush = ImageDraw.Draw(img)
    rng = np.random.default_rng(20 + phase)
    if not launch:
        for x, y, c, size in zip(rng.integers(315, W, 114), rng.integers(12, H - 82, 114),
                                  rng.integers(48, 163, 114), rng.random(114)):
            if img.getpixel((int(x), int(y)))[0] > 31:
                continue
            brush.ellipse((x, y, x + (1 if size > .78 else 0), y + (1 if size > .78 else 0)),
                          fill=(c, min(255, c + 8), min(255, c + 20), 255))
    if launch:
        brush.polygon([(0,394),(164,403),(331,391),(454,400),(590,386),(738,407),(818,395),(944,391),(944,H),(0,H)],
                      fill=(25, 34, 40, 255))
        brush.polygon([(0,431),(351,434),(580,420),(802,429),(944,414),(944,H),(0,H)],fill=(19,28,32,255))
        brush.polygon([(463,H),(611,426),(741,426),(858,H)],fill=(39,44,45,255))
        brush.polygon([(572,451),(601,435),(742,435),(775,451),(759,460),(589,460)],fill=(74,72,63,255))
        brush.polygon([(589,460),(759,460),(767,472),(581,472)],fill=(48,47,45,255))
        for y in range(459, 499, 8):
            offset = (y - 434) * .3
            brush.line((637-offset, y, 695+offset, y),fill=(36,39,39,255),width=1)
        for i in range(6):
            x = 519 + 52 * i
            y = 484 - int(20*sin(i*.8))
            brush.line((x, y, x, y-12),fill=(41,45,48,255),width=2)
            brush.point((x,y-12),fill=(209,141,74,255))
    if surface:
        ridge = [(int(x), int(367 + 8*sin(x/94)+9*sin(x/168+phase)+4*sin(x/30))) for x in range(0,W+4,4)]
        brush.polygon([*ridge,(W, H),(0,H)],fill=(51,54,58,255))
        brush.polygon([(0,404),(367,398),(617,402),(838,395),(W,382),(W,H),(0,H)],fill=(67,66,69,255))
        for _ in range(175):
            y = rng.uniform(389, H + 2)
            x = rng.uniform(323, W)
            s = .12 + (y-385)/145
            r = rng.uniform(1.2,10.4)*s
            g = int(rng.uniform(50,85))
            brush.polygon([(x-r,y),(x-r*.19,y-r*.28),(x+r,y-r*.08),(x+r*.80,y+r*.18)],
                          fill=(g,g-1,g+2,255))
        for cx,cy,rx,ry in ((854,448,62,13),(455,478,54,15),(595,423,30,6),(722,495,51,8)):
            brush.ellipse((cx-rx,cy-ry,cx+rx,cy+ry),fill=(82,78,78,255))
            brush.ellipse((cx-rx+2,cy-ry+2,cx+rx-2,cy+ry*.66),fill=(50,51,54,255))
            brush.ellipse((cx-rx+13,cy-ry+6,cx+rx-5,cy+ry*.67),fill=(62,61,62,255))
    return img


def tint_panel(img):
    dark = np.zeros((H,W,4), dtype=np.uint8)
    fade = np.clip((394 - X) / 130, 0, 1)
    dark[..., :3] = (8,15,24)
    dark[..., 3] = np.uint8(223 * fade)
    img.alpha_composite(Image.fromarray(dark))


@lru_cache
def caption(phase, section="all"):
    mission, program, subject, action, hardware = STORY[phase]
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    ink = (241,239,228)
    soft = (167,191,198)
    accent = (232,157,119) if program.startswith("SOVIET") else (128,205,205)
    if section in ("all", "heading"):
        d.rectangle((37, 80, 75, 82), fill=accent)
        d.text((38,98), program, font=font(14, bold=True), fill=accent)
        title_font = font(54, title=True)
        for i, line in enumerate(mission):
            d.text((35,124+52*i), line, font=title_font, fill=ink)
        d.line((38,452,227,452),fill=(59,80,87),width=1)
        d.text((38,465), "FOR ALL KERBALKIND", font=font(11, bold=True), fill=(149,165,167))
    if section in ("all", "details"):
        d.text((38, 270), subject, font=font(25, bold=True), fill=ink)
        d.text((39,314), action, font=font(17), fill=soft, spacing=6)
        d.text((39, 380), hardware, font=font(13, bold=True), fill=accent)
    return layer


def transition_frame(phase, following, step, plates):
    weight = ease((step + 1) / (OVERLAP + 1))
    outgoing = make_frame(phase, FRAMES - OVERLAP + step, plates[phase], title=False)
    incoming = make_frame(following, step, plates[following], title=False)
    frame = Image.blend(outgoing, incoming, weight).convert("RGBA")
    same_mission = STORY[phase][0] == STORY[following][0]
    if same_mission:
        frame.alpha_composite(caption(phase, "heading"))
    target = phase if weight < .5 else following
    labels = caption(target, "details" if same_mission else "all").copy()
    opacity = abs(2*weight - 1)
    labels.putalpha(labels.getchannel("A").point(lambda sample: round(sample*opacity)))
    frame.alpha_composite(labels)
    return frame.convert("RGB")

def shadow(img, x, y, width, height, opacity=105):
    layer = Image.new("RGBA", img.size)
    ImageDraw.Draw(layer).ellipse((x-width,y-height,x+width,y+height), fill=(9,13,18,opacity))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(max(3,height*.48))))


def exhaust(img,x,y,amount,frame,wide=False):
    if amount < .03:
        return
    layer=Image.new("RGBA", img.size)
    d=ImageDraw.Draw(layer)
    r = (25 if wide else 10) * amount
    height = (82 if wide else 58) * amount * (.97 + .03*sin(frame*1.5))
    d.ellipse((x-r*1.25,y-4,x+r*1.25,y+height),fill=(251,111,58,150))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(11 if wide else 7)))
    plume=Image.new("RGBA", img.size)
    d=ImageDraw.Draw(plume)
    d.polygon([(x-r*.47,y-2),(x+r*.47,y-2),(x+r*.29,y+height*.52),
               (x+sin(frame*1.1)*r*.08,y+height),(x-r*.26,y+height*.43)],
              fill=(255,167,92,207))
    d.ellipse((x-r*.36,y-3,x+r*.36,y+height*.54),fill=(255,230,167,235))
    d.ellipse((x-r*.17,y-1,x+r*.17,y+height*.38),fill=(255,251,214,240))
    img.alpha_composite(plume.filter(ImageFilter.GaussianBlur(1.8)))
    if wide:
        smoke=Image.new("RGBA",img.size)
        d=ImageDraw.Draw(smoke)
        for j in range(14):
            u = ((j/14 + frame*.008) % 1)
            sx = (-1 if j%2==0 else 1) * (12 + 61*u + (j//2)*4)
            sy = 450 + 11*sin(j*1.4+frame*.13)
            radius = (10+20*u)*amount
            d.ellipse((x+sx-radius,sy-radius*.54,x+sx+radius,sy+radius*.54),
                      fill=(186,161,131,int(68*amount*(sin(pi*u)**0.8))))
        img.alpha_composite(smoke.filter(ImageFilter.GaussianBlur(8)))


def ease(x):
    x = min(1,max(0,x))
    return x**3 * (10 + x * (-15 + 6*x))


STORY = (
    (("Red Mun",), "SOVIET PROGRAM", "N1-L3", "Lift off from Kerbin", "Blocks A, B & V  ·  L3 lunar train"),
    (("Red Mun",), "SOVIET PROGRAM", "LK lander", "Touch down on the Mun", "LK ascent cabin  ·  landing frame"),
    (("Apollo 11",), "AMERICAN PROGRAM", "Saturn V", "Launch Columbia and Eagle", "S-IC  ·  S-II  ·  S-IVB"),
    (("Apollo 11",), "AMERICAN PROGRAM", "Eagle & Columbia", "Rendezvous in Mun orbit", "LM ascent stage  ·  command & service modules"),
    (("Jamestown","Campaign"), "AMERICAN PROGRAM", "Jamestown outpost", "Land a permanent base near\nShackleton crater", "Four docking stations  ·  detachable airlock"),
    (("Jamestown","Campaign"), "AMERICAN PROGRAM", "LSAM & Osprey", "Refuel Apollo 24 and\nrescue its pilot", "LSAM propulsion deck  ·  Apollo service module"),
)


def make_frame(phase, f, plate, title=True):
    tick = f/(FRAMES-1)
    t = ease((tick-.08)/.86)
    plume_time = tick * 33
    img = plate.copy()
    sunlight = (-.36,.64,-.88)
    if phase in (0, 2):
        ship = n1 if phase==0 else saturn
        y = on_floor(ship)
        cam = Camera((.52,.08,-1), (662,447), 12.1)
        climb = 0.05 + ease((tick-.16)/.82)*3.0
        placed = posed(ship,(0,y+climb,0), axis_rot(1,(.55+.12*t) if phase==0 else (-.14+.21*t)))
        flame = ease((tick-.04)/.24)
        px,py,_ = cam.screen((0,climb,.12))
        exhaust(img,px,py,flame,plume_time,True)
    elif phase == 1:
        cam = Camera((.56,.33,-1), (661,435), 81.0)
        altitude = .05 + (1-t)*1.04
        placed = posed(lk,(0,on_floor(lk)+altitude,0),axis_rot(1,.08-.31*t))
        shadow(img,646,439,91,17,130)
        px,py,_ = cam.screen((0,altitude+.18,0))
        exhaust(img,px,py,(1-ease((tick-.72)/.25))*.72,plume_time)
    elif phase == 4:
        cam = Camera((-1.35,.63,-.76), (685,410), 55)
        placed = posed(hab, (0, on_floor(hab), 0), axis_rot(1, -.06 + .23*t))
        shadow(img, 659, 419, 156, 24)
    else:
        left,right,ln,rn,render_scale = ((columbia,eagle,"famApolloCM","famLMAscent",75.0) if phase==3
                                   else (lsam,osprey,"famLSAMCab","famApolloCM",53.0))
        cam = Camera((-.32 + .16*t,.27,-1), (692,235) if phase == 3 else (683,235), render_scale)
        gap = .035 + (1-t)*1.35
        lrot = axis_rot(1,-.04) @ axis_rot(2,-pi/2)
        rrot = axis_rot(1,-.04) @ axis_rot(2,pi/2)
        if phase == 3:
            lrot = lrot @ axis_rot(1, 3.50)
        else:
            rrot = rrot @ axis_rot(1, 3.15)
        placed = posed(left,(-gap/2,0,0),lrot,(0,port_heights[ln],0))
        placed += posed(right,(gap/2,0,0),rrot,(0,port_heights[rn],0))
    img.alpha_composite(cam.render(placed,sunlight))
    tint_panel(img)
    if title:
        img.alpha_composite(caption(phase))
    return img.convert("RGB")


def fit_sprite(mesh, eye, size, padding=12, scale=None):
    camera = Camera(eye, (0, 0), 1)
    projected = [camera.screen(pts).reshape(-1, 3)[:, :2] for pts, _, _, _ in mesh]
    points = np.vstack(projected)
    lo, hi = points.min(axis=0), points.max(axis=0)
    scale = scale or min((np.array(size) - 2 * padding) / np.maximum(hi - lo, .01))
    center = np.array(size) / 2 - (lo + hi) * scale / 2
    return Camera(eye, center, scale).render(mesh, (-.56,.78,-.73), size)


def fleet_plate():
    size = (1680, 960)
    plate = Image.new("RGB", size, (15, 26, 37))
    draw = ImageDraw.Draw(plate)
    cream, muted, teal = (238, 238, 223), (169, 190, 196), (128, 205, 205)
    draw.text((60, 39), "FOR ALL KERBALKIND", font=font(18, bold=True), fill=teal)
    draw.text((57, 67), "Season 1 flight hardware", font=font(55, title=True), fill=cream)
    draw.line((60, 152, 1620, 152), fill=(69, 91, 104), width=2)
    draw.text((60, 176), "Launch vehicles", font=font(30, bold=True), fill=cream)
    draw.text((833, 176), "Mun spacecraft", font=font(30, bold=True), fill=cream)
    draw.line((789, 184, 789, 896), fill=(55, 74, 86))
    launchers = [(n1, "N1-L3", "Soviet lunar train"), (saturn, "Saturn V", "Apollo crew stack"),
                 (cargo, "Saturn V", "Jamestown delivery")]
    for i, (mesh, label, role) in enumerate(launchers):
        x = 51 + 243 * i
        bottom = 781
        centered = posed(mesh, (0, on_floor(mesh), 0))
        eye = (.50,.048,-1)
        camera = Camera(eye, (112, bottom-223), 20.0)
        # Use one physical scale and the same pad datum for all three launchers.
        sprite = camera.render(centered, (-.59,.68,-.76), (225, 585))
        plate.paste(sprite, (x, 223), sprite)
        draw.line((x+16, bottom+14,x+213,bottom+14),fill=(68, 86, 95))
        draw.text((x+15, bottom+31), label, font=font(29, bold=True), fill=cream)
        draw.text((x+16, bottom+74), role, font=font(20), fill=muted)
    spacecraft = [
        (lk, "LK lander", "Single-seat Mun landing", (.58,.34,-1)),
        (falcon, "Falcon", "Apollo 15 survey lander", (.55,.35,-1)),
        (posed(columbia, (0,0,0), axis_rot(2,-.42) @ axis_rot(1,3.50)), "Columbia", "Command and service ship", (-.89,-.20,-1)),
        (hab, "Jamestown", "Expandable polar outpost", (-1.35,.63,-.76)),
        (lsam, "LSAM", "Lunar surface access module", (.59,.37,-1)),
    ]
    for i, (mesh, label, role, view) in enumerate(spacecraft):
        x, y = (835 + i*261, 247) if i < 3 else (835 + (i-3)*408, 569)
        width = 237 if i < 3 else 358
        sprite = fit_sprite(mesh, view, (width, 196), 6)
        plate.paste(sprite, (x, y), sprite)
        draw.line((x, y+211, x+width, y+211), fill=(68, 86, 95))
        draw.text((x, y+222), label, font=font(28, bold=True), fill=cream)
        draw.text((x, y+261), role, font=font(17), fill=muted)
    return plate


def render_banners(fleet):
    folder = ROOT / "saves/scenarios/banners"
    for number, title in enumerate(("Red Mun", "Apollo 11", "Jamestown Campaign"), 1):
        groups = [fleet.craft(v) for v in fleet.scenario(number).values()]
        image = Image.new("RGB", (322,120), (24,35,47))
        draw = ImageDraw.Draw(image)
        draw.ellipse((-34,96,356,220), fill=(83,92,98))
        width = image.width // len(groups)
        for i, mesh in enumerate(groups):
            sprite = fit_sprite(mesh, (.5,.22,-1), (width,118), 4)
            image.paste(sprite, (i*width,0), sprite)
        image.save(folder / f"FAM S1.{number} - {title}.png")


def unpack_fleet(archive_path, destination):
    # A review can target a historical release explicitly. The current build must match the checkout.
    parts = "GameData/FAMSeasons/Season1/Parts"
    patterns = (f"{parts}/*.cfg", f"{parts}/*.mu", f"{parts}/*.png", f"{parts}/*.dds",
                "Ships/VAB/FAM S1 - *.craft", "saves/scenarios/FAM S1.*.sfs")
    canonical = archive_path.resolve() == (ROOT / "dist/FAMSeasons.zip").resolve()
    with ZipFile(archive_path) as archive:
        inputs = {name for name in archive.namelist()
                  if not name.endswith("/") and any(fnmatchcase(name, pattern) for pattern in patterns)}
        if canonical:
            expected = {p.relative_to(ROOT).as_posix() for pattern in patterns for p in ROOT.glob(pattern) if p.is_file()}
            if expected != inputs:
                raise ValueError(f"Rebuild dist/FAMSeasons.zip before rendering. Different fleet inputs: {sorted(expected ^ inputs)}")
        for name in sorted(inputs):
            path = archive.extract(name, destination)
            if canonical and not filecmp.cmp(path, ROOT / name, shallow=False):
                raise ValueError(f"Rebuild dist/FAMSeasons.zip before rendering. Outdated fleet input: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=ROOT / "dist/FAMSeasons.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "docs")
    parser.add_argument("--work", type=Path, help="Retain the PNG frames and diagnostic views")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--proof", action="store_true", help="Write a six-scene contact sheet")
    modes.add_argument("--scenarios", action="store_true", help="Render the stock scenario menu banners")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="fam-preview-") as scratch:
        work = (args.work or Path(scratch)).resolve()
        work.mkdir(parents=True, exist_ok=True)
        # Always start from a fresh manifest, even when retaining frame diagnostics.
        with TemporaryDirectory(prefix="release-", dir=work) as unpack:
            release = Path(unpack)
            unpack_fleet(args.archive, release)
            global raster
            raster = load_raster(work)
            fleet = load_fleet(release, args.ksp_root.resolve())
            if args.scenarios:
                render_banners(fleet)
                return
            plate = fleet_plate()
            plates = [baseplate(i) for i in range(len(STORY))]
            if args.proof:
                plate.save(work / "fleet-proof.png")
                sheet = Image.new("RGB", (3*W//2, 2*H//2))
                for i, background in enumerate(plates):
                    frame = make_frame(i, FRAMES//2, background)
                    frame.save(work/f"proof-{i+1}.png")
                    sheet.paste(frame.resize((W//2,H//2), Image.Resampling.LANCZOS), (i%3*W//2,i//3*H//2))
                sheet.save(work / "proof-sheet.png")
                return
            frames = work / "frames"
            frames.mkdir(exist_ok=True)
            index = 0
            for i, background in enumerate(plates):
                for j in range(OVERLAP, FRAMES):
                    transition = j - (FRAMES - OVERLAP)
                    if transition >= 0:
                        frame = transition_frame(i, (i+1) % len(plates), transition, plates)
                    else:
                        frame = make_frame(i, j, background)
                    frame.save(frames / f"{index:04d}.png", compress_level=2)
                    index += 1
                print(f"{STORY[i][0][0]} / {STORY[i][2]}", flush=True)
            output = work / "season-1-scenarios.gif"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "25", "-i", str(frames / "%04d.png"),
                            "-frames:v", str(index), "-filter_complex",
                            f"[0:v]trim=end_frame={index},split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                            "-loop", "0", str(output)], check=True)
            with Image.open(output) as result:
                if result.n_frames != index or result.size != (W,H):
                    raise ValueError("The encoded intro lost frames or changed dimensions")
            with TemporaryDirectory(prefix=".season-one-", dir=args.output) as publish:
                staged = Path(publish)
                artwork = staged / "season-1-fleet.png"
                plate.save(artwork, optimize=True)
                movie = staged / output.name
                shutil.copyfile(output, movie)
                artwork.replace(args.output / artwork.name)
                movie.replace(args.output / movie.name)


if __name__ == "__main__":
    main()
