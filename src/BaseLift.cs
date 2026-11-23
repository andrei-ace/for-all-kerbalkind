using Expansions.Serenity;
using UnityEngine;

namespace FAMSeasons
{
    public sealed class FAMBaseLift : PartModule
    {
        [KSPField]
        public float dockingStroke = 0.75f;

        ModuleRoboticServoPiston[] lifting;
        float nextTrim, finishTrim;

        [KSPEvent(guiActive = true, guiName = "Lower to boarding height")]
        public void LowerToBoard() { SetStroke(0f); }

        [KSPEvent(guiActive = true, guiName = "Raise to expansion height")]
        public void RaiseToDock() { SetStroke(dockingStroke); }

        [KSPAction("Extend / retract landing cylinders", KSPActionGroup.Gear)]
        public void SetLandingGear(KSPActionParam action)
        {
            bool extend = action.type == KSPActionType.Activate;
            if (action.type == KSPActionType.Toggle)
                extend = (Legs()[0]?.targetExtension ?? 0f) < dockingStroke * 0.5f;
            SetStroke(extend ? dockingStroke : 0f);
        }

        [KSPEvent(guiActive = true, guiName = "Lock landing cylinders")]
        public void LockFeet()
        {
            lifting = null;
            foreach (var leg in Legs())
                leg?.EngageServoLock();
        }

        ModuleRoboticServoPiston[] Legs()
        {
            var legs = new ModuleRoboticServoPiston[4];
            for (int i = 0; i < legs.Length; i++)
                legs[i] = part.FindAttachNode("jack" + (i + 1))?.attachedPart?
                    .FindModuleImplementing<ModuleRoboticServoPiston>();
            return legs;
        }

        void SetStroke(float metres)
        {
            var legs = Legs();
            foreach (var leg in legs)
            {
                if (leg == null || !leg.servoMotorIsEngaged || metres < leg.softMinMaxExtension.x ||
                    metres > leg.softMinMaxExtension.y + 0.001f)
                {
                    ScreenMessages.PostScreenMessage("Jamestown needs four powered cylinders with the requested travel.", 4f);
                    return;
                }
            }

            lifting = null;
            float travelTime = 0f;
            foreach (var leg in legs)
            {
                leg.DisengageServoLock();
                travelTime = Mathf.Max(travelTime, Mathf.Abs(metres - leg.currentExtension) / Mathf.Max(0.01f, leg.traverseVelocity));
                SetTarget(leg, metres);
            }
            if (metres > 0)
            {
                lifting = legs;
                nextTrim = Time.fixedTime + travelTime + 0.8f;
                finishTrim = nextTrim + 12f;
            }
        }

        static void SetTarget(ModuleRoboticServoPiston leg, float metres)
        {
            var field = leg.Fields[nameof(leg.targetExtension)];
            float previous = leg.targetExtension;
            field.SetValue(metres, leg);
            field.uiControlFlight.onFieldChanged?.Invoke(field, previous);
        }

        public void FixedUpdate()
        {
            if (lifting == null || Time.fixedTime < nextTrim) return;
            nextTrim = Time.fixedTime + 0.5f;
            bool settled = true;
            foreach (var leg in lifting)
            {
                if (leg == null || leg.vessel != vessel || leg.servoIsLocked || !leg.servoMotorIsEngaged)
                {
                    lifting = null;
                    return;
                }
                // A loaded stock piston can settle short of its target. Use the remaining
                // 50 mm of travel independently at each foot, including on the heavier Kerbin pad.
                float error = dockingStroke - leg.currentExtension;
                if (Mathf.Abs(error) <= 0.004f) continue;
                float target = Mathf.Clamp(leg.targetExtension + 0.65f * error, dockingStroke - 0.05f,
                                          Mathf.Min(leg.softMinMaxExtension.y, dockingStroke + 0.05f));
                if (Mathf.Abs(target - leg.targetExtension) > 0.0005f) SetTarget(leg, target);
                settled = false;
            }
            if (settled || Time.fixedTime >= finishTrim) lifting = null;
        }
    }
}
