"""Prepare and capture Season 1 shots in a disposable KSP 1.12.5 copy."""

import argparse
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from math import acos, pi, sin
from pathlib import Path
from zipfile import ZipFile

from build_plugin import compile_csharp, managed_directory
from build_review import review_craft
from config import Node, read_node
from craft import Craft, fleet
from crew import ALEXEI, BUZZ, ELLEN, MICHAEL, NEIL
from parts import ROOT
from scenarios import (
    EPOCH,
    KERBIN,
    KERBIN_RADIUS,
    Orbit,
    Scenario,
    Start,
    Surface,
    flight_kit,
    habitat,
    lander,
    orbiter,
    scenario_state,
    scenarios,
)

SAVE_FOLDER = "FAM Preview"
MANIFEST = "capture.cfg"
FPS = 25
WIDTH, HEIGHT = 1920, 1080


@dataclass(frozen=True)
class Shot:
    name: str
    title: str
    flights: tuple[Start, ...]
    distance: int
    action: str = ""
    partner: str = ""
    heading: int = 0
    elevation: int = 9
    epoch: int = EPOCH


def entry_orbit():
    """Start above Kerbin's atmosphere on a Mun-return ellipse."""
    periapsis = KERBIN_RADIUS + 36_000
    axis = (12_000_000 + periapsis) / 2
    eccentricity = 1 - periapsis / axis
    anomaly = -acos((1 - (KERBIN_RADIUS + 150_000) / axis) / eccentricity)
    return Orbit(axis, anomaly=anomaly - eccentricity * sin(anomaly), eccentricity=eccentricity, body=KERBIN)


def shots():
    red, apollo, jamestown = scenarios()
    falcon, _, _, ferry, osprey = jamestown.flights
    lk = lander("LK", "famLK", "famLKPlatform")
    # Landing patches surveyed in KSP's stock terrain with the Sun above the local horizon.
    lk_site = Surface(0.24, 69.08, 4115.21)
    eagle_site = Surface(1.34, 24.14, 807.62)
    habitat_site = Surface(-77, 11.2221, 6038.38, heading=180)
    eagle_landed = lander("Eagle", "famLMAscent", "famLMDescent")
    eagle = Craft("Eagle", "", "famLMAscent", "Lander")
    columbia = orbiter("Columbia", "famApolloCM", "famRing250", "famApolloSM")
    delivery = next(craft for craft in fleet() if craft.title == "FAM S1 - Jamestown Delivery")
    upper_stage = next(i for i, piece in enumerate(delivery.pieces) if piece.kind == "famSaturnIVB")
    delivery.pieces = delivery.pieces[:upper_stage + 1]
    del delivery.pieces[-1].connections["bottom"]
    delivery.tip = upper_stage
    parking = 233_000
    carrier = flight_kit(Start(delivery, Orbit(parking, 90, 12, pi / 6), active_engine="famSaturnIVB"))
    # KSP compresses the two surviving stages when the detached upper stage loads.
    # Save its already-burning S-IVB at index 1 and the outpost release at index 0.
    surviving_stages = sorted({part.stage for part in carrier.craft.pieces if part.stage >= 0})
    for part in carrier.craft.pieces:
        if part.stage >= 0:
            part.stage = surviving_stages.index(part.stage)
    return (
        Shot("red-mun-launch", "Red Mun · N1 liftoff", red.flights, 60, action="launch", heading=-32, elevation=12),
        Shot(
            "lk-on-the-mun",
            "Red Mun · LK on the Mun",
            (Start(lk, lk_site, (ALEXEI,)),),
            9,
            elevation=6,
            epoch=26949,
        ),
        Shot(
            "apollo-11-launch",
            "Apollo 11 · Saturn V liftoff",
            apollo.flights,
            58,
            action="launch",
            heading=25,
        ),
        Shot(
            "eagle-on-the-mun",
            "Apollo 11 · Eagle on the Mun",
            (Start(eagle_landed, eagle_site, (NEIL, BUZZ)),),
            10,
            heading=-32,
            elevation=7,
            epoch=54746,
        ),
        Shot(
            "apollo-rendezvous",
            "Apollo 11 · Eagle and Columbia in Mun orbit",
            (
                Start(columbia, Orbit(parking), (MICHAEL,)),
                Start(eagle, Orbit(parking, anomaly=8 / parking), (NEIL, BUZZ)),
            ),
            11,
            partner="Eagle",
            heading=-20,
            elevation=35,
        ),
        Shot(
            "columbia-separation",
            "Apollo 11 · Columbia service separation",
            (Start(columbia, entry_orbit(), (MICHAEL, NEIL, BUZZ), "famApolloSM"),),
            9,
            action="separate",
            heading=13,
            elevation=40,
        ),
        Shot(
            "shackleton-survey",
            "Jamestown · Falcon at Shackleton",
            (falcon,),
            9,
            heading=21,
            epoch=jamestown.epoch,
        ),
        Shot(
            "jamestown-unpacking",
            "Jamestown · Outpost release in Mun orbit",
            (carrier,),
            23,
            action="unpack",
            heading=10,
            elevation=37,
        ),
        Shot(
            "jamestown-airlock-release",
            "Jamestown · Releasing the roof-stowed airlock",
            (Start(review_craft(habitat(), roof_stowed_airlock=True), carrier.location),),
            14,
            action="roof-release",
            heading=-12,
            elevation=27,
        ),
        Shot(
            "jamestown-base",
            "Jamestown · Boarding lights at Shackleton",
            (Start(habitat(), habitat_site),),
            11,
            action="lights",
            heading=32,
            elevation=18,
            epoch=jamestown.epoch,
        ),
        Shot(
            "apollo-24-rendezvous",
            "Jamestown · LSAM meets Apollo 24",
            (
                Start(ferry.craft, Orbit(parking, 90, 12, pi / 6), ferry.crew[:1]),
                Start(osprey.craft, Orbit(parking, 90, 12, pi / 6 + 9 / parking), (ELLEN,)),
            ),
            12,
            partner=osprey.craft.title,
            heading=-25,
            elevation=37,
        ),
    )


