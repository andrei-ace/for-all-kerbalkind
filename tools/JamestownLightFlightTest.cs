// Exercise the stock action, real spotlights and electrical load in a disposable flight.
using System;
using System.Collections;
using System.Linq;
using UnityEngine;

public static class JamestownLightFlightTest
{
    // ModuleLight fades the emissive material over this part's configured 2.5 seconds.
    const float FadeWait = 3f;

    static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    static void CheckPart(Part part, bool on)
    {
        var module = part.FindModuleImplementing<ModuleLight>();
        Require(module != null && module.Actions.Any(a => (a.actionGroup & KSPActionGroup.Light) != 0),
                part.name + " has no stock Lights action");
        var lights = part.FindModelComponents<Light>(module.lightName);
        Require(lights.Count == 2 && lights.All(l => l.type == LightType.Spot && l.range >= 8),
                part.name + " must contain two working floodlights");
        Require(module.isOn == on && lights.All(l => (l.enabled && l.intensity > 0.05f) == on),
                part.name + " beam state after U = " + on + ": " +
                string.Join(", ", lights.Select(l => l.enabled + "/" + l.intensity)));
        var lens = part.FindModelComponent<MeshRenderer>(module.lightMeshRendererName);
        Require(lens != null && lens.material.HasProperty("_EmissiveColor"),
                part.name + " is missing its emissive lens material on " + module.lightMeshRendererName);
        var brightness = lens.material.GetColor("_EmissiveColor").maxColorComponent;
        Require((brightness > 0.05f) == on,
                part.name + $" lens brightness {brightness:F3} after Lights {(on ? "on" : "off")}");
        Debug.Log($"[Jamestown test] {part.partInfo.title}, Lights {(on ? "on" : "off")}, " +
                  $"lens {brightness:F3}, two {lights[0].range:g} m beams at {lights[0].intensity:F3}");
    }

    public static IEnumerator Check(Part airlock)
    {
        var vessel = airlock.vessel;
        var frame = vessel.parts.Single(p => p.partInfo.name == "famJamestownFrame");
        CheckPart(airlock, false);
        CheckPart(frame, false);
        // Sun tracking and fuel cell production can each dwarf this load. Disconnect
        // those generators in the test vessel while keeping the stock battery bus live.
        var generators = vessel.parts.SelectMany(p => p.Modules.Cast<PartModule>())
            .Where(m => m is ModuleDeployableSolarPanel || m is ModuleResourceConverter ||
                        m is ModuleAlternator || m is ModuleGenerator)
            .Select(m => new { module = m, behaviourEnabled = m.enabled, moduleEnabled = m.isEnabled }).ToArray();
        foreach (var g in generators) { g.module.isEnabled = false; g.module.enabled = false; }
        yield return new WaitForFixedUpdate();
        var batteries = vessel.parts.Select(p => p.Resources.Get("ElectricCharge")).Where(r => r != null).ToArray();
        var initial = batteries.Select(r => r.amount).ToArray();
        foreach (var battery in batteries) battery.amount *= 0.75;
        Func<double> charge = () => batteries.Sum(r => r.amount);
        double startCharge = charge();
        float startTime = Time.fixedTime;
        for (int i = 0; i < 100; i++) yield return new WaitForFixedUpdate();
        double darkRate = (startCharge - charge()) / (Time.fixedTime - startTime);
        vessel.ActionGroups.ToggleGroup(KSPActionGroup.Light);
        yield return new WaitForSeconds(FadeWait);
        CheckPart(airlock, true);
        CheckPart(frame, true);
        var beams = airlock.FindModelComponents<Light>("jamestownFlood");
        for (int i = 1; i <= 4; i++)
        {
            var step = airlock.FindModelTransform("stairTread" + i);
            Require(beams.All(l => Vector3.Angle(l.transform.forward, step.position - l.transform.position)
                                   < l.spotAngle / 2), "Boarding lamps must illuminate tread " + i);
        }
        startCharge = charge();
        startTime = Time.fixedTime;
        for (int i = 0; i < 100; i++) yield return new WaitForFixedUpdate();
        double litRate = (startCharge - charge()) / (Time.fixedTime - startTime);
        vessel.ActionGroups.ToggleGroup(KSPActionGroup.Light);
        yield return new WaitForSeconds(FadeWait);
        CheckPart(airlock, false);
        CheckPart(frame, false);
        for (int i = 0; i < batteries.Length; i++) batteries[i].amount = initial[i];
        foreach (var g in generators) { g.module.enabled = g.behaviourEnabled; g.module.isEnabled = g.moduleEnabled; }
        Require(Math.Abs(litRate - darkRate - 0.06) < 0.012,
                $"Landing and boarding lights must draw 0.06 EC/s together. Off {darkRate:F4}, on {litRate:F4}");
        Debug.Log($"[Jamestown test] U switched four beams and lenses and lit the four treads. " +
                  $"Additional draw {litRate - darkRate:F4} EC/s");
    }

    public static IEnumerator CheckIndependent(Part baseHull, Part airlock)
    {
        var frame = baseHull.vessel.parts.Single(p => p.partInfo.name == "famJamestownFrame");
        Require(airlock.vessel != frame.vessel, "Light independence needs two released vessels");
        airlock.vessel.ActionGroups.SetGroup(KSPActionGroup.Light, true);
        frame.vessel.ActionGroups.SetGroup(KSPActionGroup.Light, false);
        yield return new WaitForSeconds(FadeWait);
        CheckPart(airlock, true);
        CheckPart(frame, false);
        airlock.vessel.ActionGroups.SetGroup(KSPActionGroup.Light, false);
        frame.vessel.ActionGroups.SetGroup(KSPActionGroup.Light, true);
        yield return new WaitForSeconds(FadeWait);
        CheckPart(airlock, false);
        CheckPart(frame, true);
        frame.vessel.ActionGroups.SetGroup(KSPActionGroup.Light, false);
        yield return new WaitForSeconds(FadeWait);
        CheckPart(frame, false);
        Debug.Log("[Jamestown test] Released airlock and landing frame lit independently through U");
    }
}
