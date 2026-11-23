using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;

namespace FAMSeasons
{
    internal sealed class ScenarioVessel
    {
        public Guid Id;
        public int Body;
        public bool Landed, Splashed, Orbiting, Loaded;
        public double Altitude, Periapsis, Atmosphere, Radius, Latitude, Longitude, SurfaceSpeed;
        public double LiquidFuel, Oxidizer;
        public Vector3d Position;
    }

    internal sealed class ScenarioPart
    {
        public ScenarioVessel Vessel;
        public string[] Crew = Array.Empty<string>();
        public double LiquidFuel, Oxidizer, ElectricCharge;
        public bool Upright, Core;
    }

    internal sealed class ScenarioAsset
    {
        public string Role;
        public uint PartId;
        public string[] Crew;
    }

    internal sealed class ScenarioStep
    {
        public readonly string VesselRole, Title, Hint;
        public readonly Func<ScenarioFrame, bool> Check;

        public ScenarioStep(string vesselRole, string title, string hint, Func<ScenarioFrame, bool> check)
        {
            VesselRole = vesselRole;
            Title = title;
            Hint = hint;
            Check = check;
        }
    }

    internal sealed class ScenarioFrame
    {
        public double UniversalTime;
        public readonly Dictionary<string, ScenarioPart> Parts = new Dictionary<string, ScenarioPart>();

        public ScenarioPart this[string role]
        {
            get
            {
                Parts.TryGetValue(role, out var part);
                return part;
            }
        }
    }

    internal sealed class ScenarioPlan
    {
        private const int Kerbin = 1, Mun = 2;
        private const double SiteRange = 1200, ParkingRange = 200;

        public readonly string Mission;
        public readonly string Focus, Milestone;
        public readonly bool FromPad;
        public readonly ScenarioAsset[] Assets;
        public readonly List<ScenarioStep> Steps = new List<ScenarioStep>();
        public int Completed { get; private set; }
        public bool Finished => Completed == Steps.Count;
        public ScenarioStep CurrentStep => Finished ? null : Steps[Completed];
        public bool ReturnsToKerbin { get; private set; }
        private readonly double latitude, longitude;
        private double steadySince;

        public ScenarioPlan(ConfigNode node)
        {
            Mission = node.GetValue("mission");
            Focus = node.GetValue("focus") ?? "";
            Milestone = node.GetValue("milestone") ?? "";
            FromPad = node.GetValue("fromPad") == "True";
            latitude = double.Parse(node.GetValue("siteLatitude"), CultureInfo.InvariantCulture);
            longitude = double.Parse(node.GetValue("siteLongitude"), CultureInfo.InvariantCulture);
            Assets = node.GetNodes("ASSET").Select(asset => new ScenarioAsset {
                Role = asset.GetValue("role"),
                PartId = uint.Parse(asset.GetValue("partId"), CultureInfo.InvariantCulture),
                Crew = asset.GetValues("crew")
            }).ToArray();
            if (Assets.Select(asset => asset.PartId).Distinct().Count() != Assets.Length ||
                Assets.Select(asset => asset.Role).Distinct().Count() != Assets.Length)
                throw new InvalidDataException("Duplicate spacecraft in scenario " + Mission);
            switch (Mission)
            {
                case "red-mun":
                case "apollo-11":
                case "into-the-crater":
                    AddLunarFlight(Mission == "into-the-crater");
                    break;
                case "reentry":
                    AddReentry(Crew("orbiter"), false);
                    break;
                case "jamestown":
                    AddJamestown();
                    break;
                case "first-crew":
                    AddFirstCrew();
                    break;
                case "apollo-24":
                    AddRescue();
                    break;
                default:
                    throw new InvalidDataException("Unknown scenario mission " + Mission);
            }
            if (int.TryParse(node.GetValue("completed"), out var completed))
                Completed = Math.Max(0, Math.Min(completed, Steps.Count));
            if (!double.TryParse(node.GetValue("steadySince"), NumberStyles.Float, CultureInfo.InvariantCulture,
                out steadySince))
                steadySince = -1;
        }

        public void Save(ConfigNode node)
        {
            node.SetValue("mission", Mission, true);
            node.SetValue("focus", Focus, true);
            node.SetValue("milestone", Milestone, true);
            node.SetValue("fromPad", FromPad ? "True" : "False", true);
            node.SetValue("siteLatitude", latitude.ToString("R", CultureInfo.InvariantCulture), true);
            node.SetValue("siteLongitude", longitude.ToString("R", CultureInfo.InvariantCulture), true);
            node.SetValue("completed", Completed, true);
            node.SetValue("steadySince", steadySince.ToString("R", CultureInfo.InvariantCulture), true);
            node.RemoveNodes("ASSET");
            foreach (var asset in Assets)
            {
                var saved = node.AddNode("ASSET");
                saved.AddValue("role", asset.Role);
                saved.AddValue("partId", asset.PartId);
                foreach (var name in asset.Crew)
                    saved.AddValue("crew", name);
            }
        }

