"""Fly the packaged Jamestown delivery Saturn in a disposable installation of KSP 1.12.5."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

from build_plugin import compile_csharp, managed_directory
from parts import ROOT
from render_scenarios import clone_game


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ksp-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Directory for a new game clone and flight log")
    parser.add_argument("--archive", type=Path, default=ROOT / "dist/FAMSeasons.zip")
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    game = output / "game"
    clone_game(args.ksp_root.resolve(), game)
    # Replace the flight hardware in the clone with the exact files from the release.
    for name in ("FAMSeasons", "FAMSeasonsReview"):
        existing = game / "GameData" / name
        if existing.exists():
            shutil.rmtree(existing)
    with ZipFile(args.archive) as release:
        for name in release.namelist():
            if name.startswith("GameData/") or name == "Ships/VAB/FAM S1 - Jamestown Delivery.craft":
                release.extract(name, game)
    plugin = game / "GameData/FAMSaturnFlightTest/Plugins/SaturnAscentFlightTest.dll"
    plugin.parent.mkdir(parents=True)
    compile_csharp(game, args.dotnet, ROOT / "tools/SaturnAscentFlightTest.cs", plugin, "library",
                   [managed_directory(game) / "UnityEngine.PhysicsModule.dll"])
    if args.prepare_only:
        print(f"Prepared {game}. Set FAM_SATURN_FLIGHT_TEST=1 when launching the clone.")
        return
    binary = next(game / n for n in ("KSP.app/Contents/MacOS/KSP", "KSP_x64", "KSP_x64.exe") if (game / n).is_file())
    log = output / "Player.log"
    subprocess.run([binary, "-screen-fullscreen", "0", "-logFile", log], cwd=game,
                   env=dict(os.environ, FAM_SATURN_FLIGHT_TEST="1"), check=True, timeout=900)
    if "[Saturn ascent] PASS" not in log.read_text(errors="replace"):
        raise RuntimeError(f"The flight did not reach parking orbit and release its payload. See {log}")


if __name__ == "__main__":
    main()
