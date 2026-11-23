using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using FAMSeasons;

internal static class ScenarioSmoke
{
    private static void Need(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }

    private static double Value(ConfigNode node, string key) =>
        double.Parse(node.GetValue(key), CultureInfo.InvariantCulture);

    public static void Check(ConfigNode game)
    {
        var guide = game.GetNodes("SCENARIO").Single();
        Need(guide.GetValue("name") == typeof(FAMScenarioObjectives).Name &&
            guide.GetValue("scene") == ((int)GameScenes.FLIGHT).ToString(), "Invalid scenario module");
        var operations = FAMScenarioObjectives.LoadOperations(guide);
        if (operations.Length > 1)
        {
            Need(operations.Select(op => op.Mission).SequenceEqual(new [] {
                "into-the-crater", "jamestown", "first-crew", "apollo-24"
            }), "Wrong order of Jamestown operations");
            Need(operations.Skip(1).Select(op => op.Assets.Single(a => a.Role == "habitat").PartId).Distinct().Count() == 1 &&
                operations.Skip(2).Select(op => op.Assets.Single(a => a.Role == "ferry").PartId).Distinct().Count() == 1,
                "The campaign must keep the same habitat and ferry");
        }
        else
            Need(operations[0].FromPad, "A lunar landing scenario must begin on the pad");
        var parts = CaptureStart(game);
        foreach (var operation in operations)
        {
            Need(ReferenceEquals(FAMScenarioObjectives.CurrentOperation(operations), operation), "Wrong active operation");
            Need(operation.Steps.All(step => operation.Assets.Any(asset => asset.Role == step.VesselRole)),
                "Every checklist step needs a tracked spacecraft");
            var frame = new ScenarioFrame { UniversalTime = Value(game.GetNode("FLIGHTSTATE"), "UT") };
            foreach (var asset in operation.Assets)
            {
                var part = parts[asset.PartId];
                bool transferred = operation.Mission == "apollo-24" && (asset.Role == "ferry" || asset.Role == "habitat");
                if (!operation.FromPad && !transferred)
                    Need(asset.Crew.SequenceEqual(part.Crew), "Guide crew does not match flight roster");
                frame.Parts.Add(asset.Role, part);
            }
            CheckOperation(operation, frame);
            var saved = new ConfigNode("SCENARIO");
            FAMScenarioObjectives.SaveOperations(saved, operations);
            var loaded = FAMScenarioObjectives.LoadOperations(saved);
            Need(loaded.Length == operations.Length && loaded.Zip(operations, (next, prior) => next.Completed == prior.Completed &&
                next.Assets.Length == prior.Assets.Length).All(match => match), "Lost campaign progress on reload");
            Need(FAMScenarioObjectives.CurrentOperation(loaded).Mission ==
                FAMScenarioObjectives.CurrentOperation(operations).Mission, "Reload resumed the wrong chapter");
        }
    }

    private static void CheckOperation(ScenarioPlan plan, ScenarioFrame frame)
    {
        Need(plan.Completed == 0, "Scenario guide must start with no checkmarks");
        plan.Advance(frame);
        switch (plan.Mission)
        {
            case "red-mun":
            case "apollo-11":
            case "into-the-crater":
                LunarFlight(plan, frame);
                break;
            case "reentry":
                Expect(plan, 1);
                Reentry(plan, frame, false);
                break;
            case "jamestown":
                Jamestown(plan, frame);
                break;
            case "first-crew":
                FirstCrew(plan, frame);
                break;
            case "apollo-24":
                Rescue(plan, frame);
                break;
        }
        Need(plan.Finished, plan.Mission + " did not pass");
    }

