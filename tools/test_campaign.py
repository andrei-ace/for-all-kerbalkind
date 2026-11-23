"""Run the release scenarios and Career offer checks in a separate KSP installation."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

from build_plugin import compile_csharp, managed_directory
from parts import ROOT
from render_scenarios import clone_game


def prepare(game, archive, output, dotnet):
    clone = output / "game"
    output.mkdir(parents=True, exist_ok=True)
    clone_game(game, clone)
    for retired in ("FAMSeasons", "FAMSeasonsReview"):
        if (clone / "GameData" / retired).is_dir():
            shutil.rmtree(clone / "GameData" / retired)
    with ZipFile(archive) as release:
        for member in release.namelist():
            if member.startswith(("GameData/", "Ships/", "saves/scenarios/")):
                release.extract(member, clone)
    plugin = clone / "GameData/FAMCampaignTest/Plugins"
    plugin.mkdir(parents=True)
    managed = managed_directory(clone)
    modules = ("PhysicsModule", "AnimationModule", "UIModule", "UI", "ImageConversionModule", "ScreenCaptureModule")
    refs = [managed / ("UnityEngine." + module + ".dll") for module in modules]
    refs.append(clone / "GameData/FAMSeasons/Plugins/FAMSeasons.dll")
    compile_csharp(clone, dotnet, ROOT / "tools/ScenarioMenuProbe.cs", plugin / "ScenarioMenuProbe.dll", "library", refs)
    compile_csharp(clone, dotnet, ROOT / "tools/CareerOfferSmoke.cs", plugin / "CareerOfferSmoke.dll", "library")
    return clone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory for the clone and logs")
    parser.add_argument("--archive", type=Path, default=ROOT / "dist/FAMSeasons.zip")
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    game = prepare(args.ksp_root.resolve(), args.archive, output, args.dotnet)
    if args.prepare_only:
        print(f"Prepared {game}")
        return
    binary = next(game / n for n in ("KSP.app/Contents/MacOS/KSP", "KSP_x64", "KSP_x64.exe") if (game / n).is_file())
    for name, flags, marker in (
        ("scenarios", {"FAM_SCENARIO_TEST_DIR": str(output)}, "The menu resumed Falcon"),
        ("career", {"FAM_CAREER_TEST_SAVE": "FAM Career Test"}, "[FAM Career] PASS"),
    ):
        log = output / (name + ".log")
        subprocess.run([binary, "-screen-fullscreen", "0", "-logFile", log], cwd=game,
                       env=dict(os.environ, **flags), check=True, timeout=360)
        if marker not in log.read_text(errors="replace"):
            raise RuntimeError(f"KSP exited before {name} passed. See {log}")


if __name__ == "__main__":
    main()
