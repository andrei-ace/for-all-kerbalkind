// Compile only into a disposable KSP test installation. The test uses its named Sandbox start.sfs.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Expansions.Serenity;
using FAMSeasons;
using UnityEngine;

[KSPAddon(KSPAddon.Startup.MainMenu, true)]
public sealed class JamestownRoboticsFlightTest : MonoBehaviour
{
    const string Tag = "[Jamestown test] ";

    static void Verify(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
        Debug.Log(Tag + message);
    }

    static string Strokes(IEnumerable<ModuleRoboticServoPiston> legs) =>
        string.Join(", ", legs.Select(p => p.currentExtension.ToString("F3")));

    IEnumerator Start()
    {
        string saveName = Environment.GetEnvironmentVariable("FAM_ROBOTICS_TEST_SAVE");
        if (string.IsNullOrEmpty(saveName)) yield break;
        DontDestroyOnLoad(gameObject);
        Application.runInBackground = true;
        var test = Run(saveName);
        while (true)
        {
            object pending;
            try
            {
                if (!test.MoveNext()) break;
                pending = test.Current;
            }
            catch (Exception error)
            {
                Debug.LogError(Tag + error);
                Application.Quit(1);
                yield break;
            }
            yield return pending;
        }
        Debug.Log(Tag + "PASS");
        Application.Quit();
    }

