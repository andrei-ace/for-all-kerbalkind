# For All Kerbalkind

## Season development order

1. Build the ships and their editable parts. Define the assembly, interfaces, and each ship's mission role.
2. Review the assembled ships before moving on. In Blender, inspect the exact meshes and attachments from several angles. Check the silhouette, clearance, EVA paths, and docking and landing interfaces. Check mass, thrust, and provisional delta-v against what the ship needs to do.
3. Generate the documentation images from the reviewed models and update the README and relevant guides.
4. Build or revise the missions and scenarios from the reviewed ships. Validate the exact packaged craft and saves in KSP, including staging, delta-v and fuel reserves, docking, landing, recovery, and objective tracking as applicable. Recheck existing saves when part or staging rules change.
5. Record the in-game captures after those tests pass. Use high visual settings and high resolution, then update the screenshots and reel in the documentation.

## Staging verification

- Check the exact packaged VAB craft and scenario saves against KSP 1.12.5. When staging changes, inspect the stages KSP shows after loading and test the affected events in the isolated desktop game when available. Cover launch and tower jettison, payload release, lander ascent, docking and undocking, service separation, and recovery as applicable.
- Give the return chutes a dedicated final stage. Check every module that can add a part to staging, including `ModuleJettison`. KSP can show the service module beside the chutes when its engine is already non-staging and only its shroud can stage.
- Check stock delta-v and burn time on the detached return ship and ascent cabin. The service engine needs a burn stage above the service separator. Check the orange vessel total after the landing platform separates, when the ascent engine is the only engine left.
- Check both fresh starts and an existing save for a changed staging rule. Preserve ignition, fuel, and attachment state on load. Keep the regression checks against stock staging predicates in `tools/StockSmoke.cs`.
- Rebuild the plugin after changes under `src/`. Run `python3 tools/build.py --ksp-root "/path/to/KSP"`, then run `python3 tools/stock_smoke.py --ksp-root "/path/to/KSP" --root "/path/to/extracted-release"` on the exact release. Record the evidence and any desktop flight checks still pending.

## Attachment verification

- Before presenting or packaging a changed craft, open the editable models together in Blender at the exact craft attachment poses. Use the real stock meshes for fittings. Inspect several angles, including the underside, and fix clipping or floating mounts before sending previews. Check tanks, struts, nozzle exits and thrust direction, stairs, and docking approaches. Recheck the exported models in KSP.
- Apply each attachment change to the shared craft generator and check the exported VAB craft and scenario saves. Verify stack nodes meet in local space and face each other after both parts' rotations are applied. Compare each part's attachment plane with its exported model.
- For surface attachments, check the actual mounting plate and cover against the host mesh. Use KSP 1.12.5's Mk2-R model when the game is available. Its cap faces local `-Z`. A correct parent link and stage number alone can leave a chute inside a capsule.
- Check the full mounting footprint for gaps and penetration, the cover for clearance, and both sides of a paired mount. Render or inspect the assembled parts from the side and near the attachment when possible.
- On tapered crew capsules, measure the hatch trim against the actual hull facets. Render a front quarter, a profile and the underside with the packed stock chutes in their flight poses. Check that KSP offers EVA and boarding at the same hatch.
- Keep a regression check that rejects the old inward chute orientation and a displaced mount. Run the attachment checks in `tools/verify.py` on the packaged payload and installed files.
- Check the entire lander and its fittings against the deployed fairing profile when an exterior mesh changes. For Jamestown, keep the four thrust transforms aligned with the bell exits beneath the tank pods and above the common pad plane.

## Launchers and packed payloads

- Fly the packaged launch stacks in KSP at normal physics speed through a gentle gravity turn, peak dynamic pressure, and the second-stage handoff. Check that all four tail surfaces deflect, the thrust vectors follow pitch and yaw, and the upper stage settles after separation. Check joint movement separately from attitude oscillation.
- Run `python3 tools/test_saturn_ascent.py --ksp-root "/path/to/isolated KSP" --output "/path/to/new/ascent-test"` for changes to the delivery launcher. Record the orbit, retained S-IVB and landing fuel, and the result of releasing the payload after stock staging is ready.
- Inspect the fitted interstage shrouds on the pad and verify they clear with the lower attachment. Check the stage list for the same separator and next engine ignition, and keep the shrouds out of the stage stack.
- Compare launch and landing budgets separately against the stock Community Delta-V Map using vacuum figures. For Jamestown, allow 3,800 m/s for the Kerbin ascent, 860 for transfer and 310 for direct polar capture. Allow another 400 m/s from the loaded S-IVB for circularization and targeting, and measure the reserve after polar capture. Fly the four Sparks to the survey shelf and record fuel after touchdown. On the Saturn S-II check both 3.75 m engine-plate nodes, the loaded gimbal travel, and the tank autostrut. Record the attitude error and tank-to-engine flex separately through the gravity turn. Match the final two fairing slopes to the packed reference and measure the minimum clearance around the roof-stowed airlock.
- Lay out the transport and operating configurations before changing a fairing. Check the exact nested hardware and folded stock fittings against the saved profile. For Jamestown, check the TS-12 roof release, the airlock's independent control, power and RCS, stock capture, servo roll after capture, and all stair positions. Render the cutaway and closed silhouette.
- Serialize the docking modules in prefab order in generated craft. KSP 1.12.5 populates the accepted docking sizes in `ModuleDockingNode.OnLoad`. Check an actual stock capture as well as the facing and clearance.

