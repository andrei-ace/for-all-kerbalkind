"""Build the Season 1 release using Python 3.10+ and the included Blender .mu codec."""

import argparse
import os
import tempfile
import zipfile
from pathlib import Path

from contracts import write_contracts
from build_review import build_review
from crew import write_cast
from hardware import science, tech_tree
from model_gallery import review_images
from models import model, write_atlas
from parts import ART, CATALOG, PACK, ROOT, SEASON, SHIPS
from scenarios import SCENARIOS, scenarios, write_scenarios
from verify import verify


def generate(game, regenerate_models=False):
    ART.mkdir(parents=True, exist_ok=True)
    if regenerate_models:
        write_atlas()
    for part in CATALOG:
        if regenerate_models:
            model(part).write(ART / (part.id + ".mu"))
    if regenerate_models:
        from modular_models import write_splits
        write_splits(ROOT / "art/season-1/modular/parts")
    tech_tree().write(SEASON / "Research/TechTree.cfg")
    science().write(SEASON / "Research/ScienceDefs.cfg")
    configs = build_review(game, ROOT)
    write_contracts()
    write_cast()
    write_scenarios(configs)


def package(game, dist=ROOT / "dist"):
    dist.mkdir(parents=True, exist_ok=True)
    destination = dist / "FAMSeasons.zip"
    scenario_files = [SCENARIOS / (start.filename + ".sfs") for start in scenarios()]
    files = sorted(
        [
            p
            for parent in (PACK, SHIPS)
            for p in parent.rglob("*")
            if p.is_file() and not p.name.startswith(".")
        ]
        + [
            ROOT / "README.md",
            ROOT / "docs/flight-guide.md",
            ROOT / "docs/how-season-1-was-made.md",
            ROOT / "docs/season-1-model-review.md",
            ROOT / "docs/season-1-fleet.png",
            ROOT / "docs/season-1-scenarios.gif",
            ROOT / "docs/season-1-in-ksp.jpg",
            ROOT / "docs/season-1-in-ksp.mp4",
            ROOT / "docs/jamestown-checklist.jpg",
            ROOT / "docs/jamestown-on-the-mun.jpg",
            ROOT / "art/season-1/famApolloCM.blend",
        ]
        + review_images(ROOT)
        + list((ROOT / "art/season-1/modular").glob("*.blend"))
        + [p for p in (ROOT / "art/season-1/modular/parts").glob("*") if p.suffix in (".mu", ".png")]
        + scenario_files
        + [SCENARIOS / "banners" / (file.stem + ".png") for file in scenario_files]
    )
    # Validate the exact archive in a new directory before replacing a previous good build.
    with tempfile.TemporaryDirectory(dir=dist) as tmp:
        tmp = Path(tmp)
        candidate = tmp / destination.name
        with zipfile.ZipFile(candidate, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                entry = zipfile.ZipInfo(file.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                entry.external_attr = 0o100644 << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, file.read_bytes())
        with zipfile.ZipFile(candidate) as archive:
            if archive.testzip() is not None:
                raise ValueError("Corrupt release archive")
            unpacked = tmp / "unpacked"
            archive.extractall(unpacked)
        review_images(unpacked)
        verify(unpacked, game)
        os.replace(candidate, destination)
    print(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path, required=True, help="KSP 1.12.5 with Breaking Ground")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--package-only",
        action="store_true",
        help="Package existing meshes/configs, including Blender edits",
    )
    mode.add_argument(
        "--regenerate-models",
        action="store_true",
        help="Recreate the parametric seed meshes and livery before generating configs",
    )
    args = parser.parse_args()
    if not args.package_only:
        generate(args.ksp_root, args.regenerate_models)
    package(args.ksp_root)
