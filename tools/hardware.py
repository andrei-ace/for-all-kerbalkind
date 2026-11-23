from config import Node
from parts import (
    APOLLO,
    BOOST,
    CAPSULES,
    DOCKING,
    FRAMES,
    HAB,
    HAB_PORT_X,
    HAB_PORT_Y,
    HAB_PORTS,
    L3,
    LOGISTICS,
    POLAR,
)


def keep_out_of_staging(config):
    return (
        config.add("stagingEnabled", "False")
        .add("stagingToggleEnabledEditor", "False")
        .add("stagingToggleEnabledFlight", "False")
    )


def module(name, **values):
    return Node("MODULE", name=name, **values)


def resource(name, amount):
    return Node("RESOURCE", name=name, amount=f"{amount:g}", maxAmount=f"{amount:g}")


def loaded_resources(cfg, propellant_fraction):
    for tank in cfg.children("RESOURCE"):
        name = tank.values("name")[0]
        amount = tank.values("amount")[0]
        if name in ("LiquidFuel", "Oxidizer"):
            amount = f"{float(amount) * propellant_fraction:g}"
        yield Node("RESOURCE", name=name, amount=amount, maxAmount=tank.values("maxAmount")[0])


def engine(p):
    m = module(
        "ModuleEnginesFX",
        thrustVectorTransformName="thrustTransform",
        engineID="main",
        minThrust=0,
        maxThrust=p.thrust,
        heatProduction=95,
        EngineType="LiquidFuel",
        exhaustDamage="True",
        ignitionThreshold=0.1,
        runningEffectName="exhaust",
    )
    for name, ratio in (("LiquidFuel", 0.9), ("Oxidizer", 1.1)):
        m.child(Node("PROPELLANT", name=name, ratio=ratio, DrawGauge="True"))
    curve = Node("atmosphereCurve")
    for key in (f"0 {p.vacuum}", f"1 {p.sea}", "8 0.001"):
        curve.add("key", key)
    return m.child(curve)


def exhaust(p):
    audio = Node(
        "AUDIO",
        channel="Ship",
        clip="sound_rocket_hard" if p.thrust > 200 else "sound_rocket_mini",
        loop="true",
    )
    for key, val in (
        ("volume", "0.0 0.0"),
        ("volume", "1.0 0.65"),
        ("pitch", "0.0 0.6"),
        ("pitch", "1.0 1.1"),
    ):
        audio.add(key, val)
    plume = "ks1_Exhaust" if p.id == "famSaturnIC" else "shockExhaust_blue_small"
    jet = Node("MODEL_MULTI_PARTICLE", modelName="Squad/FX/" + plume, transformName="thrustTransform")
    jet.add("emission", "0.0 0.0").add("emission", "0.05 0.15").add("emission", "1.0 1.0")
    jet.add("speed", "0 0.4").add("speed", "1 1.5")
    return Node("EFFECTS").child(Node("exhaust").child(audio).child(jet))


def add_rcs(cfg, capacity, thrust):
    cfg.child(resource("MonoPropellant", capacity))
    rcs = module(
        "ModuleRCSFX",
        stagingEnabled="False",
        thrusterTransformName="rcsJet",
        thrusterPower=thrust,
        resourceName="MonoPropellant",
        resourceFlowMode="STAGE_PRIORITY_FLOW",
        runningEffectName="rcs",
    )
    cfg.child(rcs.child(Node("atmosphereCurve").add("key", "0 240").add("key", "1 100")))
    jet = Node(
        "MODEL_MULTI_PARTICLE",
        modelName="Squad/FX/Monoprop_small",
        transformName="rcsJet",
        localRotation="-90, 0, 0",
    )
    jet.add("emission", "0 0").add("emission", "1 1").add("speed", "0 0.8").add("speed", "1 1")
    effects = cfg.children("EFFECTS")
    if not effects:
        effects = [Node("EFFECTS")]
        cfg.child(effects[0])
    effects[0].child(Node("rcs").child(jet))