        public void Advance(ScenarioFrame frame)
        {
            while (!Finished && Steps[Completed].Check(frame))
                Completed++;
        }

        public string Status(ScenarioFrame frame)
        {
            if (frame == null || Finished)
                return "";
            var habitat = frame["habitat"];
            var ferry = frame["ferry"];
            if (Mission == "jamestown" && habitat?.Vessel.Body == Mun)
            {
                if (Completed == 0)
                    return $"Survey site range {Distance(habitat.Vessel, latitude, longitude):N0} m";
                double held = steadySince < 0 ? 0 : frame.UniversalTime - steadySince;
                return $"Steady {held:0}/30 s   Charge {habitat.ElectricCharge:0}/100";
            }
            if (Mission == "first-crew" && IsOnGround(ferry, Mun) && IsOnGround(habitat, Mun))
                return $"Range {Distance(ferry.Vessel, habitat.Vessel.Latitude, habitat.Vessel.Longitude):0} m   " +
                    $"LF {ferry.Vessel.LiquidFuel:0.0}/180   Ox {ferry.Vessel.Oxidizer:0.0}/220";
            if (Mission == "apollo-24" && Completed == 2 && frame["service"] is ScenarioPart service)
                return $"Osprey tanks   LF {service.LiquidFuel:0.0}/18   Ox {service.Oxidizer:0.0}/22";
            return "";
        }

        private string[] Crew(string role) => Assets.Single(asset => asset.Role == role).Crew;

        private void Add(string vesselRole, string title, string hint, Func<ScenarioFrame, bool> check)
        {
            Steps.Add(new ScenarioStep(vesselRole, title, hint, check));
        }

        private void AddLunarFlight(bool survey)
        {
            var landerCrew = Crew("lander");
            var orbitCrew = Crew("orbiter");
            var returnCrew = landerCrew.Concat(orbitCrew).ToArray();
            if (FromPad)
            {
                Add("orbiter", "Launch and climb to orbit",
                    Mission == "red-mun" ? "Raise throttle and fire Block A at stage 7. Use stages 6 and 5 for ascent." :
                        "Raise throttle and fire the S-IC at stage 6. Use stages 5 and 4 to establish Kerbin orbit.",
                    f => HasCrew(f["orbiter"], returnCrew) &&
                        (InMunOrbit(f["orbiter"]) || (f["orbiter"].Vessel.Body == Kerbin &&
                            f["orbiter"].Vessel.Orbiting &&
                            f["orbiter"].Vessel.Periapsis >= f["orbiter"].Vessel.Atmosphere)));
                Add("orbiter", "Bring the lunar train to the Mun",
                    "Insert into Mun orbit. At zero throttle, stage to release both spacecraft and arm their engines. " +
                    "Dock to board the lander, then undock.",
                    f => InMunOrbit(f["orbiter"]) && InMunOrbit(f["lander"]) &&
                        !Joined(f["orbiter"], f["lander"]) && HasCrew(f["orbiter"], orbitCrew) &&
                        HasCrew(f["lander"], landerCrew));
            }
            if (survey)
                Add("lander", "Drill a polar core",
                    "Right-click the Shackleton Polar Core Sampler on the side of Falcon's landing deck. " +
                    "Choose Drill a regolith core, then Keep Experiment.",
                    f => IsOnGround(f["lander"], Mun) && AtSurveySite(f["lander"]) && f["corer"]?.Core == true);
            else
                Add("lander", "Land the assigned crew on the Mun", "Fly the lander down and leave the command pilot in Mun orbit.",
                    f => IsOnGround(f["lander"], Mun) && HasCrew(f["lander"], landerCrew) &&
                        InMunOrbit(f["orbiter"]) && !Joined(f["lander"], f["orbiter"]) &&
                        HasCrew(f["orbiter"], orbitCrew));
            Add("lander", "Return the ascent cabin to Mun orbit",
                survey ? "Send one Kerbal on EVA. Right-click the sampler, choose Take the core, and board Falcon. " +
                    "At zero throttle, stage away the landing deck. Throttle up once clear and establish Mun orbit." :
                    "At zero throttle, stage away the landing deck. Check the orange delta-v total below staging, " +
                    "then throttle up once clear and establish a low Mun orbit.",
                f => InMunOrbit(f["lander"]) && HasCrew(f["lander"], landerCrew) && !Joined(f["lander"], f["descent"]));
            Add("lander", "Dock with the command ship",
                survey ? "Rendezvous with Endeavour. Target its nose port and dock the two cabins in Mun orbit." :
                    "Target the command ship's nose port and dock the two cabins in Mun orbit.",
                f => InMunOrbit(f["lander"]) && Joined(f["lander"], f["orbiter"]));
            Add("orbiter", survey ? "Move the crew and core into Endeavour" : "Reunite the crew",
                survey ? "Move both Kerbals into Endeavour. On EVA, use Store samples on its command module." :
                    "Transfer the landing crew into the return cabin while still docked.",
                f => Joined(f["lander"], f["orbiter"]) && CabinReady(f["orbiter"], returnCrew, survey));
            Add("orbiter", "Undock the lander", "Leave the lander in Mun orbit and use the service engine for the Kerbin return.",
                f => InMunOrbit(f["orbiter"]) && !Joined(f["orbiter"], f["lander"]) &&
                    CabinReady(f["orbiter"], returnCrew, survey));
            AddReentry(returnCrew, survey);
        }

