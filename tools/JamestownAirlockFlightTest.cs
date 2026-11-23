// Disposable stock-physics fixture for the packed Jamestown and its actual docking ports.
using System;
using System.Collections;
using System.IO;
using System.Linq;
using KSP.UI.Screens;
using UnityEngine;

[KSPAddon(KSPAddon.Startup.MainMenu, true)]
public sealed class JamestownAirlockFlightTest : MonoBehaviour
{
    const string Tag = "[Airlock flight] ";
    const string SaveFolder = "FAM Airlock Test";

    static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    IEnumerator Start()
    {
        string mode = Environment.GetEnvironmentVariable("FAM_AIRLOCK_TEST");
        if (mode != "fresh" && mode != "saved") yield break;
        DontDestroyOnLoad(gameObject);
        Application.runInBackground = true;
        var flight = Fly(mode == "saved");
        while (true)
        {
            object next;
            try
            {
                if (!flight.MoveNext()) break;
                next = flight.Current;
            }
            catch (Exception error)
            {
                Debug.LogError(Tag + error);
                Application.Quit(1);
                yield break;
            }
            yield return next;
        }
        Debug.Log(Tag + "PASS " + mode);
        Application.Quit();
    }

    IEnumerator Fly(bool resume)
    {
        while (FindObjectOfType<MainMenu>() == null) yield return null;
        if (resume)
        {
            HighLogic.SaveFolder = SaveFolder;
            string save = Path.Combine(KSPUtil.ApplicationRootPath, "saves", SaveFolder, "packed.sfs");
            var game = GamePersistence.LoadGameCfg(ConfigNode.Load(save), SaveFolder, true, false);
            game.startScene = GameScenes.FLIGHT;
            HighLogic.CurrentGame = game;
            GamePersistence.UpdateScenarioModules(game);
            GameEvents.onGameStateCreated.Fire(game);
            game.Start();
        }
        else
        {
            var settings = GameParameters.GetDefaultParameters(Game.Modes.SANDBOX, GameParameters.Preset.Normal);
            var game = GamePersistence.CreateNewGame(SaveFolder, Game.Modes.SANDBOX, settings,
                "Squad/Flags/default", GameScenes.SPACECENTER, EditorFacility.None);
            HighLogic.CurrentGame = game;
            GameEvents.onGameNewStart.Fire();
            game.Start();
            while (HighLogic.LoadedScene != GameScenes.SPACECENTER || SpaceCenter.Instance == null) yield return null;
            yield return new WaitForSecondsRealtime(1);
            string craft = Path.Combine(KSPUtil.ApplicationRootPath, "Ships", "VAB", "FAM S1 - Jamestown Delivery.craft");
            FlightDriver.StartWithNewLaunch(craft, "Squad/Flags/default", "LaunchPad", new VesselCrewManifest());
        }
        while (!HighLogic.LoadedSceneIsFlight || !FlightGlobals.ready || FlightGlobals.ActiveVessel == null ||
               FlightGlobals.ActiveVessel.packed) yield return null;
        yield return new WaitForSeconds(1.5f);
        if (Application.isBatchMode)
            foreach (var window in FindObjectsOfType<MonoBehaviour>().Where(x => x.GetType().Name == "ManeuverTool"))
                window.enabled = false;
        var hull = FlightGlobals.ActiveVessel.parts.Single(p => p.partInfo.name == "famJamestown");
        var roof = hull.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>();
        var ring = roof.part.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDecouple>();
        var collar = ring.part.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>();
        var airlock = collar.part.FindAttachNode("bottom").attachedPart;
        var fairing = hull.vessel.parts.SingleOrDefault(p => p.partInfo.name == "famJamestownCargoAdapter");

        if (!resume)
        {
            // Use the stock debug menu's orbit setter so the exact VAB vehicle can exercise its own stages.
            var kerbin = hull.vessel.mainBody;
            FlightGlobals.fetch.SetShipOrbit(kerbin.flightGlobalsIndex, 0, kerbin.Radius + 90000, 0, 0, 0, 0, 0);
            yield return new WaitForSeconds(4);
            Require(hull.vessel.orbit.PeA > 80000, "Could not place the launch stack in the test orbit.");
        }
        if (fairing != null)
        {
            for (int i = 0; i < 8 && fairing.vessel == hull.vessel; i++)
            {
                int tick = 0;
                while (!StageManager.CanSeparate && tick++ < 600) yield return new WaitForFixedUpdate();
                Require(StageManager.CanSeparate, "Stock staging never became available for carrier release.");
                StageManager.ActivateNextStage();
                yield return new WaitForSeconds(1.5f);
            }
            Require(fairing.vessel != hull.vessel && !hull.ShieldedFromAirstream, "Outpost is still on its carrier.");
        }
        Require(hull.vessel == airlock.vessel && !ring.isDecoupled, "Expected an intact roof-stowed airlock.");
        string source = Environment.GetEnvironmentVariable("FAM_AIRLOCK_RELEASE") ?? (resume ? "separator" : "hull");
        BaseEvent release;
        switch (source)
        {
            case "hull": release = hull.Modules["FAMDockControls"].Events["ReleaseRoofAirlock"]; break;
            case "separator": release = ring.Events["Decouple"]; break;
            case "roof-port": release = roof.Events["Undock"]; break;
            case "airlock-port": release = collar.Events["Undock"]; break;
            default: throw new ArgumentException("Unknown release action " + source);
        }
        Require(release != null && release.active && release.guiActive, "The player cannot release from " + source);
        float releasedAt = Time.fixedTime;
        release.Invoke();
        yield return new WaitForSeconds(8);
        Require(airlock.vessel != hull.vessel && airlock.vessel.parts.Count == 2 &&
                ring.part.vessel.parts.Count == 1 && ring.isDecoupled, "The stock TS-12 did not separate all three pieces.");
        // The freshly separated carrier can leave the rotating roof pointed back at the drifting ring.
        // Wait until two 1.25 m diameter collars can pass side by side in the current roof frame.
        Vector3 ringOffset;
        float ringLateral;
        do
        {
            yield return new WaitForFixedUpdate();
            ringOffset = ring.part.transform.position - roof.nodeTransform.position;
            ringLateral = Vector3.ProjectOnPlane(ringOffset, roof.nodeTransform.forward).magnitude;
        }
        while (ringLateral <= 1.25f && Time.fixedTime < releasedAt + 18f);
        float gap = Vector3.Distance(roof.nodeTransform.position, collar.nodeTransform.position);
        Debug.Log(Tag + $"{Time.fixedTime - releasedAt:F1} seconds after release from {source} the port faces are {gap:F2} m apart, " +
                  $"the ring is {ringOffset.magnitude:F2} m from the roof and {ringLateral:F2} m off its docking axis. " +
                  $"The ports read {roof.state}/{collar.state}.");
        Require(gap > roof.minDistanceToReEngage && ringLateral > 1.25f &&
                roof.otherNode == null && collar.otherNode == null &&
                roof.state == "Ready" && collar.state == "Ready", "The airlock or spent ring is still on the roof.");
        Require(!hull.Modules["FAMDockControls"].Events["ReleaseRoofAirlock"].guiActive,
                "The empty roof still displays an airlock release action.");
        Require(airlock.vessel.IsControllable && airlock.FindModuleImplementing<ModuleRCS>() != null,
                "Detached airlock has no independent control or RCS.");
        FlightGlobals.SetActiveVessel(airlock.vessel);
        yield return new WaitForSeconds(0.6f);
        var propellant = airlock.Resources.Get("MonoPropellant");
        double before = propellant.amount;
        airlock.vessel.ActionGroups.SetGroup(KSPActionGroup.RCS, true);
        FlightInputCallback translate = input => input.Z = 1f;
        airlock.vessel.OnFlyByWire += translate;
        yield return new WaitForSeconds(0.8f);
        airlock.vessel.OnFlyByWire -= translate;
        airlock.vessel.ActionGroups.SetGroup(KSPActionGroup.RCS, false);
        Require(propellant.amount < before, "The detached airlock's translation input did not fire its own RCS.");
        Debug.Log(Tag + $"A pilot translation pulse spent {before - propellant.amount:F4} units of airlock monopropellant.");
        var frontServo = hull.FindAttachNode("airlock").attachedPart;
        var side = frontServo.FindAttachNode("top").attachedPart.FindModuleImplementing<ModuleDockingNode>();
        var sideDock = ApproachAndDock(collar, side);
        while (sideDock.MoveNext()) yield return sideDock.Current;
        Require(roof.state == "Ready", "The empty roof port did not return to Ready.");
        Undock(collar, side);
        yield return new WaitForFixedUpdate();
        Require(airlock.vessel != hull.vessel, "Stock Undock failed at the side port.");
        airlock.vessel.Translate((Vector3d)(side.nodeTransform.forward * 3f));
        yield return new WaitForSeconds(1.5f);
        var roofDock = ApproachAndDock(collar, roof);
        while (roofDock.MoveNext()) yield return roofDock.Current;
        Debug.Log(Tag + "The airlock docked to the front Clamp-O-Tron, undocked, and docked again to the cleared roof.");
        Undock(collar, roof);
        yield return new WaitForFixedUpdate();
        var lamps = JamestownLightFlightTest.CheckIndependent(hull, airlock);
        while (lamps.MoveNext()) yield return lamps.Current;
    }

