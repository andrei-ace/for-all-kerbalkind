using System;
using System.Collections;
using System.Globalization;
using System.IO;
using System.Linq;
using KSP.UI;
using KSP.UI.Screens;
using UnityEngine;

// The capture launcher supplies this manifest only in its disposable copy of the game.
[KSPAddon(KSPAddon.Startup.MainMenu, true)]
public sealed class KspPreviewCapture : MonoBehaviour
{
    private const string ManifestVariable = "FAM_PREVIEW_MANIFEST";
    private static readonly WaitForEndOfFrame EndOfFrame = new WaitForEndOfFrame();

    private IEnumerator Start()
    {
        var manifest = Environment.GetEnvironmentVariable(ManifestVariable);
        if (string.IsNullOrEmpty(manifest))
            yield break;
        DontDestroyOnLoad(gameObject);
        Application.runInBackground = true;
        GameSettings.INFLIGHT_HIGHLIGHT = false;
        GameSettings.HIGHLIGHT_FX = false;
        var output = Path.GetDirectoryName(manifest);
        var recording = Record(manifest, output);
        while (true)
        {
            object next;
            try
            {
                if (!recording.MoveNext())
                    break;
                next = recording.Current;
            }
            catch (Exception error)
            {
                File.WriteAllText(Path.Combine(output, "capture-error.txt"), error.ToString());
                Debug.LogException(error);
                Application.Quit(1);
                yield break;
            }
            yield return next;
        }
        File.WriteAllText(Path.Combine(output, "capture-complete.txt"), "KSP captured every requested shot.\n");
        Application.Quit();
    }

