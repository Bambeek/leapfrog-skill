#!/usr/bin/env node
// Draft design tokens from a public page's computed CSS. No screenshots.
//
//   node extract_tokens.mjs https://app.example/pricing [more urls] --out leapfrog/design
//
// Needs Playwright in the project: npm i -D playwright && npx playwright install chromium
// Writes tokens.json (roles, type scale, spacing, radius, shadow, pairs) and
// raw-styles.json (the counts behind it). Values are a draft: brand colours
// are replaced in leapfrog-ship and licensed fonts become open ones.

import { createRequire } from "node:module";
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const urls = args.filter((a, i) => !a.startsWith("--") && args[i - 1] !== "--out");
const out = args.includes("--out") ? args[args.indexOf("--out") + 1] : "leapfrog/design";
const mobile = args.includes("--mobile");
if (!urls.length) {
  console.error("usage: extract_tokens.mjs URL [URL...] [--out DIR] [--mobile]");
  process.exit(2);
}

function loadPlaywright() {
  const req = createRequire(join(process.cwd(), "noop.js"));
  for (const name of ["playwright", "@playwright/test"]) {
    try { return req(name); } catch (e) { /* try next */ }
  }
  console.error("Playwright not found in this project: npm i -D playwright && npx playwright install chromium");
  process.exit(2);
}

// Runs in the page. Collects weighted counts of computed values.
function collect() {
  const add = (m, k, w = 1) => { if (k) m[k] = (m[k] || 0) + w; };
  const r = { text: {}, bg: {}, border: {}, input: {}, accentBg: {}, accentText: {}, onAccent: {},
    font: {}, size: {}, leading: {}, weight: {}, space: {}, radius: {}, shadow: {} };
  const transparent = (c) => !c || c === "transparent" || /rgba\(.*,\s*0\)$/.test(c);
  const root = getComputedStyle(document.body);
  r.body = transparent(root.backgroundColor) ? getComputedStyle(document.documentElement).backgroundColor : root.backgroundColor;
  const els = Array.from(document.querySelectorAll("body *")).slice(0, 5000);
  for (const el of els) {
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || +s.opacity === 0) continue;
    const box = el.getBoundingClientRect();
    if (box.width < 1 || box.height < 1) continue;
    const own = Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join("").length;
    const tag = el.tagName.toLowerCase();
    if (own) {
      add(r.text, s.color, own);
      add(r.font, s.fontFamily, own);
      add(r.size, s.fontSize, own);
      add(r.weight, s.fontWeight, own);
      add(r.leading, s.fontSize + "|" + s.lineHeight, own);
    }
    if (!transparent(s.backgroundColor)) add(r.bg, s.backgroundColor, Math.min(box.width * box.height, 2e5));
    if (parseFloat(s.borderTopWidth) > 0 && !transparent(s.borderTopColor)) {
      add(["input", "select", "textarea"].includes(tag) ? r.input : r.border, s.borderTopColor);
    }
    const clickable = tag === "button" || tag === "a" || el.getAttribute("role") === "button";
    if (clickable) {
      if (!transparent(s.backgroundColor)) { add(r.accentBg, s.backgroundColor); add(r.onAccent, s.backgroundColor + "|" + s.color); }
      else add(r.accentText, s.color);
    }
    for (const p of ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "marginTop", "marginBottom", "rowGap", "columnGap"]) {
      const v = parseFloat(s[p]);
      if (v > 0 && v <= 128) add(r.space, String(Math.round(v)));
    }
    const rad = parseFloat(s.borderTopLeftRadius);
    if (rad > 0) add(r.radius, String(Math.min(Math.round(rad), 9999)));
    if (s.boxShadow && s.boxShadow !== "none") add(r.shadow, s.boxShadow);
  }
  return r;
}

const merge = (a, b) => { for (const [k, v] of Object.entries(b)) a[k] = (a[k] || 0) + v; return a; };
const top = (m, n = 1) => Object.entries(m).sort((x, y) => y[1] - x[1]).slice(0, n).map((e) => e[0]);

function rgb(c) {
  const m = (c || "").match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  return m ? [+m[1], +m[2], +m[3]] : null;
}
function hex(c) {
  const v = rgb(c);
  return v ? "#" + v.map((x) => x.toString(16).padStart(2, "0")).join("") : null;
}
function sat(c) {
  const v = rgb(c);
  if (!v) return 0;
  const mx = Math.max(...v) / 255, mn = Math.min(...v) / 255;
  return mx === 0 ? 0 : (mx - mn) / mx;
}
function lum(c) {
  const v = rgb(c).map((x) => { x /= 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}

const { chromium } = loadPlaywright();
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 } });
const raw = { text: {}, bg: {}, border: {}, input: {}, accentBg: {}, accentText: {}, onAccent: {},
  font: {}, size: {}, leading: {}, weight: {}, space: {}, radius: {}, shadow: {}, body: {} };