def add_command(cfg, p):
    cfg.add("CrewCapacity", p.crew).add("vesselType", "Base" if p.role == "hab" else "Ship")
    cfg.child(Node("INTERNAL", name=p.internal))
    command = module("ModuleCommand", minimumCrew=0 if p.role == "hab" else 1)
    if p.role == "hab":
        command.child(Node("RESOURCE", name="ElectricCharge", rate=0.025))
    cfg.child(command)
    # Direct aerial also gives the unmanned Jamestown stack control at the Mun.
    cfg.child(
        module(
            "ModuleDataTransmitter",
            antennaType="DIRECT",
            packetInterval=0.6,
            packetSize=2,
            packetResourceCost=4,
            requiredResource="ElectricCharge",
            antennaPower=15000000,
        )
    )
    wheel = 10 if p.role in ("cm", "lok", "hab") else 5
    cfg.child(
        module("ModuleReactionWheel", PitchTorque=wheel, YawTorque=wheel, RollTorque=wheel).child(
            Node("RESOURCE", name="ElectricCharge", rate=0.24)
        )
    )
    cfg.child(
        module(
            "ModuleScienceContainer",
            reviewActionName="Review samples",
            storeActionName="Store samples",
            evaOnlyStorage="True",
            storageRange=2.5,
        )
    )
    cfg.child(
        module(
            "ModuleScienceExperiment",
            experimentID="crewReport",
            experimentActionName="Crew report",
            resetActionName="Discard crew report",
            reviewActionName="Review crew report",
            useStaging="False",
            rerunnable="True",
            xmitDataScalar=1,
            usageReqMaskInternal=5,
            usageReqMaskExternal=-1,
        )
    )
    cfg.child(module("ModuleInventoryPart", InventorySlots=p.crew, packedVolumeLimit=p.crew * 100))
    cfg.child(resource("ElectricCharge", 2200 if p.role == "hab" else 320))
    add_rcs(cfg, 55 if p.role == "lsam" else 18, 0.55)
    if p.role in CAPSULES:
        # Put the pressure centre toward the nose and the mass toward the broad, shielded end.
        cfg.add("CoMOffset", "0, -0.32, 0").add("CoPOffset", "0, 0.50, 0").add("CoLOffset", "0, -0.34, 0")
        cfg.add("bodyLiftOnlyUnattachedLift", "True").add("bodyLiftOnlyAttachName", "bottom")
        cfg.add("skinMaxTemp", 3300).add("emissiveConstant", 0.9).add("skinInternalConductionMult", 0.15)
        cfg.add("buoyancy", 1.1)
        cfg.child(resource("Ablator", 250 if p.role == "lok" else 410))
        cfg.child(
            module(
                "ModuleAblator",
                ablativeResource="Ablator",
                lossExp=-7500,
                lossConst=0.1,
                pyrolysisLossFactor=6000,
                reentryConductivity=0.01,
                ablationTempThresh=500,
            )
        )
    if p.role in ("lsam", "hab"):
        cfg.child(
            module(
                "ModuleDeployableSolarPanel",
                isTracking="false",
                isBreakable="false",
                useAnimation="false",
                retractable="false",
                secondaryTransformName="sunCatcher",
                raycastTransformName="sunCatcher",
                pivotName="sunCatcher",
                resourceName="ElectricCharge",
                chargeRate=6 if p.role == "hab" else 2,
            )
        )
    if p.role == "hab":
        cfg.child(module("ModuleSAS", SASServiceLevel=2))
        cell = module(
            "ModuleResourceConverter",
            ConverterName="Habitat fuel cell",
            StartActionName="Start fuel cell",
            StopActionName="Stop fuel cell",
            FillAmount=0.95,
            AutoShutdown="false",
            GeneratesHeat="false",
            UseSpecialistBonus="false",
        )
        cell.child(Node("INPUT_RESOURCE", ResourceName="LiquidFuel", Ratio=0.0016875))
        cell.child(Node("INPUT_RESOURCE", ResourceName="Oxidizer", Ratio=0.0020625))
        cfg.child(
            cell.child(Node("OUTPUT_RESOURCE", ResourceName="ElectricCharge", Ratio=1.5, DumpExcess="false"))
        )


def node_size(radius):
    if radius >= 1.5:
        return 3
    if radius >= 0.92:
        return 2
    return int(radius >= 0.40)