    private static IEnumerator Record(string manifest, string output)
    {
        var plan = ConfigNode.Load(manifest).GetNode("CAPTURE");
        var saveFolder = plan.GetValue("saveFolder");
        int fps = int.Parse(plan.GetValue("fps"), CultureInfo.InvariantCulture);
        foreach (var shot in plan.GetNodes("SHOT"))
        {
            var name = shot.GetValue("name");
            var focusId = Guid.Parse(shot.GetValue("focusId"));
            var partnerName = shot.GetValue("partner");
            var action = shot.GetValue("action");
            int frames = int.Parse(shot.GetValue("frames"), CultureInfo.InvariantCulture);
            float distance = float.Parse(shot.GetValue("distance"), CultureInfo.InvariantCulture);
            float heading = float.Parse(shot.GetValue("heading"), CultureInfo.InvariantCulture);
            float elevation = float.Parse(shot.GetValue("elevation"), CultureInfo.InvariantCulture);
            bool sunlitSurface = bool.Parse(shot.GetValue("sunlitSurface"));
            var folder = Path.Combine(output, "frames", name);
            Directory.CreateDirectory(folder);

            Time.captureFramerate = 0;
            if (HighLogic.LoadedScene != GameScenes.MAINMENU)
            {
                HighLogic.LoadScene(GameScenes.MAINMENU);
                yield return new WaitUntil(() => HighLogic.LoadedScene == GameScenes.MAINMENU);
                yield return new WaitForSecondsRealtime(0.7f);
            }
            HighLogic.SaveFolder = saveFolder;
            var save = ConfigNode.Load(Path.Combine(KSPUtil.ApplicationRootPath, "saves", saveFolder, name + ".sfs"));
            var game = GamePersistence.LoadGameCfg(save, saveFolder, true, false);
            if (game == null)
                throw new InvalidDataException("KSP could not read " + name);
            HighLogic.CurrentGame = game;
            GamePersistence.UpdateScenarioModules(game);
            GameEvents.onGameStateCreated.Fire(game);
            GamePersistence.SaveGame(game, "persistent", saveFolder, SaveMode.OVERWRITE);
            Debug.Log("[FAM Preview] Loading " + name);
            game.Start();

            float deadline = Time.realtimeSinceStartup + 45;
            while (!HighLogic.LoadedSceneIsFlight || !FlightGlobals.ready || FlightCamera.fetch == null ||
                   FlightGlobals.ActiveVessel == null || FlightGlobals.ActiveVessel.id != focusId ||
                   FlightGlobals.ActiveVessel.packed)
            {
                if (Time.realtimeSinceStartup > deadline)
                    throw new TimeoutException("Waiting for the loaded craft in " + name);
                yield return null;
            }

            var vessel = FlightGlobals.ActiveVessel;
            Vessel partner = null;
            if (!string.IsNullOrEmpty(partnerName))
            {
                while ((partner = FlightGlobals.Vessels.FirstOrDefault(v =>
                           v.vesselName == partnerName && v.loaded && !v.packed)) == null)
                {
                    if (Time.realtimeSinceStartup > deadline)
                        throw new TimeoutException("Waiting for " + partnerName);
                    yield return null;
                }
                var axis = (Vector3)(partner.GetWorldPos3D() - vessel.GetWorldPos3D()).normalized;
                var portUp = Vector3.ProjectOnPlane(Up(vessel), axis).normalized;
                FaceDockingPort(vessel, axis, portUp);
                FaceDockingPort(partner, -axis, portUp);
                yield return new WaitForFixedUpdate();
                yield return null;
                var offset = DockingPort(vessel).position + 2.5f * axis - DockingPort(partner).position;
                partner.SetPosition((Vector3d)partner.transform.position + (Vector3d)offset, false);
            }

            Debug.Log($"[FAM Preview] {name} loaded {vessel.parts.Count} parts" +
                      (partner == null ? "" : $" and {partner.parts.Count} on {partner.vesselName}"));
            Part following = null;
            if (action == "separate" || action == "unpack")
            {
                var component = action == "unpack" ? "famJamestownCargoAdapter" : "famApolloSMBus";
                following = vessel.parts.Single(part => part.partInfo.name == component);
                if (action == "separate")
                {
                    var motor = vessel.parts.Single(part => part.partInfo.name == "famApolloSMMotor");
                    if (!motor.FindModuleImplementing<ModuleJettison>().isJettisoned)
                        throw new InvalidOperationException(name + " has a covered service engine");
                }
                OrientStack(vessel);
                FlightInputHandler.state.mainThrottle = 0;
            }
            FlightDriver.SetPause(false, false);
            ModuleDecouple roofSeparator = null;
            if (action == "roof-release")
            {
                // The preceding shot shows the S-IVB and fairing release. Start this close-up on the free payload.
                following = vessel.parts.Single(p => p.partInfo.name == "famJamestownAirlock");
                var roofPort = vessel.rootPart.FindAttachNode("top").attachedPart;
                roofSeparator = roofPort.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDecouple>();
                OrientStack(vessel);
                FlightInputHandler.state.mainThrottle = 0;
            }
            var ui = FindObjectOfType<UIMasterController>();
            if (ui != null)
                ui.HideUI();
            var camera = FlightCamera.fetch;
            var focus = new GameObject("FAM preview camera target").transform;
            focus.position = Center(vessel, partner);
            camera.setModeImmediate(FlightCamera.Modes.FREE);
            camera.SetTarget(focus, false, FlightCamera.TargetMode.Transform);
            camera.SetDistanceImmediate(distance);
            camera.SetFoV(45);
            var front = CameraSide(vessel, partner);

            Time.captureFramerate = fps;
            // Let the camera and terrain settle before counting frames.
            for (int n = 0; n < 12; n++)
            {
                Aim(camera, focus, vessel, partner, front, distance, heading, elevation, 0);
                yield return EndOfFrame;
            }
            if (partner != null)
                CheckDockingPorts(vessel, partner);
            if (sunlitSurface)
                CheckLandingSite(vessel);
            if (action == "separate" || action == "unpack")
            {
                float stageDeadline = Time.realtimeSinceStartup + 15;
                while (!StageManager.CanSeparate && Time.realtimeSinceStartup < stageDeadline)
                    yield return new WaitForFixedUpdate();
                Debug.Log($"[FAM Preview] {name} staging {StageManager.CurrentStage}, ready {StageManager.CanSeparate}, command {vessel.IsControllable}");
                if (!StageManager.CanSeparate)
                    throw new InvalidOperationException(name + " did not acquire staging control");
            }
            if (ui != null)
                ui.HideUI();
            Debug.Log("[FAM Preview] Recording " + name);
            double startAltitude = vessel.altitude;
            if (action == "lights")
                vessel.ActionGroups.SetGroup(KSPActionGroup.Light, false);
            int stepsPerPicture = action == "separate" ? 4 : action == "unpack" || action == "roof-release" ? 2 : 1;
            for (int frame = 0; frame < frames; frame++)
            {
                if (frame == fps / 2 && action == "launch")
                {
                    vessel.ActionGroups.SetGroup(KSPActionGroup.SAS, true);
                    vessel.OnFlyByWire += LaunchThrottle;
                    FlightInputHandler.state.mainThrottle = 1;
                    StageManager.ActivateNextStage();
                }
                else if ((frame == fps / 2 && action == "separate") || (frame == fps && action == "unpack"))
                {
                    StageManager.ActivateNextStage();
                }
                else if (action == "lights" && frame == fps / 2)
                {
                    vessel.ActionGroups.SetGroup(KSPActionGroup.Light, true);
                }
                else if (action == "roof-release" && frame == fps / 2)
                {
                    roofSeparator.Events["Decouple"].Invoke();
                }
                // Let physically separating modules travel far enough for their mating surfaces to read.
                for (var exposure = 0; exposure < stepsPerPicture; exposure++)
                {
                    var other = following != null && following.vessel != vessel ? following.vessel : partner;
                    Aim(camera, focus, vessel, other, front, distance, heading, elevation, (float)frame / (frames - 1));
                    yield return EndOfFrame;
                }
                var picture = ScreenCapture.CaptureScreenshotAsTexture();
                if (picture == null)
                    throw new InvalidOperationException("Unity had no frame to capture for " + name);
                try
                {
                    File.WriteAllBytes(Path.Combine(folder, frame.ToString("D4") + ".png"), picture.EncodeToPNG());
                }
                finally
                {
                    Destroy(picture);
                }
            }
            Time.captureFramerate = 0;
            if (action == "launch")
            {
                vessel.OnFlyByWire -= LaunchThrottle;
                FlightInputHandler.state.mainThrottle = 0;
                if (vessel.altitude <= startAltitude + 1)
                    throw new InvalidOperationException(name + " did not lift off");
                Debug.Log($"[FAM Preview] {name} rose {vessel.altitude - startAltitude:0.0} m");
            }
            else if (action == "separate" && vessel.parts.Exists(part => part.partInfo.name == "famApolloSMBus"))
            {
                throw new InvalidOperationException(name + " kept the service module attached");
            }
            else if (action == "unpack" && (vessel.rootPart.ShieldedFromAirstream ||
                     vessel.parts.Exists(part => part.partInfo.name == "famJamestownCargoAdapter")))
            {
                throw new InvalidOperationException($"{name} release left stage {StageManager.CurrentStage}, shielded {vessel.rootPart.ShieldedFromAirstream}, carrier attached {following.vessel == vessel}");
            }
            else if (action == "roof-release")
            {
                if (following.vessel == vessel || roofSeparator.vessel == vessel || roofSeparator.vessel == following.vessel)
                    throw new InvalidOperationException("The roof release kept its airlock or transport ring attached");
                var roof = vessel.rootPart.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>();
                var airlockPort = following.vessel.FindPartModulesImplementing<ModuleDockingNode>().Single();
                float clearance = Vector3.Distance(roof.nodeTransform.position, airlockPort.nodeTransform.position);
                if (clearance < 0.75f)
                    throw new InvalidOperationException("The two docking faces are still within magnetic capture range");
                Debug.Log($"[FAM Preview] Roof airlock clear, mating faces {clearance:0.00} m apart");
            }
            else if (action == "lights")
            {
                var lit = vessel.parts.Where(p => p.FindModulesImplementing<ModuleLight>().Any(lamp => lamp.isOn))
                                      .Select(p => p.partInfo.name).ToArray();
                if (!lit.Contains("famJamestownAirlock") || !lit.Any(p => p == "famJamestown" || p == "famJamestownFrame"))
                    throw new InvalidOperationException("The Lights action group must illuminate the airlock and base");
                Debug.Log("[FAM Preview] Lights illuminated " + string.Join(", ", lit));
            }
            camera.SetTargetVessel(vessel);
            Destroy(focus.gameObject);
            Debug.Log("[FAM Preview] Captured " + name);
            yield return null;
        }
    }

