/* Tweaks island for the hi-fi home page.
   Reflects choices onto <html> data-attributes consumed by app.css. */

const APP_TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "auto",
  "accent": "rose",
  "density": "comfortable"
}/*EDITMODE-END*/;

function applyAppTweaks(t) {
  const r = document.documentElement;
  r.dataset.theme = t.theme;
  r.dataset.accent = t.accent;
  r.dataset.density = t.density === "comfortable" ? "comfy" : "compact";
}

function AppTweaks() {
  const [t, setTweak] = useTweaks(APP_TWEAK_DEFAULTS);
  React.useEffect(() => { applyAppTweaks(t); }, [t]);
  return (
    <TweaksPanel>
      <TweakSection label="Appearance" />
      <TweakRadio
        label="Theme"
        value={t.theme}
        options={["auto", "light", "dark"]}
        onChange={(v) => setTweak("theme", v)}
      />
      <p style={{
        margin: "-4px 2px 4px", fontSize: 12, lineHeight: 1.4,
        color: "var(--tw-muted, #8a817a)"
      }}>
        Auto follows your device’s light / dark setting.
      </p>
      <TweakColor
        label="Accent"
        value={t.accent === "rose" ? "#8a2d52" : "#8a4b32"}
        options={["#8a2d52", "#8a4b32"]}
        onChange={(v) => setTweak("accent", v === "#8a2d52" ? "rose" : "brown")}
      />
      <TweakSection label="Layout" />
      <TweakRadio
        label="Density"
        value={t.density}
        options={["comfortable", "compact"]}
        onChange={(v) => setTweak("density", v)}
      />
    </TweaksPanel>
  );
}

// apply defaults before React paints
applyAppTweaks(APP_TWEAK_DEFAULTS);

ReactDOM.createRoot(document.getElementById("tweaks-root")).render(<AppTweaks />);
