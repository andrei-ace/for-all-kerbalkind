using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Serialization;
using FAMSeasons;
using ModuleManager;
using ModuleManager.Logging;
using ModuleManager.Patches;
using ModuleManager.Progress;
using ModuleManager.Tags;

internal static class StockSmoke
{
    private static string[] searchDirectories;

    private static Assembly Resolve(object sender, ResolveEventArgs request)
    {
        var filename = new AssemblyName(request.Name).Name + ".dll";
        var path = searchDirectories.Select(d => Path.Combine(d, filename)).FirstOrDefault(File.Exists);
        return path == null ? null : Assembly.LoadFrom(path);
    }

    private static IEnumerable<ConfigNode> Descend(ConfigNode parent)
    {
        foreach (ConfigNode node in parent.nodes) {
            yield return node;
            foreach (var child in Descend(node)) yield return child;
        }
    }

    private static int Main(string[] args)
    {
        searchDirectories = new [] { args[0], Path.Combine(args[1], "ContractConfigurator"),
            Path.Combine(args[1], "000_Harmony"), Path.Combine(args[2], "GameData", "FAMSeasons", "Plugins") };
        AppDomain.CurrentDomain.AssemblyResolve += Resolve;
        Assembly.LoadFrom(Directory.GetFiles(args[1], "ModuleManager*.dll").Single());
        ApplyResearchTree(args[1], args[2]);
        return Examine(args[2]);
    }

