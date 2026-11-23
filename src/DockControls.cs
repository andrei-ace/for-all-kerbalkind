using System.Collections;
using UnityEngine;

namespace FAMSeasons
{
    public sealed class FAMDockControls : PartModule
    {
        private ModuleDockingNode roof;
        private ModuleDockingNode airlockPort;
        private ModuleDecouple separator;

        public override void OnStartFinished(StartState state)
        {
            base.OnStartFinished(state);
            if (!HighLogic.LoadedSceneIsFlight) return;
            roof = part.FindAttachNode("top")?.attachedPart?.FindModuleImplementing<ModuleDockingNode>();
            var ring = roof?.part.FindAttachNode("top")?.attachedPart;
            var collar = ring?.FindAttachNode("top")?.attachedPart;
            if (ring?.partInfo.name != "Separator.1" ||
                collar?.FindAttachNode("bottom")?.attachedPart?.partInfo.name != "famJamestownAirlock") return;
            airlockPort = collar.FindModuleImplementing<ModuleDockingNode>();
            separator = ring.FindModuleImplementing<ModuleDecouple>();
            if (airlockPort != null && separator != null)
                GameEvents.onPartDeCouple.Add(BeforeRoofSeparation);
        }

        public override void OnUpdate()
        {
            Events[nameof(ReleaseRoofAirlock)].guiActive = CanRelease();
        }

        private bool CanRelease() =>
            separator != null && !separator.isDecoupled && !separator.part.ShieldedFromAirstream &&
            separator.Events["Decouple"].active;

        [KSPEvent(guiName = "Release roof airlock")]
        public void ReleaseRoofAirlock()
        {
            if (CanRelease()) separator.Events["Decouple"].Invoke();
        }

        private void BeforeRoofSeparation(Part departing)
        {
            if (separator == null || (departing != separator.part && departing != airlockPort.part)) return;
            var ring = separator;
            separator = null;
            GameEvents.onPartDeCouple.Remove(BeforeRoofSeparation);
            // A separator releases both ports directly into Ready, only 10 cm apart.
            // Give them the same distance interlock stock uses when undocking a mated pair.
            Disengage(roof, airlockPort);
            Disengage(airlockPort, roof);
            StartCoroutine(ClearRing(ring));
        }

        private static void Disengage(ModuleDockingNode port, ModuleDockingNode mate)
        {
            port.otherNode = mate;
            port.dockedPartUId = mate.part.flightID;
            port.dockingNodeModuleIndex = mate.part.Modules.IndexOf(mate);
            port.fsm.RunEvent(port.on_undock);
        }

        private IEnumerator ClearRing(ModuleDecouple ring)
        {
            yield return new WaitForFixedUpdate();
            // A player can also select Decouple Node on either adjacent Clamp-O-Tron.
            if (ring != null && !ring.isDecoupled) ring.Decouple();
            yield return new WaitForFixedUpdate();
            if (ring == null || ring.part.vessel == null || ring.part.vessel.parts.Count != 1 ||
                roof == null || airlockPort == null || roof.vessel == airlockPort.vessel) yield break;

            // The stock omni separator pushes axially on both stacks; its own axial
            // impulses cancel. The stow mount kicks the spent ring clear of the docking lane.
            var direction = roof.nodeTransform.right * 0.65f + roof.nodeTransform.forward * 0.12f;
            Vector3d force = direction * (ring.part.mass / Time.fixedDeltaTime);
            ring.part.AddForce(force);
            roof.part.AddForce(-force);
        }

        private void OnDestroy() => GameEvents.onPartDeCouple.Remove(BeforeRoofSeparation);

        // The hull shrouds cover the servo barrels. Open each real part's stock controls from the hull.
        [KSPEvent(guiActive = true, guiName = "Front docking servo", groupName = "docks", groupDisplayName = "Dock rotation")]
        public void Front() => OpenServo("airlock");

        [KSPEvent(guiActive = true, guiName = "Rear docking servo", groupName = "docks", groupDisplayName = "Dock rotation")]
        public void Rear() => OpenServo("rear");

        [KSPEvent(guiActive = true, guiName = "West docking servo", groupName = "docks", groupDisplayName = "Dock rotation")]
        public void West() => OpenServo("west");

        [KSPEvent(guiActive = true, guiName = "East docking servo", groupName = "docks", groupDisplayName = "Dock rotation")]
        public void East() => OpenServo("east");

        private void OpenServo(string socket)
        {
            var servo = part.FindAttachNode(socket)?.attachedPart;
            if (servo?.FindModuleImplementing<Expansions.Serenity.ModuleRoboticRotationServo>() != null)
                UIPartActionController.Instance.SpawnPartActionWindow(servo);
        }
    }
}
