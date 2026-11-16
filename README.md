# Rose Garden — Umbrel Community App Store

Owner: [18650Engineer](https://github.com/18650Engineer)  
App store ID: `rosegarden`  
App ID: `rosegarden-bridge`  
Application labels: **SHA256BTC ↔ BLAKE2BTC**

This repository contains an **Umbrel Community App Store package** and the source code for the **Rose Garden Bridge** private web interface. The app **does not replace** Paulscode's Lightning Fork daemon or run a Bitcoin node. It requests quotes from an existing Lightning Fork bridge, displays the short-lived hold invoice, and lets the user pay it from an independent Lightning wallet.

> **Status: ALPHA / staged release.** The application code and manifest are prepared, but this repository and its Docker image have not been published to GitHub from this environment, and the network connection to your live Lightning Fork daemon has not been tested from the new app container. Quotes will not work until a restricted bridge participant credential and trusted TLS certificate are provisioned.

## Publish from the owner's Mac

1. On GitHub while signed in as `18650Engineer`, create a **new public empty repository** named `rosegarden-umbrel-app-store` (no generated README/license). Do not add wallet credentials to GitHub.
2. Extract the supplied `rosegarden-umbrel-app-store.zip` on your Mac.
3. Open Terminal **in the extracted `rosegarden-umbrel-app-store` folder** and run:

   ```bash
   git init
   git branch -M main
   git add .
   git commit -m "Initial Rose Garden Umbrel Community App Store"
   git remote add origin https://github.com/18650Engineer/rosegarden-umbrel-app-store.git
   git push -u origin main
   ```

   GitHub will request supported credentials (or SSH), not an account password.
4. Under the repository's **Actions** tab, allow the `Build and publish Rose Garden Bridge` workflow to run. It builds `ghcr.io/18650engineer/rosegarden-bridge:0.1.0` for x86_64 Umbrel systems.
5. Under the repository's **Packages** (GHCR) settings, confirm that `rosegarden-bridge` is **public**, otherwise Umbrel cannot pull its image unauthenticated. The image does not contain macaroons or wallet credentials.
6. For a production release, pin the image in `rosegarden-bridge/docker-compose.yml` by its published digest. After testing and updating the package version, republish.

## Add the store to Umbrel

After the GitHub repository and container image are published:

1. On Umbrel, open **App Store → ⋯ → Community App Stores → Add**.
2. Enter:

   `https://github.com/18650Engineer/rosegarden-umbrel-app-store`

3. Open the **Rose Garden** store and install **Rose Garden Bridge**.
4. Open the app. The interface should load even before the restricted bridge connection is configured, but live quotes will display a configuration error until then.

## Bridge connection (required)

Read [Bridge connection and security](docs/BRIDGE_CONNECTION.md) **before requesting live quotes**. Do not mount `/var/run/docker.sock`, `admin.macaroon`, seed files, or entire LND data directories in the app. The original local prototype used `docker exec`, but a native Umbrel app must use a **restricted participant API** over authenticated TLS instead.

The compose file currently defaults to the address from the user's previous LND process output, `https://10.21.21.66:8180`. **Verify this exact REST address and certificate on your actual installation**; container IPs can change. Put the restricted credentials under the app's private `data/bridge` folder, where the app sees them read-only.

`lncli bridge code --help` on the Paulscode BLAKE2BTC container documents creating a bridge participant credential. The complete structure of its bridge code (and safe extraction into separate TLS/macaroon files) **has not yet been validated on this installed daemon**. Do not use the admin macaroon as a shortcut. Inspect that CLI output locally before provisioning the app.

## Capabilities and limits

- SHA256BTC → BLAKE2BTC and BLAKE2BTC → SHA256BTC quotes, subject to bridge liquidity.
- Live exchange spread, amount, expiration countdown and one-click hold invoice copying.
- Umbrel App Proxy authentication remains on; **no direct public port is mapped**.
- Configured quote caps: 10,000 SHA256BTC sats and 5,000,000 BLAKE2BTC sats per swap.
- Optional Start9 LND payment integration exists in source but is **off in the Umbrel compose file**. No automatic payment is initiated by installation or by requesting a quote.
- Quotes are not payments. Actual settlement must be verified using both Lightning wallet histories.
- Bridge quote expiry is unchanged. See [Security notes](docs/BRIDGE_CONNECTION.md).

## Develop and test

```bash
python3 -m unittest discover -s app/tests -v
cd app && python3 server.py
# Local CLI mode is available in this non-container developer setup if Docker and lncli are installed.
```

No Python dependencies beyond the standard library are required. The GHCR image uses Python 3.13 Alpine. Do not deploy the development server directly to the public internet.

## Relevant upstream documentation

- [Umbrel Community App Store template](https://github.com/getumbrel/umbrel-community-app-store)
- [Umbrel: adding a community app store](https://umbrel.com/support/apps/how-to-add-a-community-app-store)
- [Paulscode Lightning Fork](https://github.com/paulscode/lightning-fork)


## v0.1.1-alpha status display fix

The participant-only Bridge `Info` endpoint returns `directions` as objects
(`name`, `open`, `refusal`), not as a list of direction strings. v0.1.1
normalizes both response styles, filters unavailable directions, and labels
restricted operator-only metrics honestly. No wallet permissions change.

After updating files in this Git repository, push to `main` and verify the
`Build and publish Rose Garden Bridge` GitHub Action succeeds. The Umbrel
app manifest and Docker image tag both move to `0.1.1`. Install the app
update from Umbrel's App Store; do not uninstall the app or remove its
persistent `data/bridge` credential directory.


## v0.1.2-alpha — BOLT11 invoice input fix

The previous validator incorrectly rejected the mandatory BOLT11 `1` separator.
The fixed validator accepts correctly shaped uppercase and lowercase `lnbc`
invoices and delegates cryptographic validation to Lightning Fork.
Automatic payments remain disabled. After publishing the update, upgrade the
installed application from Umbrel without uninstalling it; this preserves
`data/bridge` credentials.