        private void AddReentry(string[] crew, bool survey)
        {
            ReturnsToKerbin = true;
            Add("orbiter", "Set up atmospheric entry", "Aim for a 36 km Kerbin periapsis. The approach registers in Kerbin's SOI.",
                f => OutsideKerbinAtmosphere(f["orbiter"]) && f["orbiter"].Vessel.Periapsis >= 0 &&
                    f["orbiter"].Vessel.Periapsis < f["orbiter"].Vessel.Atmosphere);
            Add("orbiter", "Separate the service section", "At zero throttle above 70 km, release the ring below the cabin. Set Surface retrograde.",
                f => OutsideKerbinAtmosphere(f["orbiter"]) && !Joined(f["orbiter"], f["service"]) &&
                    !Joined(f["orbiter"], f["lander"]) && CabinReady(f["orbiter"], crew, survey));
            Add("orbiter", survey ? "Touch down with the crew and core" : "Bring the crew safely home",
                "Hold the heat shield into the airflow. Stage the chutes when safe, then land or splash down on Kerbin.",
                f => f["orbiter"]?.Vessel.Body == Kerbin && (f["orbiter"].Vessel.Landed || f["orbiter"].Vessel.Splashed) &&
                    CabinReady(f["orbiter"], crew, survey) && !Joined(f["orbiter"], f["service"]));
        }

        private void AddJamestown()
        {
            Add("habitat", "Land at the Shackleton site",
                "Fly the uncrewed Jamestown habitat down from Mun orbit using its four-engine landing platform. " +
                "Set all four pads on level ground within 1.2 km of 77° S, 12° E. Keep the side stairs attached " +
                "and leave space at both end ports.",
                f => IsOnGround(f["habitat"], Mun) && AtSurveySite(f["habitat"]) && f["habitat"].Crew.Length == 0);
            Add("habitat", "Hold the habitat upright and powered",
                "Remain within 15° of vertical at under 0.5 m/s, with at least 100 ElectricCharge, for 30 seconds.",
                f =>
                {
                    var basePart = f["habitat"];
                    if (!IsOnGround(basePart, Mun) || !AtSurveySite(basePart) || !basePart.Upright ||
                        basePart.Crew.Length != 0 || basePart.ElectricCharge < 100 || basePart.Vessel.SurfaceSpeed >= 0.5)
                    {
                        steadySince = -1;
                        return false;
                    }
                    if (steadySince < 0 || steadySince > f.UniversalTime)
                        steadySince = f.UniversalTime;
                    return f.UniversalTime - steadySince >= 30;
                });
        }

        private void AddFirstCrew()
        {
            var crew = Crew("ferry");
            Add("ferry", "Park the LSAM with rescue reserves",
                "Set the landed Jamestown habitat as target in map view. Land the LSAM within 200 m " +
                "with both Kerbals aboard and at least 180 LiquidFuel and 220 Oxidizer.",
                f => FerryParked(f) && HasCrew(f["ferry"], crew));
            if (string.IsNullOrEmpty(Milestone))
                Add("ferry", "Board Jamestown on EVA", "Leave the ferry parked. Lower and lock the frame, deploy the airlock stairs, board the airlock, then transfer into the habitat.",
                    f => FerryParked(f) && f["habitat"].Upright && f["habitat"].Crew.Any(crew.Contains));
            else
                Add("ferry", "Board Jamestown on EVA",
                    $"Lower and lock the frame, turn on Lights and deploy the stairs. Send {crew[1]} through the airlock into the habitat. Leave {crew[0]} at the LSAM controls.",
                    f => FerryParked(f) && f["habitat"].Upright && f["habitat"].Crew.Contains(crew[1]) &&
                        f["ferry"].Crew.Contains(crew[0]));
        }

