"""Release the roof-stowed airlock in stock KSP from a new delivery craft or an existing orbital save."""

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
    parser.add_argument("--archive", type=Path, default=ROOT / "dist/FAMSeasons.zip")
    parser.add_argument("--output", type=Path, required=True, help="New disposable game and logs")
    parser.add_argument("--packed-save", type=Path, help="Resume an orbital delivery with the airlock still on its TS-12")
    parser.add_argument("--release-from", choices=("hull", "separator", "roof-port", "airlock-port"),
                        help="Part menu used to release the stowed airlock. Defaults to hull for a fresh flight and separator for a save.")
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = args.ksp_root.resolve()
    game = output / "game"
    clone_game(source, game)
    if (source / "PartDatabase.cfg").is_file():
        shutil.copy2(source / "PartDatabase.cfg", game / "PartDatabase.cfg")
    mode = "saved" if args.packed_save else "fresh"
    release_from = args.release_from or ("separator" if args.packed_save else "hull")
    if args.packed_save:
        save = game / "saves/FAM Airlock Test/packed.sfs"
        save.parent.mkdir(parents=True)
        shutil.copy2(args.packed_save, save)
    for name in ("FAMSeasons", "FAMSeasonsReview"):
        existing = game / "GameData" / name
        if existing.exists():
            shutil.rmtree(existing)
    with ZipFile(args.archive) as archive:
        for name in archive.namelist():
            if name.startswith("GameData/") or name == "Ships/VAB/FAM S1 - Jamestown Delivery.craft":
                archive.extract(name, game)
    plugin = game / "GameData/FAMAirlockTest/Plugins/JamestownAirlockFlightTest.dll"
    plugin.parent.mkdir(parents=True)
    compile_csharp(game, args.dotnet, ROOT / "tools/JamestownAirlockFlightTest.cs", plugin, "library",
                   [managed_directory(game) / "UnityEngine.PhysicsModule.dll"],
                   [ROOT / "tools/JamestownLightFlightTest.cs"])
    if args.prepare_only:
        print(f"Prepared {game}. Set FAM_AIRLOCK_TEST={mode} and FAM_AIRLOCK_RELEASE={release_from} when launching this clone.")
        return
    binary = next(game / n for n in ("KSP.app/Contents/MacOS/KSP", "KSP_x64", "KSP_x64.exe") if (game / n).is_file())
    log = output / "Player.log"
    subprocess.run([binary, "-batchmode", "-nographics", "-logFile", log], cwd=game,
                   env=dict(os.environ, FAM_AIRLOCK_TEST=mode, FAM_AIRLOCK_RELEASE=release_from), timeout=450, check=True)
    if f"[Airlock flight] PASS {mode}" not in log.read_text(errors="replace"):
        raise RuntimeError(f"KSP exited before verifying release and docking. See {log}")


if __name__ == "__main__":
    main()
