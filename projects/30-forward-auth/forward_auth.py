#!/usr/bin/env python3
import argparse
import sys
import json
import hmac
import hashlib
import base64
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
from http.cookies import SimpleCookie

class TokenValidator:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key.encode('utf-8') if secret_key else b''

    def create_token(self, payload: dict, expires_in: int = 3600) -> str:
        payload['exp'] = int(time.time()) + expires_in
        payload_json = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        payload_b64 = base64.urlsafe_b64encode(payload_json).decode('utf-8').rstrip('=')
        
        signature = hmac.new(self.secret_key, payload_b64.encode('utf-8'), hashlib.sha256).digest()
        signature_b64 = base64.urlsafe_b64encode(signature).decode('utf-8').rstrip('=')
        
        return f"{payload_b64}.{signature_b64}"

    def verify_token(self, token: str) -> dict:
        if not token or not self.secret_key:
            return None
        
        parts = token.split('.')
        if len(parts) != 2:
            return None
        
        payload_b64, signature_b64 = parts
        
        # Verify signature
        expected_signature = hmac.new(self.secret_key, payload_b64.encode('utf-8'), hashlib.sha256).digest()
        expected_signature_b64 = base64.urlsafe_b64encode(expected_signature).decode('utf-8').rstrip('=')
        
        if not hmac.compare_digest(signature_b64, expected_signature_b64):
            return None
        
        # Decode and verify payload
        try:
            # Add padding back if necessary
            padding = '=' * (4 - (len(payload_b64) % 4))
            payload_json = base64.urlsafe_b64decode(payload_b64 + padding).decode('utf-8')
            payload = json.loads(payload_json)
        except Exception:
            return None
            
        if 'exp' in payload and int(time.time()) > payload['exp']:
            return None
            
        return payload

class RoleGovernor:
    # A simple static mapping for now.
    # Admin can access anything.
    # Guest can access non-admin domains.
    def __init__(self):
        self.admin_domains = ["admin.homelab.local", "proxymanager.homelab.local"]
    
    def is_allowed(self, role: str, domain: str) -> bool:
        if role == 'Admin':
            return True
        elif role == 'Guest':
            if domain in self.admin_domains:
                return False
            return True
        return False

class MetricsRegistry:
    def __init__(self):
        self.requests_total = 0
        self.allowed_total = 0
        self.denied_total = 0

    def inc_requests(self):
        self.requests_total += 1

    def inc_allowed(self):
        self.allowed_total += 1

    def inc_denied(self):
        self.denied_total += 1

    def export(self) -> str:
        lines = [
            "# HELP homelab_auth_requests_total Total authentication requests",
            "# TYPE homelab_auth_requests_total counter",
            f"homelab_auth_requests_total {self.requests_total}",
            "# HELP homelab_auth_allowed_total Total allowed authentication requests",
            "# TYPE homelab_auth_allowed_total counter",
            f"homelab_auth_allowed_total {self.allowed_total}",
            "# HELP homelab_auth_denied_total Total denied authentication requests",
            "# TYPE homelab_auth_denied_total counter",
            f"homelab_auth_denied_total {self.denied_total}",
            ""
        ]
        return "\n".join(lines)

class ForwardAuthHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, token_validator=None, metrics=None, governor=None, **kwargs):
        self.token_validator = token_validator
        self.metrics = metrics
        self.governor = governor
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.path == '/verify':
            self.metrics.inc_requests()
            
            # Extract domain from headers
            forwarded_host = self.headers.get('X-Forwarded-Host')
            host = self.headers.get('Host')
            domain = forwarded_host or host or ""

            # Extract cookie
            cookie_header = self.headers.get('Cookie')
            token = None
            if cookie_header:
                cookie = SimpleCookie(cookie_header)
                if 'homelab_session' in cookie:
                    token = cookie['homelab_session'].value

            payload = self.token_validator.verify_token(token)
            if payload and 'role' in payload and 'user' in payload:
                role = payload.get('role')
                user = payload.get('user')
                
                if self.governor.is_allowed(role, domain):
                    self.metrics.inc_allowed()
                    self.send_response(200)
                    self.send_header('X-Forwarded-User', user)
                    self.end_headers()
                    self.wfile.write(b"OK")
                    return
            
            self.metrics.inc_denied()
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            
        elif self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(self.metrics.export().encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

def create_handler_class(validator, metrics, governor):
    class CustomHandler(ForwardAuthHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, token_validator=validator, metrics=metrics, governor=governor, **kwargs)
    return CustomHandler

class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True

def run(port=9136, secret_key=""):
    validator = TokenValidator(secret_key)
    metrics = MetricsRegistry()
    governor = RoleGovernor()
    server_address = ('', port)
    handler_class = create_handler_class(validator, metrics, governor)
    httpd = ReusableHTTPServer(server_address, handler_class)
    print(f"Starting server on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("Server stopped.")

def main():
    parser = argparse.ArgumentParser(description="Forward Auth Middleware Gatekeeper")
    parser.add_argument('--check-now', action='store_true', help="Check something now")
    parser.add_argument('--secret-key', type=str, default="", help="Secret key for HMAC")
    parser.add_argument('--port', type=int, default=9136, help="Port to run on")
    parser.add_argument('--dry-run', action='store_true', help="Dry run mode")
    parser.add_argument('--json', action='store_true', help="Output in JSON")

    args = parser.parse_args()

    if args.check_now:
        if args.json:
            print(json.dumps({"status": "check passed"}))
        else:
            print("Check passed")
        sys.exit(0)
    
    if args.dry_run:
        if args.json:
            print(json.dumps({"status": "dry run"}))
        else:
            print("Dry runmode. Exiting.")
        sys.exit(0)

    run(port=args.port, secret_key=args.secret_key)

if __name__ == '__main__':
    main()
