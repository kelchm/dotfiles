// Generates a T3 Code theme file for One Dark Pro Darker.
// Sources of truth:
//   ~/.config/ghostty/themes/One Dark Pro Darker  (terminal colors, verbatim)
//   zhuangtongfa.material-theme OneDark-Pro-darker.json  (workbench colors)
//   classic One Dark syntax palette (accent + action voices)

// ---- One Dark Pro Darker source palette ------------------------------------
const P = {
  // Surface ladder, darkest to lightest. Every value is a real One Dark color.
  deepest: "#181a1f", // tab.border / editorGroup.border
  // One Dark's own sideBar.background (#1e2227) sits only ~5/255 below the
  // canvas, and T3 Code's grain overlay closes even that, erasing the sidebar
  // edge. peekViewEditor.background is the next real One Dark step down.
  sidebar: "#1b1d23", // peekViewEditor.background
  canvas: "#23272e", // editor.background + ghostty background
  raised: "#282c34", // One Dark Pro's own editor background
  hover: "#2c313a", // list.hoverBackground / list.activeSelectionBackground
  selected: "#323842", // list.inactiveSelectionBackground
  border: "#3e4452", // focusBorder / panel.border
  borderStrong: "#4b5263", // classic One Dark gutter/edge gray

  // Three text tiers. `editorText` is One Dark's editor foreground: correct
  // inside code and the terminal, where syntax color carries the contrast, but
  // far too dim for prose UI chrome, so it serves as the SECONDARY tier here
  // and `uiText` (One Dark's own bright UI foreground) leads.
  uiText: "#d7dae0", // activityBar.foreground / list.activeSelectionForeground
  editorText: "#abb2bf", // editor.foreground + ghostty foreground
  textMuted: "#9da5b4", // statusBar.foreground / titleBar.activeForeground
  comment: "#7f848e", // classic One Dark comment gray

  blue: "#61afef", // textLink.foreground - the One Dark accent
  // No second "action voice" here. T3 Code maps `messageAction` onto its
  // global `--primary` (index.css), so a companion hue would repaint every
  // primary button across ~31 files. One Dark has a single interactive color,
  // and One Dark's purple (#c678dd) is a syntax color for keywords, not UI --
  // as `--primary` it reads pink against these blue-gray surfaces.
  red: "#e06c75", // classic One Dark red
  orange: "#d19a66", // editorWarning.foreground

  // Verbatim from the ghostty theme file.
  termBg: "#23272e",
  termFg: "#abb2bf",
  termCursor: "#d0d1d3",
  termSelection: "#3d4149",
  termScrollbar: "#4e5666", // scrollbarSlider.background, alpha flattened
  termScrollbarHover: "#5a6375", // scrollbarSlider.hoverBackground, flattened
};

// ---- color math ------------------------------------------------------------
const rgb = (hex) => ({
  r: parseInt(hex.slice(1, 3), 16),
  g: parseInt(hex.slice(3, 5), 16),
  b: parseInt(hex.slice(5, 7), 16),
});
const hex = ({ r, g, b }) =>
  "#" +
  [r, g, b].map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, "0")).join("");
const mix = (a, b, t) => {
  const [x, y] = [rgb(a), rgb(b)];
  return hex({ r: x.r + (y.r - x.r) * t, g: x.g + (y.g - x.g) * t, b: x.b + (y.b - x.b) * t });
};
const luminance = (c) => {
  const ch = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const { r, g, b } = rgb(c);
  return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b);
};
const contrast = (a, b) => {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};

// Status surfaces: the signal color laid over the canvas at 16%, matching how
// T3 Code derives them for dark themes.
const surfaceOf = (signal) => mix(P.canvas, signal, 0.16);

// ---- role mapping ----------------------------------------------------------
const colors = {
  canvas: P.canvas,
  // The workspace header belongs to the main panel, so it shares the canvas.
  chrome: P.canvas,
  toolbar: P.canvas,
  toolbarForeground: P.uiText,
  toolbarBorder: P.deepest,
  toolbarControl: P.hover,
  toolbarControlForeground: P.uiText,
  toolbarControlHover: P.selected,

  surface: P.raised,
  surfaceRaised: P.hover,
  surfaceOverlay: P.selected,

  text: P.uiText,
  textMuted: P.editorText,
  border: P.border,
  input: P.borderStrong,
  focus: P.blue,

  accent: P.blue,
  accentForeground: P.canvas,
  secondary: P.selected,
  secondaryForeground: P.uiText,
  muted: P.hover,
  mutedForeground: P.editorText,
  // Placeholders stay on the dimmest tier -- they should recede.
  placeholder: P.textMuted,
  secondaryLabel: P.editorText,
  iconMuted: P.editorText,

  error: P.red,
  // The signal red on its own dark surface lands just under AA, so the text
  // role is the same red lifted toward white. `error` itself stays canonical.
  errorForeground: mix(P.red, "#ffffff", 0.2),
  errorSurface: surfaceOf(P.red),
  warning: P.orange,
  warningForeground: P.orange,
  warningSurface: surfaceOf(P.orange),
  update: P.blue,
  updateForeground: P.blue,
  updateSurface: surfaceOf(P.blue),

  accentSurface: P.hover,
  accentSurfaceForeground: P.uiText,
  messageSurface: P.raised,
  messageForeground: P.uiText,
  messageAction: P.blue,
  messageActionForeground: P.canvas,
  // The action button carries dark text, so hover brightens rather than
  // darkens -- the same direction T3 Code's own generator picks.
  messageActionHover: mix(P.blue, "#ffffff", 0.12),

  codeBackground: P.raised,
  // Code keeps One Dark's editor foreground: this is the one place the dimmer
  // value is right, because syntax highlighting supplies the contrast.
  codeForeground: P.editorText,

  sidebar: P.sidebar,
  sidebarForeground: P.uiText,
  sidebarMutedForeground: P.editorText,
  sidebarControlSurface: P.hover,
  sidebarRowHover: P.canvas,
  sidebarRowActive: P.hover,
  sidebarRowSelected: P.selected,
  sidebarBorder: P.deepest,

  terminalBackground: P.termBg,
  terminalForeground: P.termFg,
  terminalCursor: P.termCursor,
  terminalSelection: P.termSelection,
  terminalScrollbar: P.termScrollbar,
  terminalScrollbarHover: P.termScrollbarHover,
};

