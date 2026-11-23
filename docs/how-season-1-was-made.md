# How we built Season 1 and filmed the trailer

When Jamestown’s airlock floats clear in the trailer, you’re seeing the stock separator fire in a running copy of Kerbal Space Program. We reviewed the spacecraft in Blender, wrote a C# recorder to operate the ship and camera in KSP, and used Reverse Engineer Anything (REA) to launch and observe the game. [Watch the Season 1 trailer](https://www.youtube.com/watch?v=cf8Nhy6frKE)

## What runs in a player’s game

| Component | Its job in Season 1 |
| --- | --- |
| KSP 1.12.5 and Breaking Ground | KSP supplies the flight physics, Spark descent engines and Clamp-O-Tron docking ports. Breaking Ground supplies the F-12 servos that rotate Jamestown’s side ports and the 1P2 cylinders that raise or lower the habitat. |
| ModuleManager | Applies our six research nodes to KSP’s stock technology tree. [ModuleManager](https://github.com/sarbian/ModuleManager) |
| Contract Configurator and Harmony for KSP | Contract Configurator reads the three Career contracts and checks which missions and parts the player has unlocked. Harmony for KSP supplies its runtime patching library. [Contract Configurator](https://github.com/KSP-RO/ContractConfigurator) · [Harmony for KSP](https://github.com/KSPModdingLibs/HarmonyKSP) |
| For All Kerbalkind | Our configs define the parts, ships and missions. Our compiled plug-in handles the scenario checklist, staging fixes, Jamestown’s controls and the contract check that recognizes an occupied, landed habitat. [Gameplay source](https://github.com/andrei-ace/for-all-kerbalkind/tree/main/src) |

The release includes the compiled plug-in. Players can follow the install instructions and fly with KSP’s own runtime. [Install and start](../README.md#install-and-start)

## From editable models to flyable ships

We generated the custom meshes and livery with the project’s Python tools and reviewed the editable assemblies in Blender. Bill Currie’s `io_object_mu` add-on lets Blender read KSP’s `.mu` models, so we could fit the actual stock and DLC parts at their in-game attachment poses. For Jamestown we checked the roof-stowed airlock inside its fairing, the clearance around each docking face, and where the bottom stair meets the ground. The model guide shows the packed and deployed views and links the editable files. [Model review](season-1-model-review.md#jamestown) · [Blender add-on and author](https://github.com/taniwha/io_object_mu/tree/ff04234928b2e66f92d2d1325225e9a29f0b415c)

Python generates the VAB ships and scenario starting vessels from shared craft definitions. The .NET SDK’s Roslyn compiler builds our C# code against the installed game’s `Assembly-CSharp.dll`, Unity libraries and `ContractConfigurator.dll`. The result is `GameData/FAMSeasons/Plugins/FAMSeasons.dll`, which Unity loads with Mono. We used REA’s `inspect_managed_artifact` to inspect the compiled plug-in and the game assembly and confirm which libraries the plug-in actually references. [Build script](https://github.com/andrei-ace/for-all-kerbalkind/blob/main/tools/build_plugin.py) · [REA](https://github.com/morluto/rea)

Before recording, we checked the extracted release for attachment poses, staging and fuel budgets. We also loaded the packaged scenarios and tested Career progression in a fresh game. For example, the campaign test withholds required parts and checks that the corresponding contract stays unavailable. The flight guide gives the stage budgets and reserves. [Flight guide](flight-guide.md) · [Campaign test](https://github.com/andrei-ace/for-all-kerbalkind/blob/main/tools/test_campaign.py)

## Reproduce the airlock shot with REA

From the source checkout, use Python 3.10 or newer, the .NET SDK, FFmpeg and an isolated KSP install synced to `dist/FAMSeasons.zip`. Choose an empty output directory. This command checks the installed mod against the archive, clones the game, writes a flight save and camera plan, and compiles the temporary recorder into the clone.

```sh
KSP_ROOT="/absolute/path/to/isolated KSP"
TAKE="/absolute/path/to/new-take"
python3 tools/render_scenarios.py --ksp-root "$KSP_ROOT" --output "$TAKE" \
  --shot jamestown-airlock-release --prepare-only
```

Launch the clone with REA’s `capture_process_scenario`. These are the macOS settings we used. Replace `<take>` with the absolute output directory in each field.

| REA field | Value |
| --- | --- |
| Executable | `<take>/game/KSP.app/Contents/MacOS/KSP` |
| Working directory | `<take>/game` |
| Arguments | `["-screen-fullscreen", "0", "-screen-width", "1920", "-screen-height", "1080", "-logFile", "<take>/Player.log"]` |
| Environment | `FAM_PREVIEW_MANIFEST=<take>/capture.cfg` |

The recorder loads the shot, waits for the vessel to be ready, fires the TS-12 separator and captures PNG frames through Unity. It checks that the airlock, habitat and transport ring became three separate vessels and that the two docking faces cleared each other by at least 0.75 m. It writes the measured gap to `Player.log`. Once `capture-complete.txt` appears in the output directory, assemble the frames. [Recorder source](https://github.com/andrei-ace/for-all-kerbalkind/blob/main/tools/KspPreviewCapture.cs)

```sh
python3 tools/render_scenarios.py --output "$TAKE" --assemble
```

Omit `--shot jamestown-airlock-release` in the preparation command to record all eleven scenes. FFmpeg adds the opening title and shot captions and encodes the 44-second reel at 1080p and 25 frames per second. The README’s opening GIF is a separate stylized animation. The linked YouTube trailer shows the in-game footage with the soundtrack added for publication. [Capture and assembly script](https://github.com/andrei-ace/for-all-kerbalkind/blob/main/tools/render_scenarios.py)
