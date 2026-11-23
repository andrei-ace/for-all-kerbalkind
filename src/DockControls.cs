namespace FAMSeasons
{
    public sealed class FAMDockControls : PartModule
    {
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