def copy_directory(source, target):
    if platform.system() == "Darwin":
        # APFS clones the large immutable game files while keeping writes to the copy local.
        subprocess.run(["cp", "-cR", source, target], check=True)
    else:
        shutil.copytree(source, target)


def clone_game(source, target):
    target.mkdir()
    for folder in ("KSP.app", "KSP_x64_Data", "KSP_Data", "MonoBleedingEdge", "GameData", "Missions"):
        if (source / folder).is_dir():
            copy_directory(source / folder, target / folder)
    for name in (
        "KSP_x64",
        "KSP_x64.exe",
        "KSP.exe",
        "UnityPlayer.so",
        "UnityPlayer.dll",
        "Physics.cfg",
        "settings.cfg",
        "buildID.txt",
        "buildID64.txt",
    ):
        if (source / name).is_file():
            shutil.copy2(source / name, target / name)


def write_manifest(output, game, selected, frames):
    save_path = game / "saves" / SAVE_FOLDER
    save_path.mkdir(parents=True)
    plan = Node("CAPTURE", saveFolder=SAVE_FOLDER, fps=FPS)
    from build_review import stock_configs
    configs = stock_configs(game)
    for path in (game / "GameData/FAMSeasons/Season1/Parts").glob("*.cfg"):
        config = read_node(path).children("PART")[0]
        configs[config.values("name")[0]] = config
    for shot in selected:
        scene = scenario_state(Scenario(shot.title, shot.title, shot.flights, (), epoch=shot.epoch), configs)
        # Keep the authored flight state and roster. The capture controller supplies the camera.
        scene.entries = [
            entry for entry in scene.entries if not isinstance(entry, Node) or entry.kind != "SCENARIO"
        ]
        scene.write(save_path / (shot.name + ".sfs"))
        active = scene.children("FLIGHTSTATE")[0].children("VESSEL")[0]
        location = shot.flights[0].location
        plan.child(
            Node(
                "SHOT",
                name=shot.name,
                title=shot.title,
                distance=shot.distance,
                heading=shot.heading,
                elevation=shot.elevation,
                sunlitSurface=str(isinstance(location, Surface) and not location.at_pad).title(),
                action=shot.action,
                partner=shot.partner,
                focusId=active.values("pid")[0],
                frames=frames,
            )
        )
    plan.write(output / MANIFEST)


