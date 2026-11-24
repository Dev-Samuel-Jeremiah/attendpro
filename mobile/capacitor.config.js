/*
 * Capacitor configuration for the AttendPro Android and iPhone apps.
 * Normally you change app.settings.json, not this file, then run `npx cap sync`.
 *
 * How the app works: it opens the live site (settings.siteUrl) in a full-screen native web view
 * and adds phone features through static/js/app-bridge.js on the website. Every change you
 * deploy to attendpro.cloud appears in the apps straight away; no reinstall or store update.
 */
const settings = require("./app.settings.json");

// devUrl (e.g. http://10.0.2.2:8799/app/) points a test build at your own computer.
const devUrl = (settings.devUrl || "").replace(/\/+$/, "/");
const url = devUrl || settings.siteUrl;
const devHost = devUrl ? new URL(devUrl).hostname : null;
const release = process.env.ATTENDPRO_RELEASE === "1";

/** @type {import('@capacitor/cli').CapacitorConfig} */
module.exports = {
  appId: settings.appId,
  appName: settings.appName,
  webDir: "www",                         // loading + offline screens shipped inside the app

  server: {
    url,
    errorPath: "offline.html",
    allowNavigation: [...settings.appHosts, ...settings.paymentHosts, ...(devHost ? [devHost] : [])],
    cleartext: Boolean(devUrl),
  },

  android: {
    appendUserAgent: "AttendProApp/android",
    allowMixedContent: Boolean(devUrl),
    captureInput: true,
    webContentsDebuggingEnabled: !release,
    adjustMarginsForEdgeToEdge: "auto",
    backgroundColor: settings.colors.brand,
  },

  ios: {
    appendUserAgent: "AttendProApp/ios",
    contentInset: "never",               // the site handles the notch itself (env(safe-area-inset-*))
    backgroundColor: settings.colors.brand,
    limitsNavigationsToAppBoundDomains: false,
    webContentsDebuggingEnabled: !release,
    scrollEnabled: true,
  },

  plugins: {
    SplashScreen: {
      launchShowDuration: Math.round(settings.splashSeconds * 1000),
      launchAutoHide: true,
      backgroundColor: settings.colors.splashBackground,
      androidScaleType: "CENTER_INSIDE",
      showSpinner: false,
      splashFullScreen: false,
      splashImmersive: false,
    },
    StatusBar: {
      overlaysWebView: false,
      style: "DARK",                     // light text on the navy bar
      backgroundColor: settings.colors.statusBar,
    },
  },
};