    private static void LaunchThrottle(FlightCtrlState state)
    {
        state.mainThrottle = 1;
    }

    private static void OrientStack(Vessel vessel)
    {
        var up = Up(vessel);
        var front = CameraSide(vessel, null);
        var along = (Vector3.Cross(up, front) - 0.45f * front - 0.12f * up).normalized;
        var root = vessel.rootPart;
        var turn = Quaternion.FromToRotation(root.transform.up, along);
        vessel.SetRotation(turn * root.transform.rotation * Quaternion.Inverse(root.orgRot));
        foreach (var part in vessel.parts)
            if (part.rb != null)
                part.rb.angularVelocity = Vector3.zero;
    }

    private static Vector3 HullCenter(Vessel vessel)
    {
        var bounds = new Bounds(vessel.rootPart.transform.position, Vector3.zero);
        foreach (var part in vessel.parts)
            bounds.Encapsulate(part.transform.position);
        return bounds.center;
    }

    private static Vector3 Center(Vessel vessel, Vessel partner)
    {
        if (vessel.LandedOrSplashed || vessel.situation == Vessel.Situations.PRELAUNCH ||
            (vessel.mainBody.atmosphere && vessel.altitude < vessel.mainBody.atmosphereDepth))
            return (Vector3)vessel.GetWorldPos3D();
        var center = HullCenter(vessel);
        return partner == null ? center : (center + HullCenter(partner)) / 2;
    }

