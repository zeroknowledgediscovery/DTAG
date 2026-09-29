"""Shared-password protection (DTAG_PASSWORD)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dtag_web.app import create_app
from dtag_web.auth import COOKIE, PasswordAuth


@pytest.fixture()
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html>DTAG UI</html>")
    return d


@pytest.fixture()
def client(fake_engine, dist):
    auth = PasswordAuth("s3cret-pass", secret="test-secret", max_failures=3)
    return TestClient(create_app(engine=fake_engine, frontend_dist=dist, auth=auth), follow_redirects=False)


def test_disabled_by_default(fake_engine, dist, monkeypatch):
    monkeypatch.delenv("DTAG_PASSWORD", raising=False)
    c = TestClient(create_app(engine=fake_engine, frontend_dist=dist))
    assert c.get("/api/profiles").status_code == 200
    assert c.get("/").status_code == 200
    assert c.get("/api/health").json()["auth"] == "none"


def test_enabled_from_env(fake_engine, dist, monkeypatch):
    monkeypatch.setenv("DTAG_PASSWORD", "from-env")
    c = TestClient(create_app(engine=fake_engine, frontend_dist=dist), follow_redirects=False)
    assert c.get("/api/profiles").status_code == 401
    assert c.get("/api/profiles", headers={"Authorization": "Bearer from-env"}).status_code == 200


def test_everything_protected_except_health_and_login(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").json()["auth"] == "password"
    for path in ("/api/profiles", "/api/models", "/api/readiness", "/openapi.json"):
        r = client.get(path)
        assert r.status_code == 401 and r.json()["detail"] == "Authentication required", path
    assert client.post("/api/sessions", json={"profile": "gss2024_cm"}).status_code == 401
    for path in ("/", "/docs", "/some/page", "/assets/app.js"):
        r = client.get(path)
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next="), path
    page = client.get("/login")
    assert page.status_code == 200 and 'type="password"' in page.text


def test_browser_login_flow(client):
    r = client.post("/api/login", data={"password": "wrong", "next": "/"})
    assert r.status_code == 303 and "error=1" in r.headers["location"]
    r = client.post("/api/login", data={"password": "s3cret-pass", "next": "/docs"})
    assert r.status_code == 303 and r.headers["location"] == "/docs"
    set_cookie = r.headers["set-cookie"]
    assert COOKIE in set_cookie and "HttpOnly" in set_cookie and "samesite=lax" in set_cookie.lower()
    assert client.get("/").status_code == 200
    assert client.get("/api/profiles").status_code == 200
    r = client.get("/api/logout")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    client.cookies.clear()
    assert client.get("/api/profiles").status_code == 401


def test_json_login_and_bearer(client):
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    r = client.post("/api/login", json={"password": "s3cret-pass"})
    assert r.status_code == 200 and COOKIE in r.cookies
    client.cookies.clear()
    assert client.get("/api/models", headers={"Authorization": "Bearer s3cret-pass"}).status_code == 200
    assert client.get("/api/models", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_open_redirect_blocked(client):
    for bad in ("https://evil.example", "//evil.example", "/\\evil"):
        r = client.post("/api/login", data={"password": "s3cret-pass", "next": bad})
        assert r.headers["location"] == "/", bad
    assert 'value="/"' in client.get("/login?next=https://evil.example").text


def test_failed_logins_are_throttled(client):
    for _ in range(3):
        client.post("/api/login", json={"password": "bad"})
    r = client.post("/api/login", json={"password": "s3cret-pass"})
    assert r.status_code == 429, "correct password is refused while throttled"
    r = client.post("/api/login", data={"password": "s3cret-pass", "next": "/"})
    assert "error=2" in r.headers["location"]


def test_cookie_integrity():
    a = PasswordAuth("pw-one", secret="k")
    good = a.make_cookie()
    assert a.cookie_valid(good)
    exp, sig = good.split(".")
    assert not a.cookie_valid(f"{int(exp) + 999}.{sig}"), "tampered expiry"
    assert not a.cookie_valid(f"{exp}.{'0' * len(sig)}"), "forged signature"
    assert not a.cookie_valid(f"{int(time.time()) - 5}.{a._sign(int(time.time()) - 5)}"), "expired"
    assert not a.cookie_valid("garbage") and not a.cookie_valid(None)
    b = PasswordAuth("pw-two", secret="k")
    assert not b.cookie_valid(good), "changing the password invalidates cookies"
    assert not PasswordAuth("pw-one", secret="other").cookie_valid(good), "other secret"