    static void Undock(ModuleDockingNode collar, ModuleDockingNode station)
    {
        var action = new[] { collar.Events["Undock"], station.Events["Undock"] }
            .FirstOrDefault(item => item.active && item.guiActive);
        Require(action != null, "No stock Undock action on the assembled airlock.");
        action.Invoke();
    }

    static IEnumerator ApproachAndDock(ModuleDockingNode collar, ModuleDockingNode station)
    {
        var visitor = collar.vessel;
        var target = station.nodeTransform;
        // Align as a pilot would. Stock attraction and capture make the joint.
        for (int tick = 0; tick < 160 && collar.vessel != station.vessel; tick++)
        {
            var guest = collar.nodeTransform;
            var align = Quaternion.LookRotation(-target.forward, target.up) * Quaternion.Inverse(guest.rotation);
            visitor.SetRotation(align * visitor.transform.rotation, false);
            visitor.Translate((Vector3d)(target.position + target.forward * 0.045f - guest.position));
            foreach (var piece in visitor.parts)
            {
                piece.rb.velocity = station.part.rb.velocity;
                piece.rb.angularVelocity = station.part.rb.angularVelocity;
            }
            Physics.SyncTransforms();
            yield return new WaitForFixedUpdate();
        }
        yield return new WaitForSeconds(1.5f);
        Require(collar.vessel == station.vessel && station.otherNode == collar &&
                station.state.StartsWith("Docked", StringComparison.Ordinal),
                $"Stock docking failed. Target {station.state}, airlock {collar.state}.");
    }
}