def part_config(p):
    if p.role in ("ring", "adapter"):
        category = "Coupling"
    elif p.role == "tower":
        category = "Utility"
    elif p.role == "corer":
        category = "Science"
    elif p.crew:
        category = "Utility" if p.role == "hab" else "Pods"
    else:
        category = "Engine" if p.thrust else "FuelTank"
    cfg = Node(
        "PART",
        name=p.id,
        module="Part",
        author="FAM Seasons",
        title=p.title,
        manufacturer="Jamestown Flight Works",
        description=p.description,
        TechRequired=p.tech,
        entryCost=0,
        cost=p.cost,
        category=category,
        subcategory=0,
        scale=1,
        rescaleFactor=1,
    )
    cfg.child(Node("MODEL", model="FAMSeasons/Season1/Parts/" + p.id))
    if p.role == "corer":
        cfg.add("node_attach", "0, 0, 0.10, 0, 0, -1, 0").add("attachRules", "0,1,0,0,0")
    else:
        for side, sign, radius in (("top", 1, p.top_radius), ("bottom", -1, p.radius)):
            cfg.add("node_stack_" + side, f"0, {sign * p.height / 2:g}, 0, 0, {sign}, 0, {node_size(radius)}")
        cfg.add("attachRules", "1,0,1,1,0")
    cfg.add("bulkheadProfiles", f"size{node_size(p.radius)}, srf")
    cfg.add("mass", p.dry).add("crashTolerance", 19 if p.role in FRAMES | CAPSULES else 12)
    cfg.add("breakingForce", 600).add("breakingTorque", 600).add(
        "maxTemp", 2200 if p.role in CAPSULES else 2000
    )
    cfg.add("dragModelType", "default").add("maximum_drag", 0.2).add("minimum_drag", 0.15).add(
        "angularDrag", 1.5
    )
    cfg.add("tags", "fam season 1 mun jamestown " + p.title.lower())
    if p.fuel:
        # Stock LF and oxidizer each weigh 0.005 t per resource unit.
        cfg.child(resource("LiquidFuel", 90 * p.fuel)).child(resource("Oxidizer", 110 * p.fuel))
    if p.thrust:
        cfg.child(engine(p)).child(exhaust(p))
        cfg.child(module("ModuleAlternator").child(Node("RESOURCE", name="ElectricCharge", rate=2)))
    if p.role in ("saturn", "n1"):
        # A single gimbal per cluster rotates all thrust transforms around the common mount.
        cfg.child(module("ModuleGimbal", gimbalTransformName="gimbal", gimbalRange=3))
    if p.crew:
        add_command(cfg, p)
    if p.role in DOCKING:
        cfg.child(
            module(
                "ModuleDockingNode",
                referenceAttachNode="top",
                nodeTransformName="dockingNode",
                nodeType="size1",
                stagingEnabled="False",
            )
        )
    if p.role == "hab":
        for port, sign in HAB_PORTS:
            cfg.add("node_stack_" + port, f"{sign * HAB_PORT_X:g}, {HAB_PORT_Y:g}, 0, {sign}, 0, 0, 1")
            cfg.child(
                module(
                    "ModuleDockingNode",
                    referenceAttachNode=port,
                    nodeTransformName=port + "Dock",
                    nodeType="size1",
                    stagingEnabled="False",
                )
            )
    if p.role in ("saturn", "n1", "service"):
        cfg.child(
            keep_out_of_staging(
                module(
                    "ModuleJettison",
                    jettisonName="interstage",
                    bottomNodeName="bottom",
                    isFairing="True",
                    checkBottomNode="True",
                    jettisonedObjectMass=0.03,
                    jettisonForce=4,
                    jettisonDirection="0 0 1",
                )
            )
        )
    if p.role == "adapter":
        cfg.child(
            module(
                "ModuleProceduralFairing",
                nSides=32,
                nArcs=2,
                nCollidersPerXSection=8,
                TextureURL="Squad/Parts/Aero/fairings/fairings_diff",
                CapTextureURL="Squad/Parts/Aero/fairings/fairingsCap",
                TextureNormalURL="Squad/Parts/Aero/fairings/fairings_normals",
                BaseModelTransformName="Exterior",
                pivot="0,-0.33,0",
                axis="0,1,0",
                baseRadius=1.25,
                maxRadius=3,
                capRadius=0.15,
                snapThreshold=0.25,
                xSectionHeightMin=0.2,
                xSectionHeightMax=6,
                noseTip=0.3,
                UnitAreaMass=0.01,
                UnitAreaCost=8,
                stagingToggleEnabledEditor="True",
            )
        )
        cfg.child(
            module(
                "ModuleCargoBay",
                DeployModuleIndex=0,
                closedPosition=0,
                lookupRadius=2.5,
                partTypeName="Fairing",
            )
        )
    if p.role in ("ring", "adapter", "tower"):
        cfg.add("fx_gasBurst_white", "0, 0, 0, 0, 1, 0, decouple")
        cfg.add("sound_decoupler_fire", "decouple")
    if p.role in ("ring", "adapter"):
        # Free both faces so the lander's nose port is clear after transposition.
        cfg.add("fuelCrossFeed", "False").add("stagingIcon", "DECOUPLER_VERT")
        cfg.child(module("ModuleDecouple", isOmniDecoupler="True", ejectionForce=18))
    if p.role == "tower":
        cfg.add("fuelCrossFeed", "False")
        cfg.child(resource("SolidFuel", 12))
        m = module(
            "ModuleEnginesFX",
            thrustVectorTransformName="escapeJet",
            engineID="escape",
            throttleLocked="True",
            allowShutdown="False",
            allowRestart="False",
            exhaustDamage="False",
            minThrust=0,
            maxThrust=125,
            EngineType="SolidBooster",
            ignitionThreshold=0.1,
            runningEffectName="escape",
        )
        keep_out_of_staging(m)
        m.child(Node("PROPELLANT", name="SolidFuel", ratio=1, DrawGauge="True"))
        cfg.child(m.child(Node("atmosphereCurve").add("key", "0 175").add("key", "1 155")))
        cfg.child(module("ModuleDecouple", explosiveNodeID="bottom", ejectionForce=18))
        plume = Node(
            "MODEL_MULTI_PARTICLE", modelName="Squad/FX/shockExhaust_red_small", transformName="escapeJet"
        )
        plume.add("emission", "0 0").add("emission", "1 1").add("speed", "0 0").add("speed", "1 1")
        cfg.child(Node("EFFECTS").child(Node("escape").child(plume)))
    if p.role in ("saturn", "n1", "service", "tower"):
        policy = module(
            "FAMStagePolicy", manualIgnition=str(p.role == "tower").title(), stagingEnabled="False"
        )
        if p.role == "service":
            policy.add("stageServiceEngine", "True")
        cfg.child(policy)
    if p.role == "corer":
        cfg.child(
            module(
                "ModuleScienceExperiment",
                experimentID="famPolarCore",
                experimentActionName="Drill a regolith core",
                resetActionName="Discard core",
                reviewActionName="Inspect core",
                useStaging="False",
                useActionGroups="True",
                rerunnable="True",
                xmitDataScalar=0,
                dataIsCollectable="True",
                collectActionName="Take the core",
                interactionRange=2.5,
                usageReqMaskInternal=1,
                usageReqMaskExternal=8,
            )
        )
    return cfg


