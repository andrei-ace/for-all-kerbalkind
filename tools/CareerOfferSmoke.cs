// Run only in a disposable Career game. The stock R&D and contract history are test fixtures.
using System;
using System.Collections;
using System.IO;
using System.Linq;
using System.Reflection;
using ContractConfigurator;
using Contracts;
using UnityEngine;

[KSPAddon(KSPAddon.Startup.MainMenu, true)]
public sealed class CareerOfferSmoke : MonoBehaviour
{
    const string Tag = "[FAM Career] ";
    static readonly string[] Names = { "FAMS1RedMun", "FAMS1Apollo11", "FAMS1JamestownCampaign" };

    IEnumerator Start()
    {
        string folder = Environment.GetEnvironmentVariable("FAM_CAREER_TEST_SAVE");
        if (string.IsNullOrEmpty(folder)) yield break;
        DontDestroyOnLoad(gameObject);
        Application.runInBackground = true;
        while (FindObjectOfType<MainMenu>() == null) yield return null;
        var settings = GameParameters.GetDefaultParameters(Game.Modes.CAREER, GameParameters.Preset.Normal);
        settings.Difficulty.BypassEntryPurchaseAfterResearch = false;
        var game = GamePersistence.CreateNewGame(folder, Game.Modes.CAREER, settings, "Squad/Flags/default",
                                                  GameScenes.SPACECENTER, EditorFacility.None);
        HighLogic.CurrentGame = game;
        GameEvents.onGameNewStart.Fire();
        game.Start();
        var deadline = Time.realtimeSinceStartup + 70;
        while (HighLogic.LoadedScene != GameScenes.SPACECENTER || ContractSystem.Instance == null ||
               ResearchAndDevelopment.Instance == null || !ContractSystem.loaded || SpaceCenter.Instance == null)
        {
            if (Time.realtimeSinceStartup > deadline) { Debug.LogError(Tag + $"Career did not load: scene {HighLogic.LoadedScene}, RD {ResearchAndDevelopment.Instance}, contracts {ContractSystem.Instance}, loaded {ContractSystem.loaded}"); Application.Quit(1); yield break; }
            yield return null;
        }
        yield return new WaitForSecondsRealtime(1);
        try { Check(); Debug.Log(Tag + "PASS"); Application.Quit(); }
        catch (Exception error) { Debug.LogError(Tag + error); Application.Quit(1); }
    }

    static void Need(bool ok, string message) { if (!ok) throw new InvalidDataException(message); }

    static void Check()
    {
        Need(HighLogic.CurrentGame.Mode == Game.Modes.CAREER, "Expected Career");
        var types = Names.Select(ContractType.GetContractType).ToArray();
        Need(types.All(t => t != null && t.enabled), "A campaign contract failed to load");
        var candidates = types.Select(t => new ConfiguredContract { contractType = t, subType = t.name }).ToArray();
        Func<int,bool> offered = i => types[i].MeetRequirements(candidates[i], types[i]);
        Need(!Enumerable.Range(0, 3).Any(offered), "Mission offered with starting research");
        foreach (var facility in FindObjectsOfType<Upgradeables.UpgradeableFacility>())
            facility.SetLevel(2);
        var hardware = GameDatabase.Instance.GetConfigNodes("CONTRACT_TYPE").Where(n => Names.Contains(n.GetValue("name")))
            .ToDictionary(n => n.GetValue("name"), n => n.GetNodes("REQUIREMENT").Single(r => r.GetValue("type") == "PartUnlocked")
                .GetValues("part").Select(id => PartLoader.getPartInfoByName(id.Replace('_','.'))).ToArray());
        var all = hardware.Values.SelectMany(x => x).Distinct().ToList();
        Need(all.All(p => p != null), "Missing flight part");
        foreach (var group in all.GroupBy(p => p.TechRequired))
        {
            var tech = new ProtoTechNode { techID = group.Key, state = RDTech.State.Available, partsPurchased = group.ToList() };
            ResearchAndDevelopment.Instance.SetTechState(group.Key, tech);
        }
        for (int i = 0; i < types.Length; i++)
        {
            Debug.Log(Tag + types[i].name + " gates " + string.Join(", ", types[i].Requirements.Select(r =>
                r.GetType().Name + "=" + r.RequirementMet(candidates[i]))));
            for (int j = 0; j < types.Length; j++)
                Need(offered(j) == (j == i), "Unexpected offer at step " + i + " for " + types[j].name);
            foreach (var techId in hardware[Names[i]].Select(p => p.TechRequired).Distinct())
            {
                var tech = ResearchAndDevelopment.Instance.GetTechState(techId);
                tech.state = RDTech.State.Unavailable;
                Need(!offered(i), "Offered without research " + techId);
                tech.state = RDTech.State.Available;
            }
            foreach (var part in hardware[Names[i]])
            {
                var node = ResearchAndDevelopment.Instance.GetTechState(part.TechRequired);
                node.partsPurchased.Remove(part);
                Need(!ResearchAndDevelopment.PartModelPurchased(part) && !offered(i), "Offered without " + part.name);
                node.partsPurchased.Add(part);
            }
            Debug.Log(Tag + types[i].name + " only offer; individually withheld " + hardware[Names[i]].Length + " parts");
            var state = typeof(Contract).GetField("state", BindingFlags.Instance | BindingFlags.NonPublic);
            var history = new ConfiguredContract { contractType = types[i], subType = Names[i] };
            // KSP restores this same state field from the career save.
            var records = ContractSystem.Instance.ContractsFinished;
            records.Add(history);
            foreach (Contract.State finished in new[] {Contract.State.Offered, Contract.State.Active, Contract.State.Failed, Contract.State.Cancelled, Contract.State.Completed})
            {
                state.SetValue(history, finished);
                typeof(ConfiguredContract).GetField("_completedContractsByName", BindingFlags.Static | BindingFlags.NonPublic).SetValue(null, null);
                if (i + 1 < types.Length)
                    Need(offered(i+1) == (finished == Contract.State.Completed), finished + " progression at " + Names[i]);
            }
        }
        Need(!Enumerable.Range(0, 3).Any(offered), "Season repeated after completion");
    }
}