def set_capture_quality(game):
    settings = game / "settings.cfg"
    if not settings.exists():
        return
    values = {
        "SCREEN_RESOLUTION_WIDTH": WIDTH,
        "SCREEN_RESOLUTION_HEIGHT": HEIGHT,
        "FULLSCREEN": "False",
        "QUALITY_PRESET": 5,
        "ANTI_ALIASING": 4,
        "TEXTURE_QUALITY": 0,
        "LIGHT_QUALITY": 8,
        "SHADOWS_QUALITY": 4,
        "TERRAIN_SHADER_QUALITY": 3,
        "INFLIGHT_HIGHLIGHT": "False",
        "HIGHLIGHT_FX": "False",
    }
    # Preserve the stock High terrain data and settings unrelated to the capture.
    text = re.sub(
        r"^(" + "|".join(values) + r") = .*",
        lambda match: f"{match[1]} = {values[match[1]]}",
        settings.read_text(),
        flags=re.MULTILINE,
    )
    settings.write_text(re.sub(r"^(\tpreset = )\w+", r"\g<1>High", text, count=1, flags=re.MULTILINE))


def check_capture_models(game):
    mod = Path("GameData/FAMSeasons")
    with ZipFile(ROOT / "dist/FAMSeasons.zip") as release:
        expected = {Path(n) for n in release.namelist() if n.startswith(f"{mod.as_posix()}/") and not n.endswith("/")}
        installed = {p.relative_to(game) for p in (game / mod).rglob("*") if p.is_file()}
        if expected != installed or any(release.read(p.as_posix()) != (game / p).read_bytes() for p in expected):
            raise ValueError("Capture models differ from dist/FAMSeasons.zip. Sync the isolated game before recording.")


def prepare(source, output, dotnet, requested, frames):
    selected = [shot for shot in shots() if not requested or shot.name in requested]
    if not selected or (requested and len(selected) != len(set(requested))):
        raise ValueError("Select a shot from --list-shots")
    if not (source / "GameData/FAMSeasons/Plugins/FAMSeasons.dll").is_file():
        raise FileNotFoundError("Choose the KSP copy with For All Kerbalkind installed")
    check_capture_models(source)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Choose an empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    game = output / "game"
    clone_game(source, game)
    set_capture_quality(game)
    managed = managed_directory(game)
    plugin = game / "GameData/FAMPreviewCapture/Plugins/KspPreviewCapture.dll"
    plugin.parent.mkdir(parents=True)
    compile_csharp(
        game,
        dotnet,
        ROOT / "tools/KspPreviewCapture.cs",
        plugin,
        "library",
        extra_references=[
            managed / "UnityEngine.ScreenCaptureModule.dll",
            managed / "UnityEngine.ImageConversionModule.dll",
            managed / "UnityEngine.PhysicsModule.dll",
            managed / "UnityEngine.UIModule.dll",
        ],
    )
    write_manifest(output, game, selected, frames)
    print(f"Prepared {len(selected)} shots in {output}")
    return game


def launch(game, output):
    executables = ("KSP.app/Contents/MacOS/KSP", "KSP_x64", "KSP_x64.exe", "KSP.exe")
    program = next((game / name for name in executables if (game / name).is_file()), None)
    if program is None:
        raise FileNotFoundError("KSP executable is missing from the capture copy")
    subprocess.run(
        [
            program,
            "-screen-fullscreen",
            "0",
            "-screen-width",
            str(WIDTH),
            "-screen-height",
            str(HEIGHT),
            "-logFile",
            output / "Player.log",
        ],
        cwd=game,
        env=dict(os.environ, FAM_PREVIEW_MANIFEST=str(output / MANIFEST)),
        check=True,
    )