## Jamestown expansion

- Use the released modular parts in Sandbox, Career and scenarios. Preserve `famJamestown`, `famJamestownFrame` and `famJamestownAirlock`, their mounting planes and saved module order. Keep the fixed roof port and a 1.0 m radius clear along both lateral expansion approaches.
- Attach the folding stairs, physical treads, ground shoe, sill and animation to the detachable airlock. Check its isolated render, roof stow, side docking and 137° sweep. Inspect stock and DLC scale in a loaded KSP vessel. A missing `rescaleFactor = 1` can put the shoe below the foot plane even when Blender looks correct.
- Fit an independent F-12 beneath each of the four lateral stock Clamp-O-Trons. Keep their bearings shrouded, their mating faces clear and their stock roll compatibility. Test each servo with the stairs stowed. An ordinary visiting stock port must actually dock. Fit each shoe to its own 1P2 moving top and measure all four strokes under load at the 1.85 m boarding and 2.60 m expansion settings.
- Run the Blender clearance checks and `python3 tools/test_jamestown_robotics.py --ksp-root "/path/to/isolated KSP" --sandbox-save "/path/to/Sandbox/persistent.sfs" --output "/path/to/new/test"`. In KSP test stock EVA and reboarding both from the hull and after transferring a crew member into the detachable airlock. Check the four physical treads and verify that the campaign counts the crew after transferring them back into the hull.
- Test the delivery configuration through fairing release, powered touchdown and the 30-second stability objective as well as the assembled outpost on level terrain.

## Scenario starts and objectives

- Open the exact packaged Season 1 templates through KSP's **Start Game → Scenarios** menu in a clean isolated copy. Verify that Red Mun is the active, crewed N1 and Apollo 11 is the active, crewed Saturn V on the pad. Inspect the displayed first stage and fire it to check liftoff.
- Verify resume with an existing scenario progress folder. KSP loads `saves/scenarios/<scenario>/persistent.sfs` when a scenario has progress. Its **Restart** button deletes that folder. Archive the folder before testing a fresh start on an existing installation or asking a player to restart.
- Start Jamestown on Falcon and check the first instruction against the live sampler menu. Discarding the core must leave the objective open. Verify that the stock experiment-stored event and a retained sample advance to the EVA and ascent objective, then save and resume. Check that handoffs track the vessel containing the actual modular part after staging and docking.
- Measure Falcon's distance to Shackleton along the Mun's surface using both latitude and longitude. Leave clearance for the habitat within the survey radius.
- After the scenario checks, test a fresh Career against `dist/FAMSeasons.zip` with `tools/test_campaign.py`. Mission order is Red Mun, Apollo 11, then Jamestown. Require successful completion of the predecessor, appropriate facilities, and every mod, stock and DLC part on each supplied mission craft. Withhold each required part and research node in turn. Check offered, active, cancelled and failed predecessors as well as success.

## Captures and releases

- Keep the stylized GIF at the top of the README. Use `tools/render_scenarios.py` against an isolated KSP copy to record the in-game reel. Inspect each shot for framing, staging events, and attachment clearance. Use flat, sunlit Mun terrain for surface shots and verify that the docking ports face each other with clearance in rendezvous shots. Update the README and flight guide links when refreshing the captures.
- Keep the full-resolution Columbia separation and Eagle rendezvous stills in `docs/models`. Use `docs/season-1-model-review.md` for the gallery, editable models, fleet plate, intro and reel. Verify its links against the extracted release.
- Build the fleet plate and stylized animation from the same modular craft and part exports as the archive. Inspect a launch, free-flight and surface frame against the loaded parts. When a ship changes, refresh the MP4 and its poster together, check the opening title at playback size, and play the links from both the README and flight guide.
- Publish one current set of review views in `docs/models`. For Jamestown, keep the assembled base, the detachable airlock and lift comparison, and the packed cutaway. Keep diagnostic angles in the render workspace. Run `tools/model_gallery.py --kit jamestown --renders "/path/to/render output"` to publish the linked views and prune retired ones, then verify the release gallery.
- Build `dist/FAMSeasons.zip`. The GitHub release tag supplies the release version. Keep mod release numbers out of the source archive name and documentation.
- Sync the Desktop game with `dist/For All Kerbalkind.command --install-only` and run `tools/install_local.py --check` against the same game and Sandbox save. All modes use the same archive. Check the global VAB, the Sandbox VAB, the part catalogue and all three scenario starts. Retire first-release preview saves, craft and runtimes by their project identifiers. Preserve player craft and progress made with the released fleet.
- To record through REA, use `--prepare-only` and run the cloned KSP executable with `FAM_PREVIEW_MANIFEST` set to the absolute path of `capture.cfg`. Allow time for game loading and frame capture. Run `--assemble` after `capture-complete.txt` appears.
