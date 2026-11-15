#!/usr/bin/env python3
"""Rose Garden Bridge: private UI for Paulscode Lightning Fork participant quotes.

Umbrel app mode talks only to the limited Bridge REST API over verified TLS.
Local CLI mode remains available for tests and non-Umbrel development.
Never give this container the Docker socket or an LND admin macaroon.
"""
import base64
import hashlib
import http.client
import json
import os
import re
import secrets
import ssl
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'static'
PORT = int(os.environ.get('ROSE_PORT', '8765'))
HOST = os.environ.get('ROSE_HOST', '127.0.0.1')
TRUST_PROXY = os.environ.get('ROSE_TRUST_PROXY') == '1'
BACKEND = os.environ.get('ROSE_BRIDGE_BACKEND', 'cli').lower()
REST_URL = os.environ.get('ROSE_BRIDGE_REST_URL', '').rstrip('/')
REST_CERT = os.environ.get('ROSE_BRIDGE_TLS_CERT', '')
REST_MACAROON = os.environ.get('ROSE_BRIDGE_MACAROON', '')
CONTAINER = os.environ.get('ROSE_BRIDGE_CONTAINER', 'paulscode-lightning-fork_lnd_1')
DOCKER = os.environ.get('ROSE_DOCKER', 'docker')
CLI = [DOCKER, 'exec', CONTAINER, 'lncli', '--lnddir=/data/.lnd',
       '--rpcserver=127.0.0.1:10010', 'bridge']
MAX_BTC_SAT = int(os.environ.get('ROSE_MAX_BTC_SAT', '10000'))
MAX_BLAKE_SAT = int(os.environ.get('ROSE_MAX_BLAKE_SAT', '5000000'))
FEE_LIMIT_SAT = int(os.environ.get('ROSE_BTC_ROUTING_FEE_LIMIT_SAT', '20'))
if MAX_BTC_SAT < 1 or MAX_BLAKE_SAT < 1 or FEE_LIMIT_SAT < 0:
    raise SystemExit('Invalid safety limits')

# Optional automatic payment; absent unless specifically configured by the owner.
START9_URL = os.environ.get('ROSE_START9_LND_URL', '').rstrip('/')
START9_CERT = os.environ.get('ROSE_START9_TLS_CERT', '')
START9_MACAROON = os.environ.get('ROSE_START9_MACAROON', '')
START9_READY = all([START9_URL, START9_CERT, START9_MACAROON])

TOKEN = secrets.token_urlsafe(36)
QUOTES = {}  # ephemeral quotes, never written to disk
LOCK = threading.Lock()
INVOICE_RE = re.compile(r'^lnbc[023456789acdefghjklmnpqrstuvwxyz]+$', re.I)
HASH_RE = re.compile(r'^[0-9a-f]{64}$', re.I)


class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def normalized(data):
    """Support both LND gRPC JSON (snake_case) and REST (camelCase)."""
    if isinstance(data, dict) and isinstance(data.get('result'), dict):
        data = data['result']
    if not isinstance(data, dict):
        raise AppError('Unexpected Bridge REST response', 502)
    keys = {
        'holdInvoice': 'hold_invoice', 'incomingMsat': 'incoming_msat',
        'outgoingMsat': 'outgoing_msat', 'expiresAt': 'expires_at',
        'paymentHash': 'hash', 'swapsInFlight': 'swaps_in_flight',
        'needsOperator': 'needs_operator', 'sha256Node': 'sha256_node',
    }
    clean = {keys.get(k, k): v for k,v in data.items()}
    # The JSON gateway encodes protobuf bytes (including payment hash) as base64.
    if 'hash' in clean and isinstance(clean['hash'], str) and not HASH_RE.fullmatch(clean['hash']):
        try:
            decoded = base64.b64decode(clean['hash'], validate=True)
            if len(decoded) == 32:
                clean['hash'] = decoded.hex()
        except (ValueError, base64.binascii.Error):
            pass
    return clean


