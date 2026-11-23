// Disposable flight fixture. Steering uses KSP's pilot inputs, throttle and stage button.
using System;
using System.Collections;
using System.IO;
using System.Linq;
using KSP.UI.Screens;
using UnityEngine;

[KSPAddon(KSPAddon.Startup.MainMenu, true)]
public sealed class SaturnAscentFlightTest : MonoBehaviour
{
    const string Tag = "[Saturn ascent] ";
    const double Parking = 82000;
    static readonly string[] Motors = { "famSaturnICMotor", "famSaturnIIMotor", "famSaturnIVBMotor" };
    float throttle;
    Vector3 stick;

    static void Need(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    IEnumerator Start()
    {
        if (Environment.GetEnvironmentVariable("FAM_SATURN_FLIGHT_TEST") != "1") yield break;
        DontDestroyOnLoad(gameObject);
        Application.runInBackground = true;
        var flight = Fly();
        while (true)
        {
            object next;
            try
            {
                if (!flight.MoveNext()) break;
                next = flight.Current;
            }
            catch (Exception e)
            {
                Debug.LogError(Tag + e);
                Application.Quit(1);
                yield break;
            }
            yield return next;
        }
        Debug.Log(Tag + "PASS");
        Application.Quit();
    }

    void Pilot(FlightCtrlState input)
    {
        input.pitch = stick.x;
        input.roll = stick.y;
        input.yaw = stick.z;
        input.mainThrottle = throttle;
    }

    void Steer(Vessel vessel, Vector3d target)
    {
        var control = vessel.ReferenceTransform;
        var axis = Vector3.Cross(control.up, (Vector3)target);
        float angle = Vector3.Angle(control.up, (Vector3)target) * Mathf.Deg2Rad;
        var rate = axis.normalized * Mathf.Min(0.32f, 0.75f * angle);
        var error = control.InverseTransformDirection(rate - vessel.rootPart.rb.angularVelocity);
        stick = Vector3.ClampMagnitude(-3.8f * error, 1);
    }

    static Vector3d GravityTurn(Vessel vessel, Vector3d up, int stage)
    {
        float turn = Mathf.Clamp((float)(vessel.srfSpeed - 58) * 0.085f, 0, 82);
        turn = Mathf.Lerp(turn, 90, Mathf.InverseLerp(33000, 55000, (float)vessel.altitude));
        if (vessel.altitude < 300) turn = 0;
        var east = Vector3d.Cross(up, vessel.mainBody.transform.up).normalized;
        var target = up * Math.Cos(turn * Mathf.Deg2Rad) + east * Math.Sin(turn * Mathf.Deg2Rad);
        if (stage == 0 || vessel.altitude >= 51000) return target;
        // Stay close to surface prograde while the wide payload is in dense air.
        float lead = Mathf.Lerp(3, 32, Mathf.InverseLerp(32000, 51000, (float)vessel.altitude));
        return Vector3.RotateTowards((Vector3)vessel.srf_velocity.normalized, (Vector3)target, lead * Mathf.Deg2Rad, 0);
    }

    static Part PartNamed(Vessel vessel, string name)
    {
        var part = vessel.parts.SingleOrDefault(p => p.partInfo.name == name);
        Need(part != null, $"Lost {name} at {vessel.altitude:F0} m, {vessel.srfSpeed:F0} m/s");
        return part;
    }

    IEnumerator Fly()
    {
        while (FindObjectOfType<MainMenu>() == null) yield return null;
        var settings = GameParameters.GetDefaultParameters(Game.Modes.SANDBOX, GameParameters.Preset.Normal);
        var game = GamePersistence.CreateNewGame("FAM Saturn Flight", Game.Modes.SANDBOX, settings,
            "Squad/Flags/default", GameScenes.SPACECENTER, EditorFacility.None);
        HighLogic.CurrentGame = game;
        GameEvents.onGameNewStart.Fire();
        game.Start();
        while (HighLogic.LoadedScene != GameScenes.SPACECENTER || SpaceCenter.Instance == null) yield return null;
        yield return new WaitForSecondsRealtime(1);

        var craft = Path.Combine(KSPUtil.ApplicationRootPath, "Ships", "VAB", "FAM S1 - Jamestown Delivery.craft");
        FlightDriver.StartWithNewLaunch(craft, "Squad/Flags/default", "LaunchPad", new VesselCrewManifest());
        while (!HighLogic.LoadedSceneIsFlight || !FlightGlobals.ready || FlightGlobals.ActiveVessel == null ||
               FlightGlobals.ActiveVessel.packed || StageManager.CurrentStage <= 0) yield return null;
        yield return new WaitForSeconds(1.5f);
        // The stock transfer-planner window repeatedly refreshes a missing UI panel in batch mode.
        if (Application.isBatchMode)
            foreach (var window in FindObjectsOfType<MonoBehaviour>().Where(x => x.GetType().Name == "ManeuverTool"))
                window.enabled = false;

        var vessel = FlightGlobals.ActiveVessel;
        var fairing = PartNamed(vessel, "famJamestownCargoAdapter");
        var plate = PartNamed(vessel, Motors[1]);
        var gimbal = plate.FindModuleImplementing<ModuleGimbal>();
        var skirt = plate.FindModuleImplementing<ModuleJettison>();
        var tanks = vessel.parts.Where(p => p.partInfo.name == "famJamestownDescentTank").ToArray();
        double descentFuel = tanks.Sum(t => t.GetResourceMass());
        Need(vessel.IsControllable && vessel.rootPart.ShieldedFromAirstream && tanks.Length == 4,
             "The pad craft must have a powered, shielded outpost with four descent tanks");
        Need(!skirt.isJettisoned && gimbal.gimbalRange * gimbal.gimbalLimiter / 100 >= 3.5,
             "Check the attached S-II shroud and loaded gimbal travel");
        Need(plate.FindAttachNode("top").size == 3 && plate.FindAttachNode("bottom").size == 3 &&
             plate.parent.autoStrutMode == Part.AutoStrutMode.Root,
             "The loaded S-II needs two 3.75 m engine-plate nodes and a root autostrut on its tank");
        vessel.OnFlyByWire += Pilot;
        vessel.ActionGroups.SetGroup(KSPActionGroup.SAS, false);
        vessel.Autopilot.Disable();

        int stage = 0;
        double start = Planetarium.GetUniversalTime(), stageStart = start, nextLog = start;
        double maxQ = 0, maxFlex = 0, maxSettledError = 0, maxJetAngle = 0;
        bool coast = false, circularize = false, coastWarpUsed = false;
        throttle = FlightInputHandler.state.mainThrottle = 1;
        StageManager.ActivateNextStage();
        while (vessel.orbit.PeA < 76000 || !coast)
        {
            double now = Planetarium.GetUniversalTime();
            Need(now - start < 700 && vessel.state != Vessel.State.DEAD && (now - start < 10 || !vessel.Landed),
                 "The vehicle failed to reach parking orbit");
            // Coast on rails only between atmospheric exit and the parking burn.
            if (coast && !coastWarpUsed && throttle == 0 && vessel.altitude > 70500 && vessel.orbit.timeToAp > 65)
            {
                coastWarpUsed = true;
                TimeWarp.SetRate(1, true);
                while (TimeWarp.CurrentRateIndex > 0 && vessel.orbit.timeToAp > 45) yield return null;
                TimeWarp.SetRate(0, true);
                while (vessel.packed || TimeWarp.CurrentRateIndex != 0) yield return null;
            }
            Need(TimeWarp.CurrentRateIndex == 0, "Powered ascent requires normal flight physics");
            var engine = PartNamed(vessel, Motors[stage]).FindModuleImplementing<ModuleEngines>();
            if (stage < 2 && engine.part.parent.Resources.Get("LiquidFuel").amount < 0.05 && now - stageStart > 3)
            {
                StageManager.ActivateNextStage();
                stage++;
                stageStart = now;
                Debug.Log(Tag + $"{Motors[stage]} handoff at {vessel.altitude:F0} m, {vessel.srfSpeed:F0} m/s");
                yield return new WaitForFixedUpdate();
                continue;
            }
            var up = (vessel.GetWorldPos3D() - vessel.mainBody.position).normalized;
            var target = GravityTurn(vessel, up, stage);
            if (vessel.orbit.ApA >= Parking && vessel.verticalSpeed > 0) coast = true;
            if (coast)
            {
                var horizontal = Vector3d.Exclude(up, vessel.obt_velocity);
                target = horizontal.normalized;
                double speed = Math.Sqrt(vessel.mainBody.gravParameter / (vessel.mainBody.Radius + Parking));
                double deficit = speed - horizontal.magnitude;
                double acceleration = engine.maxThrust / vessel.GetTotalMass();
                if (vessel.orbit.timeToAp <= Math.Max(5, 0.52 * deficit / (0.57 * acceleration) + 3) ||
                    vessel.verticalSpeed < 0) circularize = true;
                throttle = circularize ? Mathf.Clamp((float)(deficit / (1.4 * acceleration)), 0.04f, 0.68f) : 0;
            }
            Steer(vessel, target);
            FlightInputHandler.state.mainThrottle = throttle;
            maxQ = Math.Max(maxQ, vessel.dynamicPressurekPa);
            double error = Vector3.Angle(vessel.ReferenceTransform.up, (Vector3)target);
            if (stage == 1)
            {
                maxFlex = Math.Max(maxFlex, Vector3.Angle(plate.transform.up, plate.parent.transform.up));
                maxJetAngle = Math.Max(maxJetAngle,
                    Vector3.Angle(plate.transform.up, -engine.thrustTransforms[0].forward));
                if (now - stageStart > 5)
                {
                    Need(skirt.isJettisoned && engine.EngineIgnited, "The S-II shroud failed to clear or ignition failed");
                    if (vessel.dynamicPressurekPa > 0.5) maxSettledError = Math.Max(maxSettledError, error);
                }
            }
            if (now >= nextLog)
            {
                Debug.Log(Tag + $"t {now-start:F0}, {Motors[stage]}, altitude {vessel.altitude:F0}, " +
                          $"q {vessel.dynamicPressurekPa:F2} kPa, steering error {error:F2}°, max mount flex {maxFlex:F2}°");
                nextLog = now + 8;
            }
            yield return new WaitForFixedUpdate();
        }

        throttle = FlightInputHandler.state.mainThrottle = 0;
        Need(stage >= 1 && vessel.orbit.ApA < 110000 && maxQ > 5, "Check stage sequence, orbit and peak pressure");
        Need(maxSettledError < 12 && maxFlex < 1 && maxJetAngle > 0.1,
             $"S-II settled pointing error {maxSettledError:F2}°, peak joint flex {maxFlex:F2}°, nozzle travel {maxJetAngle:F2}°");
        if (stage == 1) StageManager.ActivateNextStage();
        yield return new WaitForFixedUpdate();
        var transfer = PartNamed(vessel, Motors[2]).FindModuleImplementing<ModuleEngines>();
        double fuel = transfer.part.parent.GetResourceMass();
        double wet = vessel.GetTotalMass();
        double remaining = transfer.atmosphereCurve.Evaluate(0) * 9.80665 * Math.Log(wet / (wet - fuel));
        Debug.Log(Tag + $"PARKING {vessel.orbit.PeA:F0} x {vessel.orbit.ApA:F0} m; loaded S-IVB {remaining:F0} m/s; " +
                  $"peak q {maxQ:F1} kPa; S-II post-handoff error {maxSettledError:F2}°, mount flex {maxFlex:F2}°, " +
                  $"nozzle travel {maxJetAngle:F2}°");
        Need(remaining >= 860 + 310 + 340, "Parking orbit consumed the required polar transfer and capture reserve");
        Need(Math.Abs(descentFuel - tanks.Sum(t => t.GetResourceMass())) < 0.001, "The launcher drained the descent tanks");
        // KSP briefly locks staging after discarding S-II. A player would normally coast to the Mun here.
        var parked = HighLogic.CurrentGame.Updated(GameScenes.FLIGHT);
        parked.startScene = GameScenes.FLIGHT;
        GamePersistence.SaveGame(parked, "parking", HighLogic.SaveFolder, SaveMode.OVERWRITE);
        double stageDeadline = Planetarium.GetUniversalTime() + 8;
        while (!StageManager.CanSeparate && Planetarium.GetUniversalTime() < stageDeadline)
            yield return new WaitForFixedUpdate();
        Need(StageManager.CanSeparate && StageManager.CurrentStage == fairing.inverseStage + 1,
             $"Payload release is unavailable. Current stage {StageManager.CurrentStage}, adapter stage {fairing.inverseStage}");
        StageManager.ActivateNextStage();
        yield return new WaitForSeconds(4);
        Need(!vessel.rootPart.ShieldedFromAirstream && fairing.vessel != vessel, "Payload failed to clear the carrier");
        int sparks = vessel.parts.Count(p => p.partInfo.name == "liquidEngineMini.v2" &&
                                        p.FindModuleImplementing<ModuleEngines>().EngineIgnited);
        Need(sparks == 4 && vessel.IsControllable, "Payload release must leave a controllable outpost with four lit Sparks");
        Debug.Log(Tag + $"RELEASED {vessel.parts.Count} parts with the hull unshielded and {sparks} Sparks ignited");
        vessel.OnFlyByWire -= Pilot;
    }
}
