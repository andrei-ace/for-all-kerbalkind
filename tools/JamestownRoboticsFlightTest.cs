// Compile only into a disposable KSP test installation. The test uses its named Sandbox start.sfs.
using System;
using System.Collections;
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
        Func<float> portHeight = () => feet.Average(foot =>
            Vector3.Dot(port.nodeTransform.position - foot.transform.position, hull.transform.up)) + 0.10f;
        float boarding = portHeight();
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

        lift.RaiseToDock();
        yield return new WaitForSeconds(19);
        float raised = portHeight();
        string strokes = string.Join(", ", legs.Select(p => p.currentExtension.ToString("F3")));
        Verify(legs.All(p => Math.Abs(p.currentExtension - 0.75f) < 0.025) && Math.Abs(raised - 2.60f) < 0.04f,
               $"Expansion port {raised:F3} m, four measured strokes {strokes} m");
        lift.LockFeet();
        yield return new WaitForSeconds(1);
        Verify(legs.All(p => p.servoIsLocked), "All four cylinders locked at expansion height");
        // Use a separate stock Clamp-O-Tron as a movable test article. Supply alignment
        // only. The stock docking FSM must acquire it and merge the two vessels.
        var visitorPort = hull.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>();
        var expansion = collars[1];
        visitorPort.part.decouple(0f);
        yield return new WaitForFixedUpdate();
        var visitor = visitorPort.part.vessel;
        Verify(visitor != hull.vessel && visitor.parts.Count == 1, "Independent stock Clamp-O-Tron test article");
        GameEvents.onVesselWasModified.Fire(visitor);
        GameEvents.onVesselWasModified.Fire(hull.vessel);
        var target = expansion.nodeTransform;
        for (int tick = 0; tick < 150 && visitorPort.part.vessel != hull.vessel; tick++)
        {
            var guest = visitorPort.nodeTransform;
            var align = Quaternion.LookRotation(-target.forward, target.up) * Quaternion.Inverse(guest.rotation);
            visitor.SetRotation(align * visitor.transform.rotation, false);
            visitor.Translate((Vector3d)(target.position + target.forward * 0.045f - guest.position));
            visitorPort.part.rb.velocity = expansion.part.rb.velocity;
            visitorPort.part.rb.angularVelocity = expansion.part.rb.angularVelocity;
            Physics.SyncTransforms();
            yield return new WaitForFixedUpdate();
        }
        yield return new WaitForSeconds(1.5f);
        Verify(visitorPort.part.vessel == hull.vessel && expansion.otherNode == visitorPort
               && expansion.state.StartsWith("Docked", StringComparison.Ordinal),
               $"Stock size1 port captured the raised east expansion dock on level ground ({expansion.state})");
        lift.LowerToBoard();
        yield return new WaitForSeconds(13);
        lift.LockFeet();
        stairsModule.Toggle();
        yield return new WaitForSeconds(3);
        Verify(Math.Abs(portHeight() - boarding) < 0.03 && Quaternion.Angle(open, hinge.localRotation) < 0.3f
               && vessel.parts.Count == 37 && !vessel.packed,
               $"Landed base recovered its {portHeight():F3} m boarding height and deployed stairs");
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
