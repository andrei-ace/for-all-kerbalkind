using System.Collections.Generic;
using UnityEngine;

namespace FAMSeasons
{
    [KSPAddon(KSPAddon.Startup.Flight, false)]
    public sealed class FAMCrewAppearance : MonoBehaviour
    {
        private static readonly int MainTexture = Shader.PropertyToID("_MainTex");
        private readonly Dictionary<string, Texture2D> faces = new Dictionary<string, Texture2D>();
        private readonly HashSet<string> reported = new HashSet<string>();
        private MaterialPropertyBlock properties;
        private float nextCheck;

        private void Start()
        {
            properties = new MaterialPropertyBlock();
            foreach (var profile in GameDatabase.Instance.GetConfigNodes("FAM_CHARACTER"))
            {
                var texture = GameDatabase.Instance.GetTexture(profile.GetValue("head"), false);
                if (texture != null)
                    faces[profile.GetValue("name")] = texture;
            }
        }

        private void Update()
        {
            if (!FlightGlobals.ready || faces.Count == 0 || Time.unscaledTime < nextCheck)
                return;
            nextCheck = Time.unscaledTime + 0.5f;
            foreach (var kerbal in FindObjectsOfType<Kerbal>())
            {
                var name = kerbal.protoCrewMember?.name;
                if (name == null || !faces.TryGetValue(name, out var face) || kerbal.HeadRenderers == null)
                    continue;
                foreach (var renderer in kerbal.HeadRenderers)
                {
                    if (renderer == null)
                        continue;
                    var materials = renderer.sharedMaterials;
                    for (int i = 0; i < materials.Length; i++)
                    {
                        var texture = materials[i]?.mainTexture;
                        if (texture == null || (texture.name != "kerbalHead" && texture.name != "kerbalGirl_06_BaseColor"))
                            continue;
                        renderer.GetPropertyBlock(properties, i);
                        if (properties.GetTexture(MainTexture) != face)
                        {
                            properties.SetTexture(MainTexture, face);
                            renderer.SetPropertyBlock(properties, i);
                            if (reported.Add(name))
                                Debug.Log("[FAMSeasons] Applied head texture for " + name);
                        }
                    }
                }
            }
        }
    }
}