def capture_font(bold=False):
    candidates = (
        ("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
         "C:/Windows/Fonts/arialbd.ttf")
        if bold else
        ("/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "C:/Windows/Fonts/arial.ttf")
    )
    selected = next((path for path in candidates if Path(path).is_file()), None)
    return "fontfile='" + selected.replace(":", "\\:") + "'" if selected else "font=Sans"


def hero_artwork(ffmpeg, target):
    title_face, caption_face = capture_font(True), capture_font()
    # The launch stack occupies the right of the shot. A feathered scrim keeps the
    # title readable against both sky and grass while the uncovered footage moves.
    layers = [
        "format=rgba",
        "geq=r=10:g=19:b=27:a='175*clip(1-X/(W*0.64)\\,0\\,1)'",
        "drawbox=x=105:y=347:w=57:h=4:color=0xF2C576:t=fill:replace=1",
        f"drawtext={caption_face}:text='SEASON 1':x=181:y=335:fontsize=28:fontcolor=0xF9D18A",
        f"drawtext={title_face}:text='FOR ALL':x=99:y=393:fontsize=115:fontcolor=0xF8F6EF",
        f"drawtext={title_face}:text='KERBALKIND':x=99:y=495:fontsize=115:fontcolor=0xF8F6EF",
        f"drawtext={caption_face}:text='The race to the Mun':x=105:y=638:fontsize=37:fontcolor=white",
    ]
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=s={WIDTH}x{HEIGHT}:d=1", "-vf", ",".join(layers),
                    "-frames:v", "1", "-threads", "1", target], check=True)


def completed_take(output):
    error = output / "capture-error.txt"
    if error.is_file():
        raise RuntimeError(error.read_text())
    if not (output / "capture-complete.txt").is_file():
        raise RuntimeError(f"KSP has not finished recording. Check {output / 'Player.log'}")
    return read_node(output / MANIFEST).children("CAPTURE")[0]