// ---- contrast validation ---------------------------------------------------
// Body text targets AA (4.5); large/secondary UI text targets 3.0.
const checks = [
  ["text on canvas", colors.text, colors.canvas, 4.5],
  ["text on surface", colors.text, colors.surface, 4.5],
  ["text on surfaceRaised", colors.text, colors.surfaceRaised, 4.5],
  ["text on surfaceOverlay", colors.text, colors.surfaceOverlay, 4.5],
  ["textMuted on canvas", colors.textMuted, colors.canvas, 4.5],
  ["mutedForeground on muted", colors.mutedForeground, colors.muted, 4.5],
  ["placeholder on surfaceRaised", colors.placeholder, colors.surfaceRaised, 4.5],
  ["toolbarForeground on toolbar", colors.toolbarForeground, colors.toolbar, 4.5],
  ["toolbarControlFg on control", colors.toolbarControlForeground, colors.toolbarControl, 4.5],
  ["sidebarForeground on sidebar", colors.sidebarForeground, colors.sidebar, 4.5],
  ["sidebarMutedFg on sidebar", colors.sidebarMutedForeground, colors.sidebar, 4.5],
  ["sidebarFg on rowSelected", colors.sidebarForeground, colors.sidebarRowSelected, 4.5],
  ["secondaryForeground on secondary", colors.secondaryForeground, colors.secondary, 4.5],
  ["accentSurfaceFg on accentSurface", colors.accentSurfaceForeground, colors.accentSurface, 4.5],
  ["messageForeground on messageSurface", colors.messageForeground, colors.messageSurface, 4.5],
  ["codeForeground on codeBackground", colors.codeForeground, colors.codeBackground, 4.5],
  ["accentForeground on accent", colors.accentForeground, colors.accent, 4.5],
  ["messageActionFg on messageAction", colors.messageActionForeground, colors.messageAction, 4.5],
  ["messageActionFg on hover", colors.messageActionForeground, colors.messageActionHover, 4.5],
  ["errorForeground on errorSurface", colors.errorForeground, colors.errorSurface, 4.5],
  ["warningForeground on warningSurface", colors.warningForeground, colors.warningSurface, 4.5],
  ["updateForeground on updateSurface", colors.updateForeground, colors.updateSurface, 4.5],
  ["error on canvas", colors.error, colors.canvas, 4.5],
  ["warning on canvas", colors.warning, colors.canvas, 4.5],
  ["terminalFg on terminalBg", colors.terminalForeground, colors.terminalBackground, 4.5],
  ["terminalCursor on terminalBg", colors.terminalCursor, colors.terminalBackground, 3.0],
  ["accent on canvas", colors.accent, colors.canvas, 3.0],
  ["focus on canvas", colors.focus, colors.canvas, 3.0],
  ["border on canvas", colors.border, colors.canvas, 1.2],
  ["input on canvas", colors.input, colors.canvas, 1.2],
];

// Hierarchy checks: the first pass shipped text at 7.0 and textMuted at 6.0,
// which is technically accessible but visually flat. Tiers must be distinct.
const hierarchy = [
  ["text is clearly brighter than textMuted", contrast(colors.text, colors.canvas) / contrast(colors.textMuted, colors.canvas) >= 1.35],
  ["textMuted is clearly brighter than placeholder", contrast(colors.textMuted, colors.canvas) / contrast(colors.placeholder, colors.canvas) >= 1.1],
  ["sidebar is visibly darker than canvas", luminance(colors.canvas) / luminance(colors.sidebar) >= 1.3],
  // T3 Code maps messageAction onto its global --primary (index.css:1107), so
  // it repaints primary buttons app-wide. One Dark has a single interactive
  // color; a second hue here reads as an unrelated accent.
  ["messageAction matches the accent (single interactive color)", colors.messageAction === colors.accent],
];

// Diagnostics go to stderr so stdout stays a clean JSON stream for
// `node build-onedark-theme.mjs > one-dark-pro-darker.json`.
let failed = 0;
console.error("hierarchy checks:");
for (const [label, ok] of hierarchy) {
  if (!ok) failed += 1;
  console.error(`  ${ok ? "PASS" : "FAIL"}  ${label}`);
}
console.error("\ncontrast checks:");
for (const [label, fg, bg, min] of checks) {
  const ratio = contrast(fg, bg);
  const ok = ratio >= min;
  if (!ok) failed += 1;
  console.error(`  ${ok ? "PASS" : "FAIL"}  ${ratio.toFixed(2)} (min ${min})  ${label}`);
}
if (failed > 0) {
  console.error(`\n${failed} CHECK(S) FAILED — no theme emitted`);
  process.exit(1);
}
console.error("\nall checks passed");

// ---- emit ------------------------------------------------------------------
const theme = {
  version: 1,
  id: "one-dark-pro-darker",
  name: "One Dark Pro Darker",
  appearance: "dark",
  colors,
};
console.error(`\nroles: ${Object.keys(colors).length}`);
process.stdout.write(JSON.stringify(theme, null, 2) + "\n");
