import { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.zopedia.client",
  appName: "Zopedia Client",
  webDir: "dist-client",
  server: {
    androidScheme: "https",
  },
  ios: {
    // "never" = don't let iOS natively inset the scrollview for safe areas.
    // We handle safe areas in CSS (env(safe-area-inset-*) padding on the
    // navbar/topbar/composer), so native inset would double-handle them and
    // create scrollable black bars at the notch / home indicator.
    contentInset: "never",
  },
};

export default config;