    private static Vector3 Up(Vessel vessel) =>
        (Vector3)(vessel.GetWorldPos3D() - vessel.mainBody.position).normalized;

    private static void CheckLandingSite(Vessel vessel)
    {
        var body = vessel.mainBody;
        var up = body.GetSurfaceNVector(vessel.latitude, vessel.longitude);
        var sun = (Planetarium.fetch.Sun.position - body.position).normalized;
        double solarElevation = Math.Asin(Vector3d.Dot(up, sun)) * Mathf.Rad2Deg;
        double longitudeStep = 0.003 / Math.Cos(vessel.latitude * Mathf.Deg2Rad);
        double min = double.PositiveInfinity, max = double.NegativeInfinity;
        for (int north = -1; north <= 1; north++)
        for (int east = -1; east <= 1; east++)
        {
            var normal = body.GetRelSurfaceNVector(vessel.latitude + north * 0.003, vessel.longitude + east * longitudeStep);
            double height = body.pqsController.GetSurfaceHeight(normal);
            min = Math.Min(min, height);
            max = Math.Max(max, height);
        }
        if (!vessel.Landed || solarElevation < 6 || max - min > 1.25)
            throw new InvalidOperationException($"{vessel.vesselName} needs a level daylight site ({solarElevation:0.0}° Sun, {max - min:0.00} m relief)");
        Debug.Log($"[FAM Preview] {vessel.vesselName} landed with {solarElevation:0.0}° Sun elevation and {max - min:0.00} m terrain relief");
    }

    private static void FaceDockingPort(Vessel vessel, Vector3 axis, Vector3 up)
    {
        var port = DockingPort(vessel);
        var turn = Quaternion.LookRotation(axis, up) * Quaternion.Inverse(port.rotation);
        var root = vessel.rootPart;
        vessel.SetRotation(turn * root.transform.rotation * Quaternion.Inverse(root.orgRot));
        foreach (var part in vessel.parts)
            if (part.rb != null)
                part.rb.angularVelocity = Vector3.zero;
    }

    private static Transform DockingPort(Vessel vessel) => vessel.parts
        .SelectMany(part => part.Modules.OfType<ModuleDockingNode>()).Single().GetTransform();

    private static void CheckDockingPorts(Vessel vessel, Vessel partner)
    {
        var first = DockingPort(vessel);
        var second = DockingPort(partner);
        var gap = second.position - first.position;
        float angle = Vector3.Angle(gap, first.forward);
        float approach = Vector3.Angle(first.forward, -second.forward);
        if (angle > 3 || approach > 3 || gap.magnitude < 1.5f || gap.magnitude > 3.5f)
            throw new InvalidOperationException($"{vessel.vesselName} ports are misaligned ({angle:0.0}°, {approach:0.0}°, {gap.magnitude:0.0} m)");
        Debug.Log($"[FAM Preview] {vessel.vesselName} ports align within {Math.Max(angle, approach):0.0}° at {gap.magnitude:0.00} m");
    }

    private static Vector3 CameraSide(Vessel vessel, Vessel partner)
    {
        Vector3 up = Up(vessel);
        Vector3 sunlight = (Vector3)(Planetarium.fetch.Sun.position - vessel.GetWorldPos3D());
        Vector3 front = Vector3.ProjectOnPlane(sunlight, up);
        if (partner != null)
        {
            front = Vector3.Cross((Vector3)(partner.GetWorldPos3D() - vessel.GetWorldPos3D()), up);
            if (Vector3.Dot(front, sunlight) < 0)
                front = -front;
        }
        if (front.sqrMagnitude < 0.01f)
            front = Vector3.Cross(up, Vector3.forward);
        return front.normalized;
    }

    private static void Aim(FlightCamera camera, Transform focus, Vessel vessel, Vessel partner,
        Vector3 front, float distance, float heading, float elevation, float time)
    {
        Vector3 up = Up(vessel);
        // Keep the lit side selected for the whole shot as the vessels move.
        front = Vector3.ProjectOnPlane(front, up).normalized;
        float progress = Mathf.SmoothStep(0, 1, time);
        var direction = Quaternion.AngleAxis(heading - 12 + 24 * progress, up) * front;
        focus.position = Center(vessel, partner);
        float radius = distance * Mathf.Lerp(1.05f, 0.96f, progress);
        camera.SetDistanceImmediate(radius);
        camera.SetCamCoordsFromPosition(focus.position + radius * (direction + Mathf.Tan(elevation * Mathf.Deg2Rad) * up).normalized);
    }
}
