// Applies app.settings.json to the native projects before `cap sync`:
//  - www/app-settings.js (where the offline screen goes back to)
//  - Android versionCode / versionName
//  - iPhone MARKETING_VERSION / CURRENT_PROJECT_VERSION
import { existsSync, readFileSync, writeFileSync } from "node:fs";

const root = new URL("../", import.meta.url);
const s = JSON.parse(readFileSync(new URL("app.settings.json", root)));
const url = s.devUrl || s.siteUrl;

writeFileSync(new URL("www/app-settings.js", root),
  `window.ATTENDPRO = ${JSON.stringify({ url, name: s.appName, version: s.version })};\n`);

const gradle = new URL("android/app/build.gradle", root);
if (existsSync(gradle)) {
  let g = readFileSync(gradle, "utf8");
  g = g.replace(/versionCode \d+/, `versionCode ${s.build}`).replace(/versionName "[^"]*"/, `versionName "${s.version}"`);
  writeFileSync(gradle, g);
}
const pbx = new URL("ios/App/App.xcodeproj/project.pbxproj", root);
if (existsSync(pbx)) {
  let p = readFileSync(pbx, "utf8");
  p = p.replace(/MARKETING_VERSION = [^;]+;/g, `MARKETING_VERSION = ${s.version};`)
       .replace(/CURRENT_PROJECT_VERSION = [^;]+;/g, `CURRENT_PROJECT_VERSION = ${s.build};`);
  writeFileSync(pbx, p);
}
console.log(`AttendPro ${s.version} (build ${s.build}) → ${url}${s.devUrl ? "  [TEST BUILD: devUrl is set]" : ""}`);
