using System;
using System.Reflection;
using System.Runtime.CompilerServices;
using ContractConfigurator;
using ContractConfigurator.Parameters;
using Contracts;
using UnityEngine;

[assembly: AssemblyVersion("0.1.0.0")]
[assembly: KSPAssembly("FAMSeasons", 0, 1)]
[assembly: KSPAssemblyDependency("ContractConfigurator", 2, 11)]
[assembly: InternalsVisibleTo("StockSmoke")]

namespace FAMSeasons
{
    // Contract Configurator discovers public ParameterFactory subclasses by their *Factory name.
    public sealed class FAMHabitatFactory : ParameterFactory
    {
        private int minimumOccupants;
        private string occupant;

        public override bool Load(ConfigNode config)
        {
            bool valid = base.Load(config);
            valid &= ConfigNodeUtil.ParseValue<int>(config, "minimumOccupants", v => minimumOccupants = v, this, 0);
            valid &= ConfigNodeUtil.ParseValue<string>(config, "occupant", v => occupant = v, this, (string)null);
            return valid && minimumOccupants >= 0;
        }

        public override ContractParameter Generate(Contract contract)
        {
            return new HabitatCondition(title, minimumOccupants, occupant);
        }
    }

    public sealed class HabitatCondition : VesselParameter
    {
        private int minimumOccupants;
        private string occupant;
        private float nextCheck;
        private static readonly float MinimumUpDot = (float)Math.Cos(15 * Math.PI / 180);

        // The contract system uses this constructor when reloading a save.
        public HabitatCondition() : base(null) { }

        public HabitatCondition(string title, int minimumOccupants, string occupant) : base(title)
        {
            this.minimumOccupants = minimumOccupants;
            this.occupant = occupant;
        }

        protected override void OnParameterSave(ConfigNode node)
        {
            base.OnParameterSave(node);
            node.AddValue("minimumOccupants", minimumOccupants);
            if (!string.IsNullOrEmpty(occupant))
                node.AddValue("occupant", occupant);
        }

        protected override void OnParameterLoad(ConfigNode node)
        {
            base.OnParameterLoad(node);
            int.TryParse(node.GetValue("minimumOccupants"), out minimumOccupants);
            occupant = node.GetValue("occupant");
        }

        protected override void OnUpdate()
        {
            base.OnUpdate();
            if (HighLogic.LoadedSceneIsFlight && Time.unscaledTime >= nextCheck)
            {
                nextCheck = Time.unscaledTime + 0.4f;
                CheckVessel(FlightGlobals.ActiveVessel);
            }
        }

        protected override bool CanCheckVesselMeetsCondition(Vessel vessel)
        {
            return vessel != null && vessel.loaded && vessel.mainBody != null &&
                base.CanCheckVesselMeetsCondition(vessel);
        }

        protected override bool VesselMeetsCondition(Vessel vessel)
        {
            if (!vessel.Landed)
                return false;

            foreach (Part part in vessel.parts)
            {
                if (part.partInfo == null || part.partInfo.name != "famJamestown")
                    continue;
                if (!IsUpright(part, vessel.mainBody))
                    continue;
                if (part.protoModuleCrew.Count >= minimumOccupants &&
                    (string.IsNullOrEmpty(occupant) || part.protoModuleCrew.Exists(kerbal => kerbal.name == occupant)))
                    return true;
            }
            return false;
        }

        internal static bool IsUpright(Part part, CelestialBody body)
        {
            Vector3 radialUp = (part.transform.position - body.transform.position).normalized;
            return Vector3.Dot(part.transform.up, radialUp) >= MinimumUpDot;
        }
    }
}