def assemble(output, ffmpeg, retakes=()):
    confirmed = None
    if retakes and not (output / "capture-complete.txt").exists() and not (output / "capture-error.txt").exists():
        # A recorder that runs out of time can still have finished earlier shots.
        # This line is written only after the last frame and all flight checks for a shot.
        log = (output / "Player.log").read_text(errors="replace")
        confirmed = set(re.findall(r"^\[FAM Preview\] Captured ([\w-]+)[ \t]*$", log, re.MULTILINE))
        plan = read_node(output / MANIFEST).children("CAPTURE")[0]
    else:
        plan = completed_take(output)
    check_capture_models(output / "game")
    fps = plan.values("fps")[0]
    chosen = {shot.values("name")[0]: (shot, output) for shot in plan.children("SHOT")}
    for directory in retakes:
        take = completed_take(directory)
        check_capture_models(directory / "game")
        if take.values("fps") != [fps]:
            raise ValueError(f"Capture frame rate changed in {directory}")
        for shot in take.children("SHOT"):
            name = shot.values("name")[0]
            if name not in chosen:
                raise ValueError(f"Unknown replacement shot {name}")
            chosen[name] = shot, directory
    if confirmed is not None:
        missing = [name for name, (_, directory) in chosen.items() if directory == output and name not in confirmed]
        if missing:
            raise RuntimeError(f"Finish or retake these interrupted shots before assembly: {', '.join(missing)}")
    stills = output / "stills"
    stills.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        sequence = Path(tmp)
        hero = sequence / "hero.png"
        hero_artwork(ffmpeg, hero)
        index = 0
        captions = []
        for shot, directory in chosen.values():
            name = shot.values("name")[0]
            count = int(shot.values("frames")[0])
            if index:
                caption = sequence / (name + ".txt")
                caption.write_text(shot.values("title")[0], encoding="utf-8")
                label_end = index + min(count, round(float(fps) * 2.5))
                captions.append(
                    f"drawtext={capture_font()}:textfile='{caption.as_posix()}':fontsize=33:"
                    "fontcolor=white:box=1:boxcolor=0x0E1C29@0.76:boxborderw=12:"
                    f"x=80:y=h-th-64:enable='gte(n,{index})*lt(n,{label_end})'"
                )
            frames = [directory / "frames" / name / f"{i:04d}.png" for i in range(count)]
            if not all(frame.is_file() and frame.stat().st_size > 0 for frame in frames):
                raise RuntimeError(f"Missing frames for {name}")
            for frame in frames:
                (sequence / f"{index:06d}.png").symlink_to(frame)
                index += 1
            # These moments show the facing ports and, after service separation, all three silhouettes.
            still_time = {"apollo-rendezvous": 0.25, "columbia-separation": 0.64}.get(name, 0.8)
            still_frame = int(count * still_time)
            shutil.copy2(frames[still_frame], stills / (name + ".png"))
        scale = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                 f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuv420p,setsar=1")
        first_shot, _ = next(iter(chosen.values()))
        duration = min(3.65, int(first_shot.values("frames")[0]) / int(fps))
        title = (f"[0:v]{scale}[footage];[1:v]format=rgba,fade=t=out:"
                 f"st={duration-.5:.2f}:d=0.5:alpha=1[title];[footage][title]overlay=shortest=1")
        if captions:
            title += "," + ",".join(captions)
        subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                fps,
                "-i",
                sequence / "%06d.png",
                "-loop", "1", "-framerate", fps, "-i", hero,
                "-filter_complex", title,
                "-c:v",
                "libx264",
                "-preset", "slow",
                "-crf", "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-metadata", "title=For All Kerbalkind — Season 1",
                "-metadata", "comment=The race to the Mun. Recorded in Kerbal Space Program.",
                output / "season-1-in-ksp.mp4",
            ],
            check=True,
        )
        subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{duration * .52:.2f}",
                        "-i", output / "season-1-in-ksp.mp4", "-frames:v", "1", "-q:v", "2",
                        output / "season-1-in-ksp.jpg"], check=True)
        exports = {
            "jamestown-base": "jamestown-on-the-mun.jpg",
            "columbia-separation": "ksp-columbia-separation.jpg",
            "apollo-rendezvous": "ksp-eagle-rendezvous.jpg",
        }
        for name in chosen:
            if name in exports:
                subprocess.run([ffmpeg, "-v", "error", "-y", "-i", stills / (name + ".png"),
                                "-frames:v", "1", "-q:v", "2", output / exports[name]], check=True)
    print(output / "season-1-in-ksp.mp4")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--shot", action="append")
    parser.add_argument("--retake", action="append", default=[], type=Path,
                        help="Use successfully recorded replacement shots from this capture directory during assembly")
    parser.add_argument("--frames", type=int, default=100)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--prepare-only", action="store_true")
    action.add_argument("--assemble", action="store_true")
    action.add_argument("--list-shots", action="store_true")
    args = parser.parse_args()
    if args.list_shots:
        for shot in shots():
            print(shot.name, shot.title)
        return
    if args.output is None:
        parser.error("--output is required")
    output = args.output.resolve()
    if args.assemble:
        assemble(output, args.ffmpeg, [d.resolve() for d in args.retake])
        return
    if args.retake:
        parser.error("--retake requires --assemble")
    if args.ksp_root is None or not 50 <= args.frames <= 250:
        parser.error("--ksp-root and 50 to 250 frames per shot are required")
    game = prepare(args.ksp_root.resolve(), output, args.dotnet, args.shot, args.frames)
    if not args.prepare_only:
        launch(game, output)
        assemble(output, args.ffmpeg)


if __name__ == "__main__":
    main()
