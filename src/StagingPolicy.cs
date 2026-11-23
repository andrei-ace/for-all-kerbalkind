using System;
using System.Collections;

namespace FAMSeasons
{
    // Older craft and flight saves can restore the previous PartModule staging flags.
    // Keep automatic shrouds and manual engines out of the stack as KSP loads those parts.
    public sealed class FAMStagePolicy : PartModule
    {
        [KSPField]
        public bool manualIgnition;

        [KSPField]
        public bool stageServiceEngine;

        [KSPField]
        public bool jettisonWithLowerStage;

        private bool needsRefresh;
        private ModuleJettison attachedShroud;

        internal static bool DisableStageAction(PartModule module, bool manualIgnition)
        {
            if (!(module is ModuleJettison) && !(manualIgnition && module is ModuleEngines))
                return false;

            bool changed = module.stagingEnabled || module.stagingToggleEnabledEditor ||
                module.stagingToggleEnabledFlight;
            module.stagingEnabled = false;
            module.stagingToggleEnabledEditor = false;
            module.stagingToggleEnabledFlight = false;
            return changed;
        }

        public override void OnInitialize()
        {
            ApplyPolicy();
        }

        public override void OnStart(StartState state)
        {
            ApplyPolicy();
        }

        public override void OnStartFinished(StartState state)
        {
            if (needsRefresh)
            {
                needsRefresh = false;
                part.UpdateStageability(false, true);
            }
            if (stageServiceEngine)
                StartCoroutine(RestoreServiceStageAfterLoad());
            if (jettisonWithLowerStage && HighLogic.LoadedSceneIsFlight)
                attachedShroud = part.FindModuleImplementing<ModuleJettison>();
        }

        private void FixedUpdate()
        {
            if (attachedShroud == null || !FlightGlobals.ready || part.packed)
                return;
            if (!attachedShroud.isJettisoned && part.FindAttachNode("bottom")?.attachedPart != null)
                return;
            if (!attachedShroud.isJettisoned)
                attachedShroud.Jettison();
            attachedShroud = null;
        }

        private IEnumerator RestoreServiceStageAfterLoad()
        {
            // The stock stage list can still normalize legacy part indexes during OnStartFinished.
            while (HighLogic.LoadedSceneIsFlight && !FlightGlobals.ready)
                yield return null;
            yield return null;
            if (RestoreServiceStage())
            {
                part.UpdateStageability(false, true);
                part.vessel?.VesselDeltaV?.SetCalcsDirty(true, true);
            }
        }

        private bool RestoreServiceStage()
        {
            var separator = part.FindAttachNode("top")?.attachedPart;
            if (separator?.partInfo.name == "famLOKServiceBus" || separator?.partInfo.name == "famApolloSMBus")
                separator = separator.FindAttachNode("top")?.attachedPart;
            var cabin = separator?.FindAttachNode("top")?.attachedPart;
            bool lok = part.partInfo.name.StartsWith("famLOKService", StringComparison.Ordinal);
            if (separator == null || cabin == null || separator.inverseStage < 0 ||
                separator.partInfo.name != (lok ? "famRing125" : "famRing250") ||
                cabin.partInfo.name != (lok ? "famLOK" : "famApolloCM"))
                return false;

            var engine = part.FindModuleImplementing<ModuleEngines>();
            if (engine == null)
                return false;

            var release = part.FindAttachNode("bottom")?.attachedPart;
            int releaseStage = release != null && release.FindModuleImplementing<ModuleDecouple>() != null
                ? release.inverseStage : -1;
            return RestoreServiceEngineStage(engine, separator.inverseStage, releaseStage, ref part.inverseStage);
        }

        internal static bool RestoreServiceEngineStage(ModuleEngines engine, int separatorStage, int releaseStage,
            ref int engineStage)
        {
            if (engine.stagingEnabled && engineStage > separatorStage)
                return false;

            // KSP's delta-v simulator needs an engine stage before the separator drops its fuel.
            engineStage = Math.Max(engineStage, Math.Max(separatorStage + 1, releaseStage));
            engine.stagingEnabled = true;
            return true;
        }

        private void ApplyPolicy()
        {
            if (part == null)
                return;
            foreach (PartModule module in part.Modules)
                needsRefresh |= DisableStageAction(module, manualIgnition);
        }
    }
}
