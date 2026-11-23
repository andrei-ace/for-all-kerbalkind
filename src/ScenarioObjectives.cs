using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace FAMSeasons
{
    public sealed class FAMScenarioObjectives : ScenarioModule
    {
        private ScenarioPlan plan;
        private ScenarioPlan[] operations;
        private Dictionary<uint, ScenarioAsset> assets;
        private ScenarioFrame latest;
        private bool keptCore;
        private float nextCheck;
        private Rect window;
        private bool collapsed, hideUi;
        private Vessel pendingSwitch;
        private GUIStyle heading;

        public override void OnAwake()
        {
            base.OnAwake();
            GameEvents.OnExperimentStored.Add(OnExperimentStored);
            GameEvents.onHideUI.Add(HideUi);
            GameEvents.onShowUI.Add(ShowUi);
        }

        private void OnDestroy()
        {
            GameEvents.OnExperimentStored.Remove(OnExperimentStored);
            GameEvents.onHideUI.Remove(HideUi);
            GameEvents.onShowUI.Remove(ShowUi);
        }

        private void OnExperimentStored(ScienceData data)
        {
            if (data == null || !IsCore(data.subjectID) || plan?.Mission != "into-the-crater" || plan.Completed != 0)
                return;
            var sampler = plan.Assets.Single(asset => asset.Role == "corer");
            keptCore = FlightGlobals.ActiveVessel.parts.Any(part => part.persistentId == sampler.PartId &&
                part.Modules.OfType<IScienceDataContainer>().Any(container => container.GetData().Contains(data)));
        }

        private void HideUi() => hideUi = true;
        private void ShowUi() => hideUi = false;

        public override void OnLoad(ConfigNode node)
        {
            base.OnLoad(node);
            bool.TryParse(node.GetValue("keptCore"), out keptCore);
            operations = LoadOperations(node);
            SelectOperation();
        }

        internal static ScenarioPlan[] LoadOperations(ConfigNode node)
        {
            var children = node.GetNodes("OPERATION");
            return (children.Length == 0 ? new [] { node } : children)
                .Select(operation => new ScenarioPlan(operation)).ToArray();
        }

        internal static ScenarioPlan CurrentOperation(ScenarioPlan[] operations) =>
            operations.FirstOrDefault(operation => !operation.Finished) ?? operations.Last();

        private void SelectOperation()
        {
            plan = CurrentOperation(operations);
            assets = plan.Assets.ToDictionary(asset => asset.PartId);
            latest = null;
            nextCheck = 0;
            Debug.Log($"[FAMSeasons] Loaded {plan.Mission} objectives ({plan.Completed}/{plan.Steps.Count}).");
        }

        public override void OnSave(ConfigNode node)
        {
            base.OnSave(node);
            node.SetValue("keptCore", keptCore, true);
            node.SetValue("fleet", "modular", true);
            if (operations == null)
                return;
            SaveOperations(node, operations);
        }

        internal static void SaveOperations(ConfigNode node, ScenarioPlan[] operations)
        {
            if (operations.Length == 1)
                operations[0].Save(node);
            else
            {
                node.RemoveNodes("OPERATION");
                foreach (var operation in operations)
                    operation.Save(node.AddNode("OPERATION"));
            }
        }

        private void Update()
        {
            if (plan == null || plan.Finished || !FlightGlobals.ready)
                return;
            if (pendingSwitch != null)
            {
                var vessel = pendingSwitch;
                pendingSwitch = null;
                if (FlightGlobals.ClearToSave() == ClearToSaveStatus.CLEAR)
                    FlightGlobals.SetActiveVessel(vessel);
                return;
            }
            if (Time.unscaledTime < nextCheck)
                return;
            nextCheck = Time.unscaledTime + 0.2f;
            latest = ReadFlight();
            if (plan.CurrentStep.VesselRole == "lander" && plan.Mission == "into-the-crater" &&
                plan.Completed == 0 && !keptCore)
                return;
            var previous = plan.Completed;
            plan.Advance(latest);
            if (plan.Completed != previous)
                Debug.Log($"[FAMSeasons] {plan.Mission} objectives {plan.Completed}/{plan.Steps.Count} complete.");
            if (plan.Finished)
            {
                SelectOperation();
                var message = plan.Finished ? "For All Kerbalkind mission complete" :
                    "Next in Mission Checklist: " + plan.CurrentStep.Title;
                ScreenMessages.PostScreenMessage(message, 4f, ScreenMessageStyle.UPPER_CENTER);
            }
        }

        private void OnGUI()
        {
            if (plan == null || hideUi || !HighLogic.LoadedSceneIsFlight || !FlightGlobals.ready)
                return;
            if (heading == null)
                heading = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, wordWrap = true };
            if (window.width == 0)
                window = new Rect(Math.Max(12, Screen.width - 408), 115, 364, 20);
            window.x = Mathf.Clamp(window.x, 0, Math.Max(0, Screen.width - window.width));
            window.y = Mathf.Clamp(window.y, 0, Math.Max(0, Screen.height - window.height));
            window = GUILayout.Window(GetInstanceID(), window, DrawChecklist, "Mission Checklist", GUILayout.Width(364));
        }

        private void DrawChecklist(int id)
        {
            if (!collapsed)
            {
                if (operations.Length > 1)
                {
                    foreach (var group in operations.GroupBy(operation => operation.Milestone))
                        DrawMilestone(group.Key, group.All(operation => operation.Finished), group.Contains(plan));
                }
                else if (plan.FromPad)
                {
                    int returnStart = plan.Steps.Count - 3;
                    DrawMilestone("Launch and enter Mun orbit", plan.Completed >= 2, plan.Completed < 2);
                    DrawMilestone("Land and reunite the crew", plan.Completed >= returnStart, plan.Completed >= 2);
                    DrawMilestone("Return to Kerbin", plan.Finished, plan.Completed >= returnStart);
                }
                if (plan.Finished)
                    GUILayout.Label(plan.ReturnsToKerbin ? "Mission complete. Use Recover Vessel." : "Mission complete.");
                else
                {
                    GUILayout.Space(5);
                    var step = plan.CurrentStep;
                    var part = latest?[step.VesselRole];
                    var vessel = part == null ? null : FlightGlobals.FindVessel(part.Vessel.Id);
                    string stepCount = $"Step {plan.Completed + 1} of {plan.Steps.Count}";
                    GUILayout.Label(vessel == null ? stepCount : $"{stepCount}   |   {vessel.vesselName}");
                    GUILayout.Label(step.Title, heading);
                    GUILayout.Label(step.Hint);
                    string status = plan.Status(latest);
                    if (!string.IsNullOrEmpty(status))
                        GUILayout.Label(status);
                    if (vessel != null && vessel != FlightGlobals.ActiveVessel)
                    {
                        bool enabled = GUI.enabled;
                        GUI.enabled = enabled && FlightGlobals.ClearToSave() == ClearToSaveStatus.CLEAR;
                        if (GUILayout.Button("Switch to " + vessel.vesselName))
                            pendingSwitch = vessel;
                        GUI.enabled = enabled;
                    }
                }
            }
            if (GUILayout.Button(collapsed ? "Show mission guide" : "Hide mission guide"))
            {
                collapsed = !collapsed;
                window.height = 20;
            }
            GUI.DragWindow(new Rect(0, 0, window.width, 19));
        }

        private static void DrawMilestone(string title, bool done, bool current)
        {
            string mark = done ? "[x]" : current ? ">" : "[ ]";
            GUILayout.Label(mark + " " + title);
        }

        private ScenarioFrame ReadFlight()
        {
            var frame = new ScenarioFrame { UniversalTime = Planetarium.GetUniversalTime() };
            foreach (var vessel in FlightGlobals.Vessels)
            {
                if (vessel == null || vessel.mainBody == null || vessel.state == Vessel.State.DEAD)
                    continue;
                ScenarioVessel reading = null;
                if (vessel.loaded)
                {
                    foreach (var part in vessel.parts)
                    {
                        if (!assets.TryGetValue(part.persistentId, out var asset))
                            continue;
                        reading = reading ?? ReadVessel(vessel);
                        var observed = new ScenarioPart {
                            Vessel = reading,
                            Crew = part.protoModuleCrew.Select(crew => crew.name).ToArray(),
                            Upright = asset.Role == "habitat" && HabitatCondition.IsUpright(part, vessel.mainBody),
                            Core = ReadsCore(asset) && part.Modules.OfType<IScienceDataContainer>()
                                .SelectMany(container => container.GetData() ?? Array.Empty<ScienceData>())
                                .Any(data => IsCore(data.subjectID))
                        };
                        foreach (PartResource resource in part.Resources)
                            RecordResource(observed, resource.resourceName, resource.amount);
                        frame.Parts[asset.Role] = observed;
                    }
                }
                else if (vessel.protoVessel != null)
                {
                    foreach (var part in vessel.protoVessel.protoPartSnapshots)
                    {
                        if (!assets.TryGetValue(part.persistentId, out var asset))
                            continue;
                        reading = reading ?? ReadVessel(vessel);
                        var observed = new ScenarioPart {
                            Vessel = reading,
                            Crew = part.protoCrewNames.ToArray(),
                            Core = ReadsCore(asset) && part.modules
                                .SelectMany(module => module.moduleValues.GetNodes("ScienceData"))
                                .Any(data => IsCore(data.GetValue("subjectID")))
                        };
                        foreach (var resource in part.resources)
                            RecordResource(observed, resource.resourceName, resource.amount);
                        frame.Parts[asset.Role] = observed;
                    }
                }
            }
            return frame;
        }

        private static ScenarioVessel ReadVessel(Vessel vessel)
        {
            return new ScenarioVessel {
                Id = vessel.id,
                Body = vessel.mainBody.flightGlobalsIndex,
                Landed = vessel.Landed,
                Splashed = vessel.Splashed,
                Orbiting = vessel.situation == Vessel.Situations.ORBITING,
                Loaded = vessel.loaded,
                Altitude = vessel.altitude,
                Periapsis = vessel.orbit?.PeA ?? double.NaN,
                Atmosphere = vessel.mainBody.atmosphereDepth,
                Radius = vessel.mainBody.Radius,
                Latitude = vessel.latitude,
                Longitude = vessel.longitude,
                SurfaceSpeed = vessel.srfSpeed,
                Position = vessel.loaded ? vessel.GetWorldPos3D() : Vector3d.zero
            };
        }

        private static bool ReadsCore(ScenarioAsset asset) => asset.Role == "corer" || asset.Role == "orbiter";

        private static bool IsCore(string subject) =>
            subject?.StartsWith("famPolarCore@MunSrfLanded", StringComparison.Ordinal) == true;

        private static void RecordResource(ScenarioPart part, string name, double amount)
        {
            switch (name)
            {
                case "LiquidFuel":
                    part.LiquidFuel += amount;
                    part.Vessel.LiquidFuel += amount;
                    break;
                case "Oxidizer":
                    part.Oxidizer += amount;
                    part.Vessel.Oxidizer += amount;
                    break;
                case "ElectricCharge":
                    part.ElectricCharge += amount;
                    break;
            }
        }
    }
}