        private void AddRescue()
        {
            var survivor = Crew("orbiter");
            Add("ferry", "Intercept Osprey in Mun orbit",
                "Take off from Jamestown in the same LSAM. In map view, target Apollo 24 Osprey, " +
                "match its orbital plane and close within 150 m.",
                f => InMunOrbit(f["ferry"]) && InMunOrbit(f["orbiter"]) && CloseInOrbit(f["ferry"], f["orbiter"]));
            Add("ferry", "Dock the LSAM with Osprey", "Match speeds, target the nose port and dock.",
                f => InMunOrbit(f["ferry"]) && Joined(f["ferry"], f["orbiter"]));
            Add("ferry", "Refuel Osprey and take the survivor",
                $"Move {survivor[0]} into the empty LSAM seat. Transfer at least 18 LiquidFuel and 22 Oxidizer " +
                "to Osprey's service module, then undock.",
                f => InMunOrbit(f["orbiter"]) && Joined(f["service"], f["orbiter"]) &&
                    f["service"].LiquidFuel >= 18 && f["service"].Oxidizer >= 22 &&
                    InMunOrbit(f["ferry"]) && !Joined(f["orbiter"], f["ferry"]) && HasCrew(f["ferry"], survivor));
            Add("ferry", "Land the survivor by Jamestown", "Return the LSAM to the Mun and park within 200 m of the habitat.",
                f => BesideHabitat(f) && HasCrew(f["ferry"], survivor));
            Add("ferry", "Bring the survivor into Jamestown", $"Send {survivor[0]} on EVA from the LSAM and board Jamestown.",
                f => BesideHabitat(f) && f["habitat"].Upright && HasCrew(f["habitat"], survivor));
        }

        private bool AtSurveySite(ScenarioPart part) => Distance(part.Vessel, latitude, longitude) <= SiteRange;

        private static bool IsOnGround(ScenarioPart part, int body) =>
            part?.Vessel.Body == body && part.Vessel.Landed;

        private static bool InMunOrbit(ScenarioPart part) =>
            part?.Vessel.Body == Mun && part.Vessel.Orbiting && part.Vessel.Periapsis > 0;

        private static bool OutsideKerbinAtmosphere(ScenarioPart part) =>
            part?.Vessel.Body == Kerbin && part.Vessel.Altitude >= part.Vessel.Atmosphere;

        private static bool HasCrew(ScenarioPart part, string[] names) =>
            part != null && names.All(part.Crew.Contains);

        private static bool CabinReady(ScenarioPart part, string[] crew, bool core) =>
            HasCrew(part, crew) && (!core || part.Core);

        private static bool Joined(ScenarioPart first, ScenarioPart second) =>
            first != null && second != null && first.Vessel == second.Vessel;

        private static bool CloseInOrbit(ScenarioPart ferry, ScenarioPart target) =>
            Joined(ferry, target) || (ferry.Vessel.Loaded && target.Vessel.Loaded &&
                Vector3d.Distance(ferry.Vessel.Position, target.Vessel.Position) <= 150);

        private static bool BesideHabitat(ScenarioFrame f) =>
            IsOnGround(f["ferry"], Mun) && IsOnGround(f["habitat"], Mun) && !Joined(f["ferry"], f["habitat"]) &&
            Distance(f["ferry"].Vessel, f["habitat"].Vessel.Latitude, f["habitat"].Vessel.Longitude) <= ParkingRange;

        private static bool FerryParked(ScenarioFrame f) =>
            BesideHabitat(f) && Joined(f["ferry"], f["drive"]) &&
            f["ferry"].Vessel.LiquidFuel >= 180 && f["ferry"].Vessel.Oxidizer >= 220;

        private static double Distance(ScenarioVessel vessel, double latitude, double longitude)
        {
            const double radians = Math.PI / 180;
            double a = vessel.Latitude * radians, b = latitude * radians;
            double angle = Math.Sin(a) * Math.Sin(b) + Math.Cos(a) * Math.Cos(b) *
                Math.Cos((vessel.Longitude - longitude) * radians);
            return vessel.Radius * Math.Acos(Math.Max(-1, Math.Min(1, angle)));
        }
    }
}