for (const url of urls) {
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  } catch (e) {
    await page.goto(url, { waitUntil: "load", timeout: 30000 });
  }
  const r = await page.evaluate(collect);
  for (const k of Object.keys(raw)) if (k !== "body") merge(raw[k], r[k]);
  raw.body[r.body] = (raw.body[r.body] || 0) + 1;
}
await browser.close();

const template = JSON.parse(readFileSync(join(here, "templates", "tokens.json"), "utf8"));
const color = { ...template.color };
const bg = top(raw.body)[0] || "rgb(255, 255, 255)";
color.bg = hex(bg) || color.bg;
const greys = (m) => top(m, 20).filter((c) => sat(c) < 0.2 && hex(c));
color.surface = hex(greys(raw.bg).find((c) => hex(c) !== color.bg)) || color.surface;
const texts = top(raw.text, 10).filter((c) => hex(c));
color.text = hex(texts[0]) || color.text;
color["text-muted"] = hex(texts.find((c) => hex(c) !== color.text && sat(c) < 0.25)) || color["text-muted"];
color.border = hex(top(raw.border)[0]) || color.border;
color["border-input"] = hex(top(raw.input)[0]) || color["border-input"];
const accent = top(raw.accentBg, 10).find((c) => sat(c) > 0.35) || top(raw.accentText, 10).find((c) => sat(c) > 0.35);
if (accent) {
  color.accent = hex(accent);
  const pair = top(raw.onAccent, 20).find((p) => p.startsWith(accent + "|"));
  color["on-accent"] = pair ? hex(pair.split("|")[1]) : (lum(accent) > 0.4 ? "#000000" : "#ffffff");
}

const sizes = top(raw.size, 7).map((s) => parseFloat(s)).filter((v) => v > 0).sort((a, b) => a - b);
const names = ["xs", "sm", "md", "lg", "xl", "2xl", "3xl"];
const text = {};
sizes.forEach((px, i) => {
  const lh = top(Object.fromEntries(Object.entries(raw.leading).filter(([k]) => parseFloat(k) === px)))[0];
  const l = lh ? parseFloat(lh.split("|")[1]) : NaN;
  text[names[i]] = [Math.round(px), Number.isFinite(l) ? Math.round(l) : Math.round(px * 1.4)];
});

const spaceVals = Object.entries(raw.space).map(([k, v]) => [+k, v]);
const total = spaceVals.reduce((s, [, v]) => s + v, 0) || 1;
const share = (b) => spaceVals.filter(([k]) => k % b === 0).reduce((s, [, v]) => s + v, 0) / total;
const base = share(8) >= 0.6 ? 8 : 4;
const scale = [0, ...new Set(top(raw.space, 30).map((k) => Math.max(base, Math.round(+k / base) * base)))]
  .slice(0, 10).sort((a, b) => a - b);

const radii = top(raw.radius, 3).map(Number).sort((a, b) => a - b);
const radius = {};
radii.forEach((v, i) => { radius[["sm", "md", "lg"][i]] = v; });
const shadows = top(raw.shadow, 2);
const shadow = {};
shadows.forEach((v, i) => { shadow[["sm", "md"][i]] = v; });

const fontFamily = top(raw.font)[0] || template.font.sans;
const tokens = {
  _source: { urls, read: new Date().toISOString().slice(0, 10), font_seen: fontFamily,
    note: "Draft from computed CSS. Replace the brand colour and any licensed font before launch." },
  color,
  font: { ...template.font },
  text: Object.keys(text).length ? text : template.text,
  weight: top(raw.weight, 3).map(Number).sort((a, b) => a - b),
  space: { base, scale: scale.length > 3 ? scale : template.space.scale },
  radius: Object.keys(radius).length ? radius : template.radius,
  shadow: Object.keys(shadow).length ? shadow : template.shadow,
  pairs: template.pairs,
};

mkdirSync(out, { recursive: true });
writeFileSync(join(out, "tokens.json"), JSON.stringify(tokens, null, 2) + "\n");
writeFileSync(join(out, "raw-styles.json"), JSON.stringify(raw, null, 1) + "\n");
console.log(`tokens from ${urls.length} page(s) -> ${join(out, "tokens.json")}`);
console.log(`  bg ${color.bg}  surface ${color.surface}  text ${color.text}  muted ${color["text-muted"]}  accent ${color.accent}`);
console.log(`  type ${Object.values(tokens.text).map((t) => t[0]).join("/")}px  space base ${base}  radius ${radii.join("/") || "-"}`);
console.log(`  font seen: ${fontFamily.split(",")[0]} (pick an open font for the same job)`);