    private static Dictionary<uint, ScenarioPart> CaptureStart(ConfigNode game)
    {
        var readings = new Dictionary<uint, ScenarioPart>();
        foreach (var start in game.GetNode("FLIGHTSTATE").GetNodes("VESSEL"))
        {
            var orbit = start.GetNode("ORBIT");
            int body = (int)Value(orbit, "REF");
            var vessel = new ScenarioVessel {
                Body = body,
                Radius = body == 1 ? 600000 : 200000,
                Atmosphere = body == 1 ? 70000 : 0,
                Altitude = Value(start, "alt"),
                Latitude = Value(start, "lat"),
                Longitude = Value(start, "lon"),
                Loaded = true,
                Landed = start.GetValue("sit") == "LANDED" || start.GetValue("sit") == "PRELAUNCH",
                Orbiting = start.GetValue("sit") == "ORBITING",
            };
            vessel.Periapsis = Value(orbit, "SMA") * (1 - Value(orbit, "ECC")) - vessel.Radius;
            foreach (var part in start.GetNodes("PART"))
            {
                var crew = part.GetValues("crew");
                var reading = new ScenarioPart { Vessel = vessel, Crew = crew, Upright = vessel.Landed };
                foreach (var tank in part.GetNodes("RESOURCE"))
                {
                    var amount = Value(tank, "amount");
                    switch (tank.GetValue("name"))
                    {
                        case "LiquidFuel": reading.LiquidFuel = amount; vessel.LiquidFuel += amount; break;
                        case "Oxidizer": reading.Oxidizer = amount; vessel.Oxidizer += amount; break;
                        case "ElectricCharge": reading.ElectricCharge = amount; break;
                    }
                }
                readings.Add(uint.Parse(part.GetValue("persistentId")), reading);
            }
        }
        return readings;
    }

    private static void Expect(ScenarioPlan plan, int count) =>
        Need(plan.Completed == count, $"{plan.Mission} expected {count} objectives, observed {plan.Completed}");

    private static void LunarFlight(ScenarioPlan plan, ScenarioFrame frame)
    {
        Expect(plan, 0);
        var lander = frame["lander"];
        var orbiter = frame["orbiter"];
        if (plan.FromPad)
            Launch(plan, frame);
        var independentLander = lander.Vessel;
        int prefix = plan.Completed;
        bool survey = plan.Mission == "into-the-crater";
        if (survey)
        {
            Need(plan.CurrentStep.VesselRole == "lander" && plan.CurrentStep.Hint.Contains("Drill a regolith core") &&
                plan.CurrentStep.Hint.Contains("Keep Experiment"), "Jamestown must tell players how to collect the core");
            frame["corer"].Core = true;
        }
        lander.Vessel.Landed = true;
        lander.Vessel.Orbiting = false;
        plan.Advance(frame);
        Expect(plan, prefix + 1);
        lander.Vessel.Landed = false;
        lander.Vessel.Orbiting = true;
        lander.Vessel.Periapsis = 30000;
        plan.Advance(frame);
        Expect(plan, prefix + 1);
        frame.Parts.Remove("descent");
        plan.Advance(frame);
        Expect(plan, prefix + 2);
        lander.Vessel = orbiter.Vessel;
        plan.Advance(frame);
        Expect(plan, prefix + 3);
        orbiter.Crew = orbiter.Crew.Concat(lander.Crew).ToArray();
        if (survey)
        {
            plan.Advance(frame);
            Expect(plan, prefix + 3);
            orbiter.Core = true;
        }
        plan.Advance(frame);
        Expect(plan, prefix + 4);
        lander.Vessel = independentLander;
        plan.Advance(frame);
        Expect(plan, prefix + 5);
        orbiter.Vessel.Body = 1;
        orbiter.Vessel.Atmosphere = 70000;
        orbiter.Vessel.Altitude = 150000;
        orbiter.Vessel.Periapsis = 36000;
        plan.Advance(frame);
        Expect(plan, prefix + 6);
        Reentry(plan, frame, survey);
    }

    private static void Launch(ScenarioPlan plan, ScenarioFrame frame)
    {
        var orbiter = frame["orbiter"];
        var lander = frame["lander"];
        var outbound = plan.Assets.Single(a => a.Role == "lander").Crew;
        var pilot = plan.Assets.Single(a => a.Role == "orbiter").Crew;
        Need(orbiter.Vessel.Body == 1 && orbiter.Vessel.Landed && orbiter.Vessel == lander.Vessel &&
            orbiter.Crew.SequenceEqual(pilot.Concat(outbound)) && lander.Crew.Length == 0,
            "Pad start needs the complete stack and crew in the command cabin");
        orbiter.Vessel.Landed = false;
        orbiter.Vessel.Orbiting = true;
        orbiter.Vessel.Periapsis = 80000;
        plan.Advance(frame);
        Expect(plan, 1);
        orbiter.Vessel.Body = 2;
        orbiter.Vessel.Periapsis = 35000;
        plan.Advance(frame);
        Expect(plan, 1);
        lander.Vessel = new ScenarioVessel { Body = 2, Orbiting = true, Periapsis = 35000 };
        frame["descent"].Vessel = lander.Vessel;
        lander.Crew = outbound;
        orbiter.Crew = pilot;
        plan.Advance(frame);
        Expect(plan, 2);
    }