def bridge_rest(args, timeout=20):
    """Limited RPC via HTTP; no direct wallet, Docker, or shell access."""
    if not REST_URL or not REST_CERT or not REST_MACAROON:
        raise AppError('Bridge not configured. Provision a restricted participant macaroon and TLS certificate (see repository README).', 503)
    u = urlsplit(REST_URL)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment:
        raise AppError('Bridge REST URL must be https://host:port', 503)
    try:
        macaroon = Path(REST_MACAROON).read_bytes()
        if not 8 <= len(macaroon) <= 65536:
            raise AppError('Invalid bridge participant macaroon', 503)
        ctx = ssl.create_default_context(cafile=REST_CERT)
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, context=ctx, timeout=timeout)
        action = args[0] if args else ''
        if action == 'quote' and len(args) == 2:
            route, method, payload = '/v2/bridge/quote', 'POST', json.dumps({'invoice':args[1]}).encode()
        elif action == 'status' and len(args) == 1:
            route, method, payload = '/v2/bridge/info', 'GET', None
        else:
            raise AppError('Unsupported bridge operation', 400)
        headers = {'Grpc-Metadata-macaroon': macaroon.hex(), 'Accept':'application/json'}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        try:
            conn.request(method, route, body=payload, headers=headers)
            response = conn.getresponse()
            if response.length and response.length > 100000:
                raise AppError('Bridge reply too large', 502)
            raw = response.read(100001)
            if len(raw) > 100000:
                raise AppError('Bridge reply too large', 502)
            try:
                body = json.loads(raw)
            except ValueError:
                raise AppError('Bridge returned unreadable JSON', 502)
            if response.status != 200:
                # Do not print macaroon, invoices, or remote body verbatim.
                code = body.get('code','unknown') if isinstance(body,dict) else 'unknown'
                raise AppError(f'Bridge rejected {action} (HTTP {response.status}; code {str(code)[:30]})', 422 if response.status < 500 else 502)
            if isinstance(body,dict) and 'error' in body:
                raise AppError('Bridge returned a service error', 422)
            return normalized(body)
        finally:
            conn.close()
    except (OSError, ssl.SSLError, TimeoutError, ValueError) as exc:
        raise AppError('Bridge REST unavailable or TLS verification failed: ' + type(exc).__name__, 502)


