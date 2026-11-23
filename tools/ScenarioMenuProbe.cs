using System;
using System.Collections;
using System.IO;
using System.Linq;
using System.Reflection;
using FAMSeasons;
using KSP.UI.Screens;
using KSP.UI.Screens.Flight.Dialogs;
using UnityEngine;

[KSPAddon(KSPAddon.Startup.MainMenu, true)]
public sealed class ScenarioMenuProbe : MonoBehaviour
{
    private const BindingFlags Nonpublic = BindingFlags.Instance | BindingFlags.NonPublic;
    private string output;
    private IEnumerator Start()
    {
        output = Environment.GetEnvironmentVariable("FAM_SCENARIO_TEST_DIR");
        if (string.IsNullOrWhiteSpace(output))
            yield break;
        DontDestroyOnLoad(gameObject);
        Application.runInBackground = true;
        var probe = Test();
        while (true)
        {
            object step;
            try
            {
                if (!probe.MoveNext())
                    break;
                step = probe.Current;
            }
            catch (Exception error)
            {
                Debug.LogException(error);
                File.WriteAllText(Path.Combine(output, "error.txt"), error.ToString());
                Application.Quit(1);
                yield break;
            }
            yield return step;
        }
        File.WriteAllText(Path.Combine(output, "passed.txt"), "Stock Scenarios menu. Both pad starts, Jamestown core and resume passed.\n");
        Application.Quit();
    }

