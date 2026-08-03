# Dev-client workflow (iterate without spending EAS build credits)

EAS cloud builds are quota-limited. A **dev client** is built **once**, then every
JS/UI change loads live over Metro — zero further builds. Only a native change
(new native module, `app.json` native config, SDK bump) needs a rebuild.

## One-time: build + install the dev client

Pick ONE. Both install the same dev-client app.

- **Local (0 cloud builds)** — needs a JDK + Android SDK on the Mac:
  ```bash
  brew install openjdk@17
  export JAVA_HOME=$(/usr/libexec/java_home -v 17)   # add to ~/.zshrc
  export ANDROID_HOME=$HOME/Library/Android/sdk       # add to ~/.zshrc
  cd mobile && npm run build:devclient:android:local
  ```
  Then install the produced `.apk` on the device (`adb install <path>` or copy it over).

- **Cloud (1 build)** — no local toolchain needed:
  ```bash
  cd mobile && npm run build:devclient:android      # → APK link, install on device
  ```

(iOS simulator dev client: `npm run build:devclient:ios-sim`.)

## Daily loop (no builds)

1. Backend up on the Mac: `cd backend && make dev` (listens on `:8000`).
2. Point the app at the Mac. `mobile/.env.development` holds
   `EXPO_PUBLIC_BACKEND_URL` — set it to the Mac's LAN IP (same-WiFi) e.g.
   `http://192.168.1.3:8000` (this Mac, may change — check `ipconfig getifaddr en0`),
   or the HTTPS cloudflared tunnel URL for any network. Dev builds allow cleartext
   HTTP, so a LAN IP is fine.
3. Start Metro in dev-client mode:
   - Same WiFi:  `npm run start:dev`         (LAN)
   - Any network: `npm run start:dev:tunnel`  (routes Metro through a tunnel)
4. Open the **dev-client app** on the device and connect to the running Metro
   (scan the QR or pick the LAN URL). Edit JS → it hot-reloads. No rebuild.

## When you DO need a new build

- Added/removed a native module or changed native config in `app.json`
  (permissions, `infoPlist`, `usesCleartextTraffic`, icons/splash).
- Bumped the Expo SDK or a package with native code.
JS-only changes (screens, components, styles, API clients) never need a rebuild.