    IEnumerator Run(string saveName)
    {
        string root = KSPUtil.ApplicationRootPath;
        string vab = Path.Combine(root, "Ships", "VAB");
        string outpost = Path.Combine(vab, "FAM S1 - Jamestown Outpost.craft");
        foreach (string path in Directory.GetFiles(vab, "FAM S1 - *.craft"))
        {
            var build = ShipConstruction.LoadShip(path);
            int count = ConfigNode.Load(path).GetNodes("PART").Length;
            Verify(build != null && build.parts.Count == count, Path.GetFileName(path) + " loaded " + count + " parts");
            if (path.Contains("Jamestown"))
            {
                var module = build.parts.Single(p => p.partInfo.name == "famJamestownAirlock");
                var stairs = module.FindModuleImplementing<ModuleAnimateGeneric>();
                Verify(Math.Abs(stairs.animTime - (path == outpost ? 1 : 0)) < 0.001f,
                       "Airlock stair pose matches " + Path.GetFileName(path));
                var frame = build.parts.Single(p => p.partInfo.name == "famJamestownFrame").FindModuleImplementing<FAMBaseLift>();
                Verify((frame.Actions["SetLandingGear"].actionGroup & KSPActionGroup.Gear) != 0,
                       "Gear controls the landing frame in " + Path.GetFileName(path));
            }
            build.Clear();
        }

        var start = ConfigNode.Load(Path.Combine(root, "saves", saveName, "start.sfs"));
        var game = GamePersistence.LoadGameCfg(start, saveName, true, false);
        HighLogic.CurrentGame = game;
        HighLogic.SaveFolder = saveName;
        game.startScene = GameScenes.SPACECENTER;
        GamePersistence.UpdateScenarioModules(game);
        GameEvents.onGameStateCreated.Fire(game);
        game.Start();
        float deadline = Time.realtimeSinceStartup + 65;
        while (HighLogic.LoadedScene != GameScenes.SPACECENTER || SpaceCenter.Instance == null)
        {
            if (Time.realtimeSinceStartup > deadline) throw new TimeoutException("Space center");
            yield return null;
        }
        yield return new WaitForSecondsRealtime(1.2f);
        FlightDriver.StartWithNewLaunch(outpost, "Squad/Flags/default", "LaunchPad", new VesselCrewManifest());
        deadline = Time.realtimeSinceStartup + 65;
        while (!HighLogic.LoadedSceneIsFlight || !FlightGlobals.ready || FlightGlobals.ActiveVessel == null ||
               FlightGlobals.ActiveVessel.packed)
        {
            if (Time.realtimeSinceStartup > deadline) throw new TimeoutException("Launch pad");
            yield return null;
        }
        yield return new WaitForSeconds(2);
        var vessel = FlightGlobals.ActiveVessel;
        var lift = vessel.FindPartModuleImplementing<FAMBaseLift>();
        var airlock = vessel.parts.Single(p => p.partInfo.name == "famJamestownAirlock");
        var hull = vessel.parts.Single(p => p.partInfo.name == "famJamestown");
        var servo = hull.FindAttachNode("airlock").attachedPart.FindModuleImplementing<ModuleRoboticRotationServo>();
        var port = servo.part.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>();
        var collar = airlock.FindAttachNode("bottom").attachedPart.FindModuleImplementing<ModuleDockingNode>();
        Debug.Log(Tag + $"Front {servo.part.partInfo.name} {port.snapRotation}/{port.snapOffset}, airlock {collar.snapRotation}/{collar.snapOffset}");
        Debug.Log(Tag + $"Outpost native wet mass {vessel.GetTotalMass():F5} t and {vessel.parts.Count} parts");
        Debug.Log(Tag + "Flight mass by part " + string.Join(", ", vessel.parts.GroupBy(p => p.partInfo.name)
            .Select(group => group.Key + "=" + group.Sum(p => p.mass + p.GetResourceMass()).ToString("F3"))));
        Verify(!port.snapRotation && !collar.snapRotation, "Both airlock ports accept a standard stock visitor");
        var stairsModule = airlock.FindModuleImplementing<ModuleAnimateGeneric>();
        var hinge = airlock.FindModelTransform("stairs");
        var shoe = hinge.Find("Ground shoe").GetComponent<BoxCollider>();
        var feet = vessel.parts.Where(p => p.partInfo.name == "famJamestownFootpad").ToArray();
        var legs = vessel.FindPartModulesImplementing<ModuleRoboticServoPiston>();
        Verify(shoe != null && feet.Length == 4 && legs.Count == 4, "Four hydraulic legs and a solid stair shoe");
        bool launchGear = vessel.ActionGroups[KSPActionGroup.Gear];
        Verify(!launchGear && legs.All(p => p.servoIsLocked && Math.Abs(p.targetExtension) < 0.001f),
               $"Launch Gear = {launchGear}, four locked boarding targets at zero, measured strokes {Strokes(legs)} m");
        Func<Part, float> heightFromFoot = foot =>
            Vector3.Dot(port.nodeTransform.position - foot.transform.position, hull.transform.up) + 0.10f;
        Func<float> portHeight = () => feet.Average(heightFromFoot);
        float boarding = portHeight();
        var boardingFeet = feet.ToDictionary(p => p.persistentId, heightFromFoot);
        // A retracted 1P2 can report a negative stroke when its joint compresses under Kerbin gravity.
        // Check the zero targets and measure the position of each actual shoe relative to the cabin.
        Func<bool> atBoarding = () => legs.Count == 4 && feet.Length == 4 &&
            legs.All(p => Math.Abs(p.targetExtension) < 0.001f && p.currentExtension < 0.025f) &&
            feet.All(p => Math.Abs(heightFromFoot(p) - boardingFeet[p.persistentId]) < 0.05f) &&
            Math.Abs(portHeight() - boarding) < 0.035f;
        var shoeBottom = shoe.transform.TransformPoint(shoe.center) - hull.transform.up * 0.015f;
        float toeGap = feet.Average(foot => Vector3.Dot(shoeBottom - foot.transform.position, hull.transform.up)) + 0.10f;
        Debug.Log(Tag + $"Airlock KSP scale {airlock.rescaleFactor} model {hinge.lossyScale}, hull-local " +
                  $"airlock {hull.transform.InverseTransformPoint(airlock.transform.position):F3} " +
                  $"hinge {hull.transform.InverseTransformPoint(hinge.position):F3} " +
                  $"shoe {hull.transform.InverseTransformPoint(shoeBottom):F3} " +
                  $"lowest tread {hull.transform.InverseTransformPoint(airlock.FindModelTransform("stairTread4").position):F3} " +
                  $"angle {hinge.localEulerAngles:F2}, collar up {Vector3.Dot(port.nodeTransform.up, collar.nodeTransform.up):F4}");
        Verify(Math.Abs(boarding - 1.85f) < 0.035f && Math.Abs(toeGap) < 0.035f,
               $"Boarding port {boarding:F3} m and stair shoe {toeGap:F3} m from the foot plane");
        for (int i = 1; i <= 4; i++)
        {
            var step = airlock.FindModelTransform("stairTread" + i);
            var contact = step.GetComponentInChildren<BoxCollider>();
            Verify(contact != null && contact.Raycast(new Ray(step.position + hull.transform.up * 0.15f,
                   -hull.transform.up), out RaycastHit hit, 0.25f), "Physical upper face of stair " + i);
        }
        var lights = JamestownLightFlightTest.Check(airlock);
        while (lights.MoveNext()) yield return lights.Current;

        var astronaut = HighLogic.CurrentGame.CrewRoster.GetNewKerbal(ProtoCrewMember.KerbalType.Crew);
        Verify(hull.AddCrewmember(astronaut), "Crew assigned to the habitat");
        vessel.SpawnCrew();
        foreach (var seat in new[] {hull, airlock})
        {
            if (seat == airlock)
            {
                hull.RemoveCrewmember(astronaut);
                Verify(airlock.AddCrewmember(astronaut), "Transferred the same Kerbal into the detachable airlock");
                vessel.SpawnCrew();
            }
            var hatch = seat.airlock;
            Verify(hatch != null && !FlightEVA.HatchIsObstructedMore(seat, hatch) && !FlightEVA.hatchInsideFairing(seat),
                   seat.partInfo.name + " primary hatch is physically clear in the landed assembly");
            var eva = FlightEVA.fetch.spawnEVA(astronaut, seat, hatch, true);
            yield return new WaitForSeconds(0.5f);
            Verify(eva != null && eva.vessel.isEVA && !seat.protoModuleCrew.Contains(astronaut),
                   seat.partInfo.name + " performed stock EVA");
            var entry = typeof(KerbalEVA).GetField("currentAirlockPart",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            Verify((Part)entry.GetValue(eva) == seat, seat.partInfo.name + " offered stock boarding at the hatch");
            eva.BoardPart(seat);
            yield return new WaitForSeconds(1f);
            Verify(seat.protoModuleCrew.Contains(astronaut), seat.partInfo.name + " reboarded the same crew member");
        }

        var open = hinge.localRotation;
        stairsModule.Toggle();
        yield return new WaitForSeconds(2.8f);
        Verify(Math.Abs(Quaternion.Angle(open, hinge.localRotation) - 137) < 0.5f, "Airlock hinge stowed through 137 degrees");
        var stations = (new[] { "west", "east", "rear", "airlock" }).Select(n =>
            hull.FindAttachNode(n).attachedPart.FindModuleImplementing<ModuleRoboticRotationServo>()).ToArray();
        var collars = stations.Select(s => s.part.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>()).ToArray();
        Verify(collars.All(d => d.part.partInfo.name == "dockingPort2" && !d.snapRotation), "Four stock-compatible turnable side ports");
        var initial = collars.Select(d => Quaternion.Inverse(hull.transform.rotation) * d.part.transform.rotation).ToArray();
        float[] angles = { -25, 30, -40, 60 };
        for (int i = 0; i < stations.Length; i++) SetAngle(stations[i], angles[i]);
        var level = Quaternion.Inverse(hull.transform.rotation) * airlock.transform.rotation;
        yield return new WaitForSeconds(15);
        for (int i = 0; i < stations.Length; i++)
        {
            var current = Quaternion.Inverse(hull.transform.rotation) * collars[i].part.transform.rotation;
            Verify(Math.Abs(Quaternion.Angle(initial[i], current) - Math.Abs(angles[i])) < 2,
                   $"Station {i + 1} independently rotated its port through {angles[i]} degrees");
            SetAngle(stations[i], 0);
        }
        yield return new WaitForSeconds(15);
        foreach (var station in stations) station.EngageServoLock();
        var upright = Quaternion.Inverse(hull.transform.rotation) * airlock.transform.rotation;
        Verify(Quaternion.Angle(level, upright) < 2, "Servo returned the stair hinge to the boarding orientation");

        vessel.ActionGroups.ToggleGroup(KSPActionGroup.Gear);
        yield return new WaitForSeconds(19);
        float raised = portHeight();
        Verify(vessel.ActionGroups[KSPActionGroup.Gear] && legs.All(p => Math.Abs(p.currentExtension - 0.75f) < 0.025) &&
               Math.Abs(raised - 2.60f) < 0.04f, $"Gear on raised the expansion port to {raised:F3} m, four strokes {Strokes(legs)} m");
        lift.LockFeet();
        yield return new WaitForSeconds(1);
        Verify(legs.All(p => p.servoIsLocked), "All four cylinders locked at expansion height");
        var assembled = hull.vessel;
        var assembledId = assembled.id;
        var savedTargets = legs.ToDictionary(p => p.part.persistentId, p => p.targetExtension);
        Debug.Log(Tag + $"Saving the locked expansion port at {portHeight():F3} m with strokes {Strokes(legs)} m");
        var expanded = HighLogic.CurrentGame.Updated(GameScenes.FLIGHT);
        expanded.startScene = GameScenes.FLIGHT;
        GamePersistence.SaveGame(expanded, "gear-expanded", saveName, SaveMode.OVERWRITE);
        assembled.ActionGroups.ToggleGroup(KSPActionGroup.Gear);
        yield return new WaitForSeconds(13);
        lift.LockFeet();
        stairsModule.Toggle();
        yield return new WaitForSeconds(3);
        Verify(!assembled.ActionGroups[KSPActionGroup.Gear] && atBoarding() && Quaternion.Angle(open, hinge.localRotation) < 0.3f &&
               assembled.parts.Count == 37 && !assembled.packed,
               $"Gear off returned the port to {portHeight():F3} m with stairs deployed and strokes {Strokes(legs)} m");

        // Invoke the same load pipeline as F9 and the stock named-load dialog.
        var quickLoad = typeof(QuickSaveLoad).GetMethod("quickLoad", System.Reflection.BindingFlags.Instance |
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public);
        quickLoad.Invoke(QuickSaveLoad.fetch, new object[] { "gear-expanded", saveName });
        deadline = Time.realtimeSinceStartup + 65;
        while (!HighLogic.LoadedSceneIsFlight || !FlightGlobals.ready || FlightGlobals.ActiveVessel == null ||
               ReferenceEquals(FlightGlobals.ActiveVessel, assembled) || FlightGlobals.ActiveVessel.id != assembledId ||
               FlightGlobals.ActiveVessel.packed)
        {
            if (Time.realtimeSinceStartup > deadline) throw new TimeoutException("Reloading the expanded outpost");
            yield return null;
        }
        yield return new WaitForSeconds(2);
        vessel = FlightGlobals.ActiveVessel;
        legs = vessel.FindPartModulesImplementing<ModuleRoboticServoPiston>();
        hull = vessel.parts.Single(p => p.partInfo.name == "famJamestown");
        feet = vessel.parts.Where(p => p.partInfo.name == "famJamestownFootpad").ToArray();
        port = hull.FindAttachNode("airlock").attachedPart.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>();
        Verify(vessel.ActionGroups[KSPActionGroup.Gear] && legs.Count == 4 &&
               legs.All(p => p.servoIsLocked && Math.Abs(p.targetExtension - savedTargets[p.part.persistentId]) < 0.001f),
               $"F9 restored Gear on and all four locked extension targets. Port {portHeight():F3} m, strokes {Strokes(legs)} m");
        var expansion = hull.FindAttachNode("east").attachedPart.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>();
        var visitorPort = hull.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>();
        visitorPort.part.decouple(0f);
        yield return new WaitForFixedUpdate();
        var visitor = visitorPort.part.vessel;
        Verify(visitor != hull.vessel && visitor.parts.Count == 1, "Independent stock Clamp-O-Tron test article");
        GameEvents.onVesselWasModified.Fire(visitor);
        GameEvents.onVesselWasModified.Fire(hull.vessel);
        var target = expansion.nodeTransform;
        var up = hull.transform.up;
        float dockHeight = feet.Average(f => Vector3.Dot(target.position - f.transform.position, up)) + 0.10f;
        const float visitorHeight = 2.60f;
        // Carry the test port horizontally at the documented height. Once the stock magnets
        // acquire it, stop positioning it and let the two stock ports close the remaining gap.
        bool acquired = false;
        for (int tick = 0; tick < 250 && visitorPort.part.vessel != hull.vessel; tick++)
        {
            acquired |= visitorPort.state.StartsWith("Acquire", StringComparison.Ordinal) ||
                        expansion.state.StartsWith("Acquire", StringComparison.Ordinal);
            if (!acquired)
            {
                var guest = visitorPort.nodeTransform;
                var align = Quaternion.LookRotation(-target.forward, target.up) * Quaternion.Inverse(guest.rotation);
                visitor.SetRotation(align * visitor.transform.rotation, false);
                float gap = Mathf.Max(0.045f, 0.38f - tick * 0.007f);
                visitor.Translate((Vector3d)(target.position + target.forward * gap + up * (visitorHeight - dockHeight) - guest.position));
                visitorPort.part.rb.velocity = expansion.part.rb.velocity - target.forward * 0.1f;
                visitorPort.part.rb.angularVelocity = expansion.part.rb.angularVelocity;
                Physics.SyncTransforms();
            }
            else
            {
                // Support the loose test port's weight, as a level visiting module would.
                visitorPort.part.rb.AddForce(-(Vector3)FlightGlobals.getGeeForceAtPosition(visitorPort.part.transform.position), ForceMode.Acceleration);
            }
            yield return new WaitForFixedUpdate();
        }
        yield return new WaitForSeconds(1.5f);
        Verify(visitorPort.part.vessel == hull.vessel && expansion.otherNode == visitorPort &&
               expansion.state.StartsWith("Docked", StringComparison.Ordinal),
               $"After F9 a stock port arriving at {visitorHeight:F3} m captured the {dockHeight:F3} m east dock ({expansion.state})");
        vessel = hull.vessel;
        Verify(vessel.ActionGroups[KSPActionGroup.Gear], "Gear stays on after expansion docking");
        var extendedFeet = feet.ToDictionary(f => f.persistentId, heightFromFoot);
        lift = vessel.FindPartModuleImplementing<FAMBaseLift>();
        lift.LowerToBoard();
        Verify(legs.All(p => !p.servoIsLocked && Math.Abs(p.targetExtension) < 0.001f),
               "The frame's manual boarding command unlocks and retracts its own four cylinders");
        lift.RaiseToDock();
        Verify(legs.All(p => Math.Abs(p.targetExtension - 0.75f) < 0.001f),
               "The frame's manual expansion command restores the four extension targets");
        vessel.ActionGroups.ToggleGroup(KSPActionGroup.Gear);
        yield return new WaitForSeconds(13);
        Verify(!vessel.ActionGroups[KSPActionGroup.Gear] && legs.All(p => Math.Abs(p.targetExtension) < 0.001f &&
               p.currentExtension < 0.025f) && feet.All(f => extendedFeet[f.persistentId] - heightFromFoot(f) > 0.50f),
               $"First Gear press after reloading returned the port to {portHeight():F3} m with strokes {Strokes(legs)} m");
    }

    static void SetAngle(ModuleRoboticRotationServo servo, float value)
    {
        servo.DisengageServoLock();
        var field = servo.Fields["targetAngle"];
        var previous = servo.targetAngle;
        field.SetValue(value, servo);
        field.uiControlFlight.onFieldChanged?.Invoke(field, previous);
    }
}