    private IEnumerator Test()
    {
        string[] titles = { "FAM S1.1 - Red Mun", "FAM S1.2 - Apollo 11", "FAM S1.3 - Jamestown Campaign", "FAM S1.3 - Jamestown Campaign" };
        string[] vessels = { "Red Mun", "Apollo 11", "Falcon", "Falcon" };
        string[] engines = { "famN1AMotor", "famSaturnICMotor" };
        int first = 0;
        foreach (var craft in Directory.GetFiles(Path.Combine(KSPUtil.ApplicationRootPath, "Ships", "VAB"), "FAM S1 - *.craft"))
        {
            var ship = ShipConstruction.LoadShip(craft);
            Need(ship != null && ship.parts.Count >= 9, "KSP could not instantiate " + craft);
            Debug.Log($"[FAM Scenario Probe] Loaded exact VAB craft {ship.shipName} with {ship.parts.Count} parts.");
            ship.Clear();
        }
        for (int i = first; i < titles.Length; i++)
        {
            if (i != first)
                HighLogic.LoadScene(GameScenes.MAINMENU);
            float deadline = Time.realtimeSinceStartup + 30;
            MainMenu menu = null;
            while (HighLogic.LoadedScene != GameScenes.MAINMENU || (menu = FindObjectOfType<MainMenu>()) == null)
            {
                Need(Time.realtimeSinceStartup < deadline, "Timed out loading the main menu");
                yield return null;
            }
            yield return new WaitForSecondsRealtime(1.0f);
            Method(menu, "StartScenario");
            ScenarioLoadDialog dialog = null;
            while ((dialog = FindObjectOfType<ScenarioLoadDialog>()) == null ||
                !((IEnumerable)Field(dialog, "saves").GetValue(dialog)).Cast<object>().Any())
            {
                Need(Time.realtimeSinceStartup < deadline, "Timed out opening the stock scenario dialog");
                yield return null;
            }
            var selected = ((IEnumerable)Field(dialog, "saves").GetValue(dialog)).Cast<object>()
                .Single(save => (string)Field(save, "name").GetValue(save) == titles[i]);
            Need((bool)Method(selected, "CanRestart") == (i == 3), titles[i] + " selected an unexpected start or resume");
            var selectedPath = (string)Method(selected, "LoadPath");
            Debug.Log("[FAM Scenario Probe] Menu loads " + selectedPath);
            if (i < 2)
            {
                var authored = ConfigNode.Load(selectedPath).GetNode("GAME").GetNode("FLIGHTSTATE").GetNode("VESSEL");
                Need(authored.GetValue("sit") == "PRELAUNCH" && authored.GetValue("landedAt") == "LaunchPad",
                    titles[i] + " must start prelaunch at the launchpad");
            }
            yield return new WaitForSecondsRealtime(0.5f);
            Field(dialog, "selectedGame").SetValue(dialog, selected);
            Method(dialog, "OnButtonLoad");

            if (i == 3)
            {
                yield return new WaitForSecondsRealtime(3f);
                if (HighLogic.LoadedScene == GameScenes.SPACECENTER)
                    FlightDriver.StartAndFocusVessel(HighLogic.CurrentGame, 0);
            }
            deadline = Time.realtimeSinceStartup + 45;
            while (!HighLogic.LoadedSceneIsFlight || !FlightGlobals.ready || FlightGlobals.ActiveVessel == null ||
                FlightGlobals.ActiveVessel.packed)
            {
                Need(Time.realtimeSinceStartup < deadline, "Timed out entering flight for " + titles[i]);
                yield return null;
            }
            yield return new WaitForSecondsRealtime(1.5f);
            var vessel = FlightGlobals.ActiveVessel;
            Need(HighLogic.CurrentGame.Mode == Game.Modes.SCENARIO && Contracts.ContractSystem.Instance == null,
                "Standalone scenarios should have a checklist without Career offers");
            var guide = FindObjectOfType<FAMScenarioObjectives>();
            Need(vessel.vesselName == vessels[i] && guide != null, "Wrong vessel or missing checklist on " + titles[i]);
            Debug.Log($"[FAM Scenario Probe] {vessel.vesselName} {vessel.situation}, {vessel.parts.Count} parts, crew {vessel.GetVesselCrew().Count}, stage {StageManager.CurrentStage}");
            if (i < 2)
            {
                // KSP can change PRELAUNCH to LANDED as the stack settles on the pad.
                bool onPad = vessel.Landed && vessel.mainBody.bodyName == "Kerbin" &&
                             Math.Abs(vessel.latitude + 0.0972078) < 0.001 && Math.Abs(vessel.longitude + 74.5576741) < 0.001;
                Need(onPad && StageManager.CurrentStage == 8 - i,
                    titles[i] + " needs the correct pad stage");
                Need(vessel.GetVesselCrew().Count == i + 2, titles[i] + " has wrong crew count");
                var engine = vessel.parts.Single(part => part.partInfo.name == engines[i]).Modules.OfType<ModuleEnginesFX>().Single();
                Need(!engine.EngineIgnited && vessel.Landed, "The first engine must start shut down on the pad");
                yield return new WaitForEndOfFrame();
                Capture(i == 0 ? "red-mun-menu" : "apollo-menu");

                double initial = vessel.altitude;
                vessel.ActionGroups.SetGroup(KSPActionGroup.SAS, true);
                vessel.OnFlyByWire += Throttle;
                FlightInputHandler.state.mainThrottle = 1;
                StageManager.ActivateNextStage();
                deadline = Time.realtimeSinceStartup + 15f;
                while ((vessel.Landed || vessel.altitude <= initial + 1) && Time.realtimeSinceStartup < deadline)
                    yield return new WaitForFixedUpdate();
                Need(engine.EngineIgnited && !vessel.Landed && vessel.altitude > initial + 1, "No liftoff for " + titles[i]);
                Debug.Log($"[FAM Scenario Probe] {vessel.vesselName} lifted off and climbed {vessel.altitude - initial:0.0} m.");
                vessel.OnFlyByWire -= Throttle;
                FlightInputHandler.state.mainThrottle = 0;
            }
            if (i == 2)
            {
                Need(vessel.Landed && Progress(guide) == 0, "Falcon needs a fresh checklist on the Mun");
                var corer = vessel.parts.Single(part => part.partInfo.name == "famIceCorer").Modules.OfType<ModuleScienceExperiment>().Single();
                yield return new WaitForEndOfFrame();
                var camera = FlightCamera.fetch;
                var surface = (vessel.GetWorldPos3D() - vessel.mainBody.position).normalized;
                var sunlight = (Planetarium.fetch.Sun.position - vessel.mainBody.position).normalized;
                double sun = Math.Asin(Vector3d.Dot(surface, sunlight)) * Mathf.Rad2Deg;
                Need(sun >= 10, "Falcon needs a daylight start");
                var front = (Vector3)Vector3d.Exclude(surface, sunlight).normalized;
                var view = Quaternion.AngleAxis(20, (Vector3)surface) * front + 0.12f * (Vector3)surface;
                camera.setModeImmediate(FlightCamera.Modes.FREE);
                camera.SetDistanceImmediate(12);
                camera.SetCamCoordsFromPosition((Vector3)vessel.GetWorldPos3D() + 12 * view.normalized);
                yield return new WaitForSecondsRealtime(1.0f);
                yield return new WaitForEndOfFrame();
                Capture("jamestown-daylight");
                Debug.Log($"[FAM Scenario Probe] Falcon day start: {sun:0.0}° Sun elevation.");

                var run = corer.Events["DeployExperiment"];
                Need(run.active && run.guiName == "Drill a regolith core", "The sampler action must be available on Falcon");
                run.Invoke();
                ExperimentsResultDialog results = null;
                while ((results = FindObjectOfType<ExperimentsResultDialog>()) == null)
                {
                    Need(Time.realtimeSinceStartup < deadline, "The sampler did not open its science results");
                    yield return null;
                }
                yield return new WaitForSecondsRealtime(0.7f);
                Need(Progress(guide) == 0, "The checklist advanced before the experiment was kept");
                Method(results, "onBtnDiscard");
                yield return new WaitForSecondsRealtime(0.7f);
                Need(Progress(guide) == 0 && !corer.GetData().Any(), "Discarding the sample must leave the first step open");
                run.Invoke();
                while ((results = FindObjectOfType<ExperimentsResultDialog>()) == null)
                {
                    Need(Time.realtimeSinceStartup < deadline, "A discarded sample could not be collected again");
                    yield return null;
                }
                Method(results, "onBtnKeep");
                yield return new WaitForSecondsRealtime(0.7f);
                Need(Progress(guide) == 1, "Keeping the core did not advance the checklist");
                yield return new WaitForEndOfFrame();
                Capture("jamestown-next-step");
                GamePersistence.SaveGame(HighLogic.CurrentGame.Updated(GameScenes.FLIGHT), "persistent", HighLogic.SaveFolder, SaveMode.OVERWRITE);
                Debug.Log("[FAM Scenario Probe] Kept Falcon's core and saved step 2.");
            }
            if (i == 3)
            {
                Need(Progress(guide) == 1, "Resuming Jamestown lost the core objective");
                Need(vessel.parts.Single(part => part.partInfo.name == "famIceCorer").Modules.OfType<ModuleScienceExperiment>()
                    .Single().GetData().Any(data => data.subjectID.StartsWith("famPolarCore@MunSrfLanded")),
                    "Resuming Jamestown lost the sample");
                Debug.Log("[FAM Scenario Probe] The menu resumed Falcon with its core and checklist progress.");
            }
        }
    }


    private static int Progress(FAMScenarioObjectives guide)
    {
        var plan = Field(guide, "plan").GetValue(guide);
        return (int)plan.GetType().GetProperty("Completed").GetValue(plan);
    }

    private static void Throttle(FlightCtrlState state) { state.mainThrottle = 1; }
    private static FieldInfo Field(object obj, string field) => obj.GetType().GetField(field, Nonpublic | BindingFlags.Public);
    private static object Method(object obj, string method) => obj.GetType().GetMethod(method, Nonpublic | BindingFlags.Public).Invoke(obj, null);
    private static void Need(bool okay, string message)
    {
        if (!okay)
            throw new InvalidOperationException(message);
    }

    private void Capture(string name)
    {
        var shot = ScreenCapture.CaptureScreenshotAsTexture();
        File.WriteAllBytes(Path.Combine(output, name + ".png"), shot.EncodeToPNG());
        Destroy(shot);
    }
}