TECH = [
    (BOOST, "Mun Launch Vehicles", 45, "RDicon_rocketry-heavy", (-1590, 1780), ["heavyRocketry"]),
    (L3, "Soviet L3 Landing System", 45, "RDicon_landing", (-1390, 1860), [BOOST]),
    (APOLLO, "Apollo Lunar Systems", 45, "RDicon_commandmodules", (-1390, 1740), [BOOST]),
    (POLAR, "Polar Prospecting", 60, "RDicon_scienceTech", (-1190, 1800), [APOLLO]),
    (HAB, "Surface Habitation", 90, "RDicon_construction-advanced", (-995, 1800), [POLAR]),
    (LOGISTICS, "Reusable Mun Logistics", 90, "RDicon_fuelSystems", (-800, 1800), [HAB]),
]


def tech_tree():
    tree = Node("@TechTree:FOR[FAMSeasons]")
    for key, title, cost, icon, (x, y), parents in TECH:
        n = Node(
            "RDNode",
            id=key,
            title=title,
            description="Season 1 research for " + title + ".",
            cost=cost,
            hideEmpty="False",
            nodeName="node_" + key,
            anyToUnlock="False",
            icon=icon,
            pos=f"{x},{y},0",
            scale=0.6,
        )
        for parent in parents:
            n.child(
                Node(
                    "Parent",
                    parentID=parent,
                    lineFrom="TOP" if parent == "heavyRocketry" else "RIGHT",
                    lineTo="LEFT",
                )
            )
        tree.child(n)
    return tree


def science():
    results = Node(
        "RESULTS",
        default="A layered regolith core. Record the location before opening the sample tube.",
        MunSrfLanded="Compacted Mun dust gives way to older impact layers.",
    )
    for biome in ("Poles", "PolarLowlands", "PolarCrater"):
        results.add(
            "MunSrfLanded" + biome,
            "Pale ice crystals survive below the surface. Seal the tube for the return flight.",
        )
    return Node(
        "EXPERIMENT_DEFINITION",
        id="famPolarCore",
        title="Polar Regolith Core",
        baseValue=12,
        scienceCap=18,
        dataScale=1,
        requireAtmosphere="False",
        situationMask=1,
        biomeMask=1,
    ).child(results)