    private sealed class TestLogger : IBasicLogger
    {
        public void Log(ILogMessage message)
        {
            if (message.LogType != UnityEngine.LogType.Log)
                throw new InvalidDataException(message.ToLogString());
        }
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ApplyResearchTree(string gameData, string release)
    {
        var stockPath = Path.Combine(gameData, "Squad", "Resources", "TechTree.cfg");
        var patchPath = Path.Combine(release, "GameData", "FAMSeasons", "Season1", "Research", "TechTree.cfg");
        var root = new UrlDir(new UrlDir.ConfigDirectory[0], new UrlDir.ConfigFileType[0]);
        var stock = ConfigNode.Load(stockPath).GetNode("TechTree");
        var file = new UrlDir.UrlFile(root, new FileInfo(patchPath));
        var patch = new UrlDir.UrlConfig(file, ConfigNode.Load(patchPath).nodes[0]);
        var db = new LinkedList<IProtoUrlConfig>();
        db.AddLast(new ProtoUrlConfig(new UrlDir.UrlFile(root, new FileInfo(stockPath)), stock));
        var logger = new TestLogger();
        var progress = new PatchProgress(logger);
        var needs = new NeedsChecker(new [] {"Squad", "FAMSeasons"}, root, progress, logger);
        var extractor = new PatchExtractor(progress, logger, needs, new TagListParser(progress),
            new ProtoPatchBuilder(progress), new PatchCompiler());
        var compiled = extractor.ExtractPatch(patch);
        if (compiled == null || !compiled.PassSpecifier.CheckNeeds(needs, progress))
            throw new InvalidDataException("Missing FAMSeasons research pass");
        compiled.Apply(db, progress, logger);
        var stockIds = stock.GetNodes("RDNode").Select(n => n.GetValue("id")).ToArray();
        var ids = db.First.Value.Node.GetNodes("RDNode").Select(n => n.GetValue("id")).ToArray();
        if (ids.Distinct().Count() != ids.Length || ids.Length != stockIds.Length + 6 ||
            stockIds.Except(ids).Any() || !ids.Contains("famMunLogistics"))
            throw new InvalidDataException("Season 1 research patch did not extend the stock tree");
        Console.WriteLine("ModuleManager applied the research patch to all {0} stock nodes and added six.", stockIds.Length);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int Examine(string root)
    {
        var data = Path.Combine(root, "GameData", "FAMSeasons");
        var contracts = Assembly.LoadFrom(Path.Combine(searchDirectories[1], "ContractConfigurator.dll"));
        var plugin = Assembly.LoadFrom(Path.Combine(searchDirectories[3], "FAMSeasons.dll"));
        var types = contracts.GetTypes().Concat(plugin.GetTypes()).ToList();
        var nodes = new List<ConfigNode>();
        var configs = Directory.GetFiles(data, "*.cfg", SearchOption.AllDirectories);
        var craft = Directory.GetFiles(Path.Combine(root, "Ships", "VAB"), "FAM S1 - *.craft")
            .Concat(Directory.GetFiles(data, "*.craft", SearchOption.AllDirectories)).ToArray();
        foreach (var file in configs.Concat(craft)) {
            var contents = ConfigNode.Load(file);
            if (contents == null || contents.nodes.Count == 0) throw new InvalidDataException(file);
            nodes.AddRange(contents.nodes.Cast<ConfigNode>());
        }
        var objectives = nodes.Where(n => n.name == "CONTRACT_TYPE").SelectMany(Descend).ToList();
        var categories = new Dictionary<string, string> {
            { "PARAMETER", "ContractConfigurator.ParameterFactory" },
            { "REQUIREMENT", "ContractConfigurator.ContractRequirement" },
            { "BEHAVIOUR", "ContractConfigurator.BehaviourFactory" }
        };
        foreach (var category in categories) {
            var baseType = contracts.GetType(category.Value, true);
            var names = new HashSet<string>(types.Where(baseType.IsAssignableFrom).Select(t => t.Name));
            var suffix = category.Key == "REQUIREMENT" ? "Requirement" : "Factory";
            foreach (var node in objectives.Where(n => n.name == category.Key)) {
                string expected = node.GetValue("type") + suffix;
                if (!names.Contains(expected)) throw new InvalidDataException("Missing provider " + expected);
            }
        }
        var partTypes = new HashSet<string>(typeof(PartModule).Assembly.GetTypes().Concat(plugin.GetTypes())
            .Where(typeof(PartModule).IsAssignableFrom).Select(t => t.Name));
        var modules = nodes.Where(n => n.name == "PART").SelectMany(n => n.GetNodes("MODULE"))
            .Select(n => n.GetValue("name")).Distinct().ToList();
        foreach (var name in modules)
            if (!partTypes.Contains(name)) throw new InvalidDataException("Missing part module " + name);
        Console.WriteLine("KSP ConfigNode.Load parsed {0} configs and {1} craft. Resolved {2} mission objectives and {3} part module types.",
            configs.Length, craft.Length, objectives.Count(n => n.name == "PARAMETER"), modules.Count);
        var partConfigs = nodes.Where(n => n.name == "PART" && n.HasValue("name"))
            .ToDictionary(n => n.GetValue("name"));
        CheckLegacyStaging(plugin);
        foreach (var part in partConfigs.Values)
            CheckAutomaticStaging(part, null);
        foreach (var part in nodes.Where(n => n.name == "PART" && n.HasValue("part"))) {
            var id = part.GetValue("part");
            var separator = id.LastIndexOf('_');
            ConfigNode prefab;
            if (separator >= 0 && partConfigs.TryGetValue(id.Substring(0, separator), out prefab))
                CheckAutomaticStaging(prefab, part);
        }
        var scenarios = Directory.GetFiles(Path.Combine(root, "saves", "scenarios"), "FAM S1.*.sfs");
        if (scenarios.Length != 3) throw new InvalidDataException("Expected three complete Season 1 scenarios");
        int starts = 0;
        foreach (var file in scenarios) {
            var game = ConfigNode.Load(file).GetNode("GAME");
            if (game == null || game.GetValue("Mode") != Game.Modes.SCENARIO.ToString() ||
                game.GetValue("scene") != ((int)GameScenes.FLIGHT).ToString())
                throw new InvalidDataException("Invalid scenario flight header " + file);
            var vessels = game.GetNode("FLIGHTSTATE").GetNodes("VESSEL");
            var seats = vessels.SelectMany(n => n.GetNodes("PART")).SelectMany(n => n.GetValues("crew"));
            var kerbals = game.GetNode("ROSTER").GetNodes("KERBAL")
                .Where(n => n.GetValue("state") == "Assigned").Select(n => n.GetValue("name"));
            if (vessels.Length == 0 || !seats.OrderBy(n => n).SequenceEqual(kerbals.OrderBy(n => n)))
                throw new InvalidDataException("Invalid scenario vessel or crew data " + file);
            foreach (var vessel in vessels) {
                foreach (var field in new [] { "ACTIONGROUPS", "DISCOVERY", "FLIGHTPLAN", "CTRLSTATE", "VESSELMODULES" })
                    if (!vessel.HasNode(field)) throw new InvalidDataException("Missing " + field + " in " + file);
                foreach (var part in vessel.GetNodes("PART")) {
                    ConfigNode prefab;
                    if (partConfigs.TryGetValue(part.GetValue("name"), out prefab))
                        CheckAutomaticStaging(prefab, part);
                }
            }
            ScenarioSmoke.Check(game);
            starts += vessels.Length;
        }
        Console.WriteLine("KSP ConfigNode.Load parsed {0} scenario saves with {1} vessels.", scenarios.Length, starts);
        Console.WriteLine("The shipped scenario checklists passed successful flights, rejected unmet objectives, and restored saved progress.");
        Console.WriteLine("Stock KSP staging predicates verified shrouds and abort motors. Legacy repair preserved ignition and restored a service burn stage before separation.");
        return 0;
    }

    private static T CreateModuleForStagingTest<T>() where T : PartModule
    {
        // These stock predicates read module flags. The test can run without a Unity scene.
        return (T)FormatterServices.GetUninitializedObject(typeof(T));
    }

    private static bool ReadFlag(ConfigNode prefab, ConfigNode snapshot, string key, bool fallback)
    {
        string value = snapshot?.GetValue(key) ?? prefab.GetValue(key);
        return value == null ? fallback : bool.Parse(value);
    }

    private static void ReadStageFlags(PartModule module, ConfigNode prefab, ConfigNode snapshot)
    {
        module.stagingEnabled = ReadFlag(prefab, snapshot, "stagingEnabled", true);
        module.stagingToggleEnabledEditor = ReadFlag(prefab, snapshot, "stagingToggleEnabledEditor", false);
        module.stagingToggleEnabledFlight = ReadFlag(prefab, snapshot, "stagingToggleEnabledFlight", false);
    }

    private static void CheckAutomaticStaging(ConfigNode part, ConfigNode snapshot)
    {
        var policy = part.GetNodes("MODULE").FirstOrDefault(m => m.GetValue("name") == "FAMStagePolicy");
        if (policy == null) return;
        foreach (var prefab in part.GetNodes("MODULE")) {
            string name = prefab.GetValue("name");
            PartModule module;
            if (name == "ModuleJettison")
                module = CreateModuleForStagingTest<ModuleJettison>();
            else if (name == "ModuleEnginesFX" && policy.GetValue("manualIgnition") == "True")
                module = CreateModuleForStagingTest<ModuleEnginesFX>();
            else
                continue;
            var saved = snapshot?.GetNodes("MODULE").FirstOrDefault(m => m.GetValue("name") == name);
            ReadStageFlags(module, prefab, saved);
            if (!StagingDisabled(module))
                throw new InvalidDataException(part.GetValue("name") + " exposes " + name + " in staging");
        }
    }

    private static bool StagingDisabled(PartModule module)
    {
        // Part.UpdateStageability requires both predicates. Engines remain stage-capable even when disabled.
        return !(module.IsStageable() && module.StagingEnabled()) &&
            !module.stagingToggleEnabledEditor && !module.stagingToggleEnabledFlight;
    }

    private static void CheckLegacyStaging(Assembly plugin)
    {
        var policy = plugin.GetType("FAMSeasons.FAMStagePolicy", true)
            .GetMethod("DisableStageAction", BindingFlags.Static | BindingFlags.NonPublic);
        var shroud = CreateModuleForStagingTest<ModuleJettison>();
        shroud.stagingEnabled = true;
        shroud.isJettisoned = true;
        if (StagingDisabled(shroud)) throw new InvalidDataException("Failed to reproduce the legacy shroud stage");
        policy.Invoke(null, new object[] { shroud, false });
        if (shroud.IsStageable() || !shroud.isJettisoned)
            throw new InvalidDataException("Legacy shroud staging repair failed");

        var engine = CreateModuleForStagingTest<ModuleEnginesFX>();
        engine.stagingEnabled = true;
        engine.stagingToggleEnabledEditor = true;
        engine.stagingToggleEnabledFlight = true;
        engine.EngineIgnited = true;
        policy.Invoke(null, new object[] { engine, false });
        if (!engine.StagingEnabled()) throw new InvalidDataException("Legacy repair changed a normal staged engine");
        policy.Invoke(null, new object[] { engine, true });
        if (!StagingDisabled(engine) || !engine.EngineIgnited)
            throw new InvalidDataException("Legacy abort motor staging repair failed");

        int engineStage = 1;
        if (!FAMStagePolicy.RestoreServiceEngineStage(engine, 1, -1, ref engineStage) ||
            engineStage != 2 || !(engine.IsStageable() && engine.StagingEnabled()) ||
            !engine.EngineIgnited || engine.staged)
            throw new InvalidDataException("Legacy service engine needs a burn stage with its ignition state preserved");
        if (FAMStagePolicy.RestoreServiceEngineStage(engine, 1, -1, ref engineStage))
            throw new InvalidDataException("Reloading a repaired service engine must keep its stage");

        engine.stagingEnabled = false;
        engine.EngineIgnited = false;
        engineStage = -1;
        if (!FAMStagePolicy.RestoreServiceEngineStage(engine, 1, 3, ref engineStage) ||
            engineStage != 3 || engine.EngineIgnited)
            throw new InvalidDataException("A legacy lunar train must arm its service engine at payload release");
    }
}