    private static void Reentry(ScenarioPlan plan, ScenarioFrame frame, bool sample)
    {
        int approach = plan.Completed;
        var orbiter = frame["orbiter"];
        orbiter.Vessel.Altitude = 65000;
        frame.Parts.Remove("service");
        plan.Advance(frame);
        Expect(plan, approach);
        orbiter.Vessel.Altitude = 150000;
        plan.Advance(frame);
        Expect(plan, approach + 1);
        orbiter.Core = false;
        orbiter.Vessel.Landed = true;
        orbiter.Vessel.Altitude = 100;
        if (sample)
        {
            plan.Advance(frame);
            Expect(plan, approach + 1);
            orbiter.Core = true;
        }
        plan.Advance(frame);
        Expect(plan, approach + 2);
    }

    private static void Jamestown(ScenarioPlan plan, ScenarioFrame frame)
    {
        var habitat = frame["habitat"];
        habitat.Vessel.Landed = true;
        habitat.Vessel.Orbiting = false;
        plan.Advance(frame);
        Expect(plan, 0);
        habitat.Vessel.Latitude = -77;
        habitat.Vessel.Longitude = 12;
        habitat.Upright = true;
        plan.Advance(frame);
        Expect(plan, 1);
        frame.UniversalTime += 20;
        habitat.ElectricCharge = 0;
        plan.Advance(frame);
        habitat.ElectricCharge = 100;
        frame.UniversalTime += 20;
        plan.Advance(frame);
        Expect(plan, 1);
        var saved = new ConfigNode("SCENARIO");
        plan.Save(saved);
        var restored = new ScenarioPlan(saved);
        frame.UniversalTime += 30;
        restored.Advance(frame);
        Need(restored.Finished, "Jamestown hold did not survive a quickload");
        plan.Advance(frame);
    }

    private static void FirstCrew(ScenarioPlan plan, ScenarioFrame frame)
    {
        Expect(plan, 0);
        var ferry = frame["ferry"];
        var habitat = frame["habitat"];
        Need(habitat.Vessel.Landed && habitat.Upright, "Jamestown deployment did not carry forward");
        LandNearHabitat(ferry, habitat);
        ferry.Vessel.LiquidFuel = 179;
        ferry.Vessel.Oxidizer = 220;
        plan.Advance(frame);
        Expect(plan, 0);
        ferry.Vessel.LiquidFuel = 180;
        plan.Advance(frame);
        Expect(plan, 1);
        habitat.Crew = new [] { ferry.Crew[1] };
        ferry.Crew = new [] { ferry.Crew[0] };
        plan.Advance(frame);
    }

    private static void Rescue(ScenarioPlan plan, ScenarioFrame frame)
    {
        Expect(plan, 0);
        var ferry = frame["ferry"];
        var osprey = frame["orbiter"];
        var service = frame["service"];
        Need(ferry.Vessel.Landed && ferry.Crew.Length == 1 && frame["habitat"].Crew.Length == 1,
            "The parked LSAM and resident crew must carry into the rescue");
        var freeFerry = ferry.Vessel;
        freeFerry.Landed = false;
        freeFerry.Orbiting = true;
        freeFerry.Periapsis = 25000;
        freeFerry.Position = new Vector3d(151, 0, 0);
        plan.Advance(frame);
        Expect(plan, 0);
        freeFerry.Position = new Vector3d(150, 0, 0);
        plan.Advance(frame);
        Expect(plan, 1);
        ferry.Vessel = osprey.Vessel;
        plan.Advance(frame);
        Expect(plan, 2);
        var survivor = osprey.Crew.Single();
        ferry.Crew = ferry.Crew.Concat(osprey.Crew).ToArray();
        ferry.Vessel = freeFerry;
        service.LiquidFuel = 18;
        service.Oxidizer = 21.9;
        plan.Advance(frame);
        Expect(plan, 2);
        service.Oxidizer = 22;
        plan.Advance(frame);
        Expect(plan, 3);
        LandNearHabitat(ferry, frame["habitat"]);
        plan.Advance(frame);
        Expect(plan, 4);
        frame["habitat"].Crew = new [] { survivor };
        plan.Advance(frame);
    }

    private static void LandNearHabitat(ScenarioPart ferry, ScenarioPart habitat)
    {
        ferry.Vessel.Landed = true;
        ferry.Vessel.Orbiting = false;
        ferry.Vessel.Latitude = habitat.Vessel.Latitude + 0.022;
        ferry.Vessel.Longitude = habitat.Vessel.Longitude;
    }
}