def get_bridge(args, timeout=20):
    if BACKEND == 'rest':
        return bridge_rest(args, timeout)
    if BACKEND != 'cli':
        raise AppError('Unknown bridge backend',503)
    try:
        result = subprocess.run(CLI + args, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppError('Unable to reach the Umbrel Lightning Fork container: ' + type(exc).__name__, 502)
    if result.returncode != 0:
        reason = (result.stderr or result.stdout or 'Bridge refused this request').strip()
        reason = re.sub(r'lnbc[023456789acdefghjklmnpqrstuvwxyz]+', '[invoice]', reason, flags=re.I)
        raise AppError(reason[:400], 422)
    try:
        return normalized(json.loads(result.stdout))
    except json.JSONDecodeError:
        raise AppError('Bridge returned unreadable JSON', 502)


def validate_invoice(invoice):
    if not isinstance(invoice, str):
        raise AppError('Lightning invoice text required')
    invoice = invoice.strip().lower()
    if not 80 <= len(invoice) <= 3000 or not INVOICE_RE.fullmatch(invoice):
        raise AppError('Paste one complete BOLT11 lnbc Lightning invoice (no spaces)')
    return invoice


def prepare_quote(invoice, intended_direction):
    if intended_direction not in ('toBLAKE2b', 'toSHA256'):
        raise AppError('Unsupported direction')
    invoice = validate_invoice(invoice)
    # The same lnbc prefix is used on both chains. The bridge checks actual chain.
    raw = get_bridge(['quote', invoice])
    required = ['hold_invoice', 'hash', 'incoming_msat', 'outgoing_msat', 'expires_at', 'direction']
    if any(x not in raw for x in required):
        raise AppError('Incomplete response from bridge', 502)
    if raw['direction'] != intended_direction:
        raise AppError('Invoice belongs to the other network. Quote rejected.', 422)
    if not HASH_RE.fullmatch(str(raw['hash'])):
        raise AppError('Invalid bridge payment hash', 502)
    incoming_msat = int(raw['incoming_msat'])
    outgoing_msat = int(raw['outgoing_msat'])
    expires = int(raw['expires_at'])
    if incoming_msat < 1 or outgoing_msat < 1 or expires <= int(time.time()) + 3:
        raise AppError('Quote expired or has invalid amounts', 422)
    incoming_sats = incoming_msat / 1000
    outgoing_sats = outgoing_msat / 1000
    # Hard caps for either direction, including the payout leg.
    btc_sats = incoming_sats if intended_direction == 'toBLAKE2b' else outgoing_sats
    blake_sats = outgoing_sats if intended_direction == 'toBLAKE2b' else incoming_sats
    if btc_sats > MAX_BTC_SAT or blake_sats > MAX_BLAKE_SAT:
        raise AppError('Quote exceeds local safety limit; no payment initiated', 422)
    if not INVOICE_RE.fullmatch(raw['hold_invoice']):
        raise AppError('Bridge returned invalid hold invoice', 502)
    ident = secrets.token_urlsafe(20)
    item = {
        'id': ident, 'hash': raw['hash'].lower(), 'direction': raw['direction'],
        'expires_at': expires, 'created_at': int(time.time()),
        'incoming_msat': incoming_msat, 'outgoing_msat': outgoing_msat,
        'incoming_sats': incoming_sats, 'outgoing_sats': outgoing_sats,
        'rate': raw.get('rate'), 'spread': raw.get('spread'),
        'hold_invoice': raw['hold_invoice'].lower(),
        'payment_state': 'NOT_STARTED',
    }
    with LOCK:
        for key, old in list(QUOTES.items()):
            if old['created_at'] < time.time() - 3600:
                del QUOTES[key]
        QUOTES[ident] = item
    return public_item(item)


def public_item(item):
    # Invoice displayed intentionally in private UI; never log its full contents.
    return {key: item[key] for key in (
        'id','hash','direction','expires_at','incoming_sats','outgoing_sats',
        'rate','spread','hold_invoice','payment_state')}


def macaroon_hex():
    data = Path(START9_MACAROON).read_bytes()
    if len(data) > 65536:
        raise AppError('Invalid macaroon size', 500)
    return data.hex()


def start9_pay(item):
    """Optional payment: LND's official streaming REST endpoint, with verified TLS."""
    if not START9_READY:
        raise AppError('Start9 automatic payment is not configured. Copy invoice into Start9 instead.', 409)
    parsed = urlsplit(START9_URL)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query:
        raise AppError('Start9 REST URL must be https://host:port', 500)
    # Reject unverified certs: no insecure fallback.
    ctx = ssl.create_default_context(cafile=START9_CERT)
    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443,
                                       context=ctx, timeout=55)
    payload = json.dumps({
        'payment_request': item['hold_invoice'],
        'timeout_seconds': 45,
        'fee_limit_sat': str(FEE_LIMIT_SAT),
        'max_parts': 1,
        'no_inflight_updates': False,
    }).encode()
    try:
        conn.request('POST', '/v2/router/send', body=payload,
                     headers={'Content-Type':'application/json',
                              'Grpc-Metadata-macaroon': macaroon_hex()})
        response = conn.getresponse()
        if response.status != 200:
            raise AppError('Start9 returned HTTP ' + str(response.status) + '. Verify node and credentials.', 502)
        # LND REST streaming delivers newline-delimited JSON objects.
        # Never repeat a payment automatically when a response is ambiguous.
        final = {'status': 'UNKNOWN', 'payment_hash': item['hash']}
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            line = response.readline(1_000_000)
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if 'error' in message:
                raise AppError('Start9 payment response error (check Start9 payment history)', 502)
            p = message.get('result', message)
            if not isinstance(p, dict):
                continue
            got_hash = str(p.get('payment_hash','')).lower()
            if got_hash and got_hash != item['hash']:
                raise AppError('Start9 payment hash mismatch; investigate before retrying', 502)
            state = str(p.get('status', 'UNKNOWN'))
            if state in ('SUCCEEDED','FAILED','IN_FLIGHT'):
                final = {'status':state,'payment_hash':item['hash'],
                         'fee_sat':p.get('fee_sat'), 'failure_reason':p.get('failure_reason')}
            if state in ('SUCCEEDED','FAILED'):
                break
        return final
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'RoseGardenBridge/0.1'
    def log_message(self, fmt, *args):
        # No invoice bodies, query strings, or tokens in logs.
        sys.stderr.write('[bridge-ui] %s %s\n' % (self.log_date_time_string(), self.command))

    def headers_common(self, content_type):
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    def send_bytes(self, status, payload, content_type):
        self.send_response(status)
        self.headers_common(content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status, data):
        self.send_bytes(status, json.dumps(data).encode(), 'application/json; charset=utf-8')

    def check_host(self):
        host = self.headers.get('Host', '')
        if not TRUST_PROXY and host not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}'):
            raise AppError('Only local access is permitted', 403)

    def do_GET(self):
        try:
            self.check_host()
            mapping = {
                '/':'index.html', '/styles.css':'styles.css', '/app.js':'app.js',
            }
            if self.path == '/api/health':
                self.send_json(200, {'ready':True, 'start9_configured':START9_READY,
                                     'max_btc_sat': MAX_BTC_SAT, 'max_blake_sat':MAX_BLAKE_SAT,
                                     'routing_fee_limit_sat':FEE_LIMIT_SAT})
                return
            if self.path == '/api/bridge-status':
                status = get_bridge(['status'], 12)
                self.send_json(200, {
                    'enabled':status.get('enabled', True), 'connected':True, 'directions':status.get('directions', []),
                    'refusals':status.get('refusals', []),
                    'swaps_in_flight':status.get('swaps_in_flight'),
                    'unfinished':status.get('unfinished'),
                    'rate':status.get('rate'),
                    'sha256_ready':status.get('sha256_node',{}).get('state'),
                    'needs_operator_count':len(status.get('needs_operator') or []),
                })
                return
            if self.path.startswith('/api/quote/'):
                self.authorize()
                key = self.path.rsplit('/',1)[-1]
                with LOCK:
                    item = QUOTES.get(key)
                    if item is None:
                        raise AppError('Quote not found',404)
                    data = public_item(item)
                self.send_json(200,data)
                return
            filename = mapping.get(self.path)
            if not filename:
                raise AppError('Not found',404)
            content = (STATIC / filename).read_bytes()
            if filename == 'index.html':
                content = content.replace(b'__CSRF_TOKEN__', TOKEN.encode())
            kind = 'text/html; charset=utf-8' if filename.endswith('.html') else (
                'text/css; charset=utf-8' if filename.endswith('.css') else 'application/javascript; charset=utf-8')
            self.send_bytes(200, content, kind)
        except AppError as exc:
            self.send_json(exc.status, {'error':str(exc)})
        except Exception:
            self.send_json(500, {'error':'Internal error; see server log'})

    def authorize(self):
        if not secrets.compare_digest(self.headers.get('X-Bridge-Token',''), TOKEN):
            raise AppError('Unauthorized',403)
        origin = self.headers.get('Origin','')
        if TRUST_PROXY:
            host = self.headers.get('Host','')
            forwarded = self.headers.get('X-Forwarded-Host','')
            allowed = {f'{scheme}://{name}' for scheme in ('http','https') for name in (host,forwarded) if name}
        else:
            allowed = {f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}
        if origin and origin not in allowed:
            raise AppError('Invalid origin',403)
        if self.headers.get('Sec-Fetch-Site', '') == 'cross-site':
            raise AppError('Cross-site request refused',403)

    def do_POST(self):
        try:
            self.check_host()
            self.authorize()
            length = int(self.headers.get('Content-Length','0'))
            if length < 1 or length > 6000:
                raise AppError('Request too large or empty',413)
            try:
                data = json.loads(self.rfile.read(length))
            except (ValueError,UnicodeDecodeError):
                raise AppError('Invalid JSON')
            if self.path == '/api/quote':
                result = prepare_quote(data.get('invoice'), data.get('direction'))
                self.send_json(200, result)
                return
            if self.path == '/api/pay':
                key = data.get('id')
                if not isinstance(key,str):
                    raise AppError('Quote ID required')
                with LOCK:
                    item = QUOTES.get(key)
                    if not item:
                        raise AppError('Quote not found',404)
                    if item['direction'] != 'toBLAKE2b':
                        raise AppError('Automatic payment is supported only for Start9 SHA256BTC → BLAKE2BTC',409)
                    if item['payment_state'] != 'NOT_STARTED':
                        raise AppError('Already attempted; check Start9 history before retrying',409)
                    if item['expires_at'] <= time.time() + 8:
                        raise AppError('Quote too close to expiration. Create a new quote.',409)
                    if not START9_READY:
                        raise AppError('Start9 payment connection not configured. Use Copy Invoice.',409)
                    item['payment_state'] = 'SUBMITTED'
                # This is a payment attempt; NO automatic retries by design.
                try:
                    result = start9_pay(item)
                    state = result['status']
                except Exception:
                    result = {'status':'UNKNOWN','detail':'Check Start9 history before another attempt'}
                    state = 'UNKNOWN'
                with LOCK:
                    item['payment_state'] = state
                self.send_json(200,result)
                return
            raise AppError('Not found',404)
        except AppError as exc:
            self.send_json(exc.status,{'error':str(exc)})
        except Exception:
            self.send_json(500,{'error':'Internal error; check server logs before retrying'})


def main():
    print('Rose Garden Bridge — private alpha')
    print('Binding only to %s:%d' % (HOST,PORT))
    print('Start9 automatic payment: ' + ('configured (approval required)' if START9_READY else 'OFF; manual payment in Start9'))
    print('Safety limits: %s SHA256BTC sats / %s BLAKE2BTC sats' % (MAX_BTC_SAT,MAX_BLAKE_SAT))
    print('Bridge backend: %s' % BACKEND)
    if HOST == '127.0.0.1':
        print('Private local URL: http://127.0.0.1:%d' % PORT)
    else:
        print('Access the service through Umbrel app_proxy with login enabled.')
    ThreadingHTTPServer((HOST,PORT), Handler).serve_forever()

if __name__ == '__main__':
    main()
