# Configuring the private bridge connection

The Rose Garden Bridge **Umbrel app must NOT use the host Docker socket** or the Lightning Fork node's administrator macaroon. The app's only required bridge operations are `Info` and `Quote` (and optionally `LookupSwap` later).

## Pending live setup verification

The live installation previously ran:

- Paulscode BLAKE2BTC LND container: `paulscode-lightning-fork_lnd_1`
- `lncli --lnddir=/data/.lnd --rpcserver=127.0.0.1:10010 bridge quote <invoice>`
- LND REST server was configured on container port `8180`, but **access from a separate Umbrel app has not been verified**.

In the Paulscode backend source, restricted participants are permitted RPC methods:

```
/bridgerpc.Bridge/Info
/bridgerpc.Bridge/Quote
/bridgerpc.Bridge/LookupSwap
```

The REST companion endpoints used by its existing UI include `GET /v2/bridge/info` and `POST /v2/bridge/quote` with JSON body `{"invoice":"lnbc..."}`. The new client code uses those routes over verified HTTPS. A successful live restricted-macaroon test is still required to validate its precise response encoding in this version.

## Obtain limited credentials WITHOUT posting them

1. In the Umbrel terminal (not on a public server), inspect the built-in CLI help:

   ```bash
   sudo docker exec paulscode-lightning-fork_lnd_1 \
     lncli --lnddir=/data/.lnd --rpcserver=127.0.0.1:10010 \
     bridge code --help
   ```

2. Follow the documented participant-code creation steps *for your installed version*. Use only a limited participant credential, never an admin macaroon.
3. Determine how that **participant code** maps to a limited macaroon and the trusted Lightning Fork TLS certificate. This decoding/provisioning is **not yet implemented**; verify the format locally before continuing.
4. Copy the binary restricted macaroon into the app-specific private directory as `participant.macaroon`, and the LND TLS PEM certificate as `tls.cert`. Store them with permissions readable only by the app's UID 1000, never in the Git repository or uploaded chat messages. Do not copy a full LND data directory.
5. Verify the REST hostname/port and the TLS certificate's subject alternative names match. Do not use insecure TLS skips or `curl -k` as a fix.
6. If the verified REST address differs from `https://10.21.21.66:8180`, update `ROSE_BRIDGE_REST_URL` in `rosegarden-bridge/docker-compose.yml`, commit, and update the installed app. Prefer a stable private network name/alias over a changing Docker IP.

## Important access caveat

The default service uses an internal IP from a prior diagnostic (`10.21.21.66`). Reachability depends on Umbrel's Docker networking. Access from the new app container and SAN validation must both be checked. These were NOT tested in the developer container.

## Payments

The `lncli bridge quote` path and the `/v2/bridge/quote` HTTP path reserve bridge liquidity temporarily. They do not pay the hold invoice. The send-side wallet (for example Start9 SHA256BTC LND) must pay the corresponding hold invoice and verify settlement.

The service’s quote expires in roughly one minute by default; we have **not** changed expiry settings. Do not pay an expired quote. Do not retry a failed/ambiguous payment until reconciled.

Optional direct Start9 payment is deliberately **disabled** in the Umbrel compose. Before enabling, use a payment-limited LND macaroon, authenticated TLS, per-swap user consent, fee ceiling, and test settlement. Public service mode requires a separate security review.
