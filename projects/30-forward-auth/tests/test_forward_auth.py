import sys
from pathlib import Path
import time
import pytest
import subprocess
import json
import io
import urllib.request
import threading
import socket
from http.cookies import SimpleCookie

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forward_auth import TokenValidator, RoleGovernor, MetricsRegistry, ForwardAuthHandler, run

def test_create_and_verify_valid_token():
    validator = TokenValidator(secret_key="my_super_secret")
    payload = {"user": "alice", "role": "Admin"}
    token = validator.create_token(payload, expires_in=3600)
    
    verified_payload = validator.verify_token(token)
    assert verified_payload is not None
    assert verified_payload["user"] == "alice"
    assert verified_payload["role"] == "Admin"
    assert "exp" in verified_payload

def test_verify_expired_token():
    validator = TokenValidator(secret_key="my_super_secret")
    payload = {"user": "bob", "role": "Guest"}
    token = validator.create_token(payload, expires_in=-1)
    
    verified_payload = validator.verify_token(token)
    assert verified_payload is None

def test_verify_invalid_signature():
    validator = TokenValidator(secret_key="my_super_secret")
    payload = {"user": "eve", "role": "Admin"}
    token = validator.create_token(payload)
    
    parts = token.split('.')
    tampered_token = f"{parts[0]}.{parts[1][:-2]}AA"
    
    verified_payload = validator.verify_token(tampered_token)
    assert verified_payload is None

def test_verify_no_secret_key():
    validator = TokenValidator(secret_key="")
    payload = {"user": "dave", "role": "Admin"}
    token = validator.create_token(payload)
    
    verified_payload = validator.verify_token(token)
    assert verified_payload is None

def test_verify_empty_or_malformed_token():
    validator = TokenValidator(secret_key="secret")
    assert validator.verify_token("") is None
    assert validator.verify_token("invalid_format_without_dot") is None
    assert validator.verify_token("payload.sig.extra") is None


def test_role_governor_admin():
    governor = RoleGovernor()
    assert governor.is_allowed("Admin", "admin.homelab.local") is True
    assert governor.is_allowed("Admin", "proxymanager.homelab.local") is True
    assert governor.is_allowed("Admin", "public.homelab.local") is True

def test_role_governor_guest():
    governor = RoleGovernor()
    assert governor.is_allowed("Guest", "admin.homelab.local") is False
    assert governor.is_allowed("Guest", "proxymanager.homelab.local") is False
    assert governor.is_allowed("Guest", "public.homelab.local") is True

def test_role_governor_unknown():
    governor = RoleGovernor()
    assert governor.is_allowed("Unknown", "public.homelab.local") is False


def test_metrics_registry():
    metrics = MetricsRegistry()
    metrics.inc_requests()
    metrics.inc_requests()
    metrics.inc_allowed()
    metrics.inc_denied()
    
    output = metrics.export()
    assert "homelab_auth_requests_total 2" in output
    assert "homelab_auth_allowed_total 1" in output
    assert "homelab_auth_denied_total 1" in output


def test_cli_check_now():
    script_path = str(Path(__file__).resolve().parent.parent / "forward_auth.py")
    result = subprocess.run(
        [sys.executable, script_path, "--check-now"], 
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "Check passed" in result.stdout

def test_cli_check_now_json():
    script_path = str(Path(__file__).resolve().parent.parent / "forward_auth.py")
    result = subprocess.run(
        [sys.executable, script_path, "--check-now", "--json"], 
        capture_output=True, text=True
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "check passed"

def test_cli_dry_run():
    script_path = str(Path(__file__).resolve().parent.parent / "forward_auth.py")
    result = subprocess.run(
        [sys.executable, script_path, "--dry-run"], 
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "Dry runmode. Exiting." in result.stdout

def test_cli_dry_run_json():
    script_path = str(Path(__file__).resolve().parent.parent / "forward_auth.py")
    result = subprocess.run(
        [sys.executable, script_path, "--dry-run", "--json"], 
        capture_output=True, text=True
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "dry run"


class MockHandler:
    def __init__(self, path, headers, validator, metrics, governor):
        self.path = path
        self.headers = headers
        self.token_validator = validator
        self.metrics = metrics
        self.governor = governor
        self.status = None
        self.response_headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.status = code

    def send_header(self, k, v):
        self.response_headers[k] = v

    def end_headers(self):
        pass

    do_GET = ForwardAuthHandler.do_GET

@pytest.fixture
def auth_components():
    secret = "test_secret"
    validator = TokenValidator(secret_key=secret)
    metrics = MetricsRegistry()
    governor = RoleGovernor()
    return validator, metrics, governor

def test_server_metrics_endpoint(auth_components):
    validator, metrics, governor = auth_components
    handler = MockHandler("/metrics", {}, validator, metrics, governor)
    handler.do_GET()
    assert handler.status == 200
    content = handler.wfile.getvalue().decode('utf-8')
    assert "homelab_auth_requests_total" in content

def test_server_verify_unauthorized_no_cookie(auth_components):
    validator, metrics, governor = auth_components
    handler = MockHandler("/verify", {}, validator, metrics, governor)
    handler.do_GET()
    assert handler.status == 401

def test_server_verify_authorized_admin(auth_components):
    validator, metrics, governor = auth_components
    token = validator.create_token({"user": "admin_user", "role": "Admin"})
    headers = {
        "Cookie": f"homelab_session={token}",
        "X-Forwarded-Host": "admin.homelab.local"
    }
    handler = MockHandler("/verify", headers, validator, metrics, governor)
    handler.do_GET()
    assert handler.status == 200
    assert handler.response_headers.get("X-Forwarded-User") == "admin_user"

def test_server_verify_authorized_guest(auth_components):
    validator, metrics, governor = auth_components
    token = validator.create_token({"user": "guest_user", "role": "Guest"})
    headers = {
        "Cookie": f"homelab_session={token}",
        "X-Forwarded-Host": "public.homelab.local"
    }
    handler = MockHandler("/verify", headers, validator, metrics, governor)
    handler.do_GET()
    assert handler.status == 200
    assert handler.response_headers.get("X-Forwarded-User") == "guest_user"

def test_server_verify_unauthorized_guest_on_admin(auth_components):
    validator, metrics, governor = auth_components
    token = validator.create_token({"user": "guest_user", "role": "Guest"})
    headers = {
        "Cookie": f"homelab_session={token}",
        "X-Forwarded-Host": "admin.homelab.local"
    }
    handler = MockHandler("/verify", headers, validator, metrics, governor)
    handler.do_GET()
    assert handler.status == 401

