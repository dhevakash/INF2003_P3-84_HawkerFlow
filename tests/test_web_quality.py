"""HTTP safety and rebuild caching checks without touching either database."""
import logging
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app


@pytest.fixture
def client():
    # Do not enter lifespan: these routes must be testable without live stores.
    instance = TestClient(app)
    yield instance
    instance.close()


def test_workspace_keeps_script_policy_local_and_applies_security_headers(client):
    response = client.get('/')
    assert response.status_code == 200
    csp = response.headers['content-security-policy']
    assert "script-src 'self';" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp
    assert 'cdn.redoc.ly' not in csp
    assert 'worker-src' not in csp
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-frame-options'] == 'DENY'
    assert 'camera=()' in response.headers['permissions-policy']


@pytest.mark.parametrize('path', ['/', '/about', '/static/app.js', '/static/styles.css'])
def test_ui_revalidates_after_application_rebuilds(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-cache'
    if path.startswith('/static/'):
        cached = client.get(path, headers={'If-None-Match': response.headers['etag']})
        assert cached.status_code == 304
        assert cached.headers['cache-control'] == 'no-cache'


@pytest.mark.parametrize('path', ['/docs', '/redoc'])
def test_documentation_uses_unique_nonces_without_relaxing_application_scripts(client, path):
    response = client.get(path)
    csp = response.headers['content-security-policy']
    script_directive = next(item.strip() for item in csp.split(';') if item.strip().startswith('script-src'))
    assert 'unsafe-inline' not in script_directive
    assert 'unsafe-eval' not in script_directive
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    scripts = re.findall(r'<script\b[^>]*>', response.text)
    assert scripts and all(f'nonce="{nonce}"' in tag for tag in scripts)
    assert nonce not in client.get(path).headers['content-security-policy']
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert 'fonts.googleapis.com' not in response.text
    assert 'fastapi.tiangolo.com/img/favicon.png' not in response.text
    if path == '/redoc':
        assert "worker-src 'self' blob:" in csp
        assert 'https://cdn.redoc.ly/redoc/logo-mini.svg' in csp
    else:
        assert 'worker-src' not in csp and 'cdn.redoc.ly' not in csp


def test_demo_information_is_local_and_transparent(client):
    response = client.get('/about')
    assert response.status_code == 200
    assert 'id="usage"' in response.text and 'id="privacy"' in response.text
    assert 'sessionStorage' in response.text
    assert 'not a reviewed commercial service agreement' in response.text
    assert '<script' not in response.text
    assert 'href="/static/styles.css"' in response.text


@pytest.mark.parametrize('path', ['/static/app.js', '/static/styles.css', '/openapi.json'])
def test_large_assets_and_schema_compress_without_changing_contents(client, path):
    compressed = client.get(path, headers={'Accept-Encoding': 'gzip'})
    uncompressed = client.get(path, headers={'Accept-Encoding': 'identity'})
    assert compressed.headers['content-encoding'] == 'gzip'
    assert 'Accept-Encoding' in compressed.headers['vary']
    assert 'content-encoding' not in uncompressed.headers
    assert compressed.content == uncompressed.content  # HTTP client decodes gzip.


def test_api_errors_do_not_cache_or_log_bound_customer_data(client, caplog):
    private_email = 'private-customer@example.test'
    secret_password = 'private-password-value'

    def unavailable_session():
        raise OperationalError('SELECT * FROM users WHERE email = :email',
                               {'email': private_email, 'password': secret_password},
                               RuntimeError('private-driver-message'))
        yield  # Keep this a dependency generator.

    app.dependency_overrides[get_session] = unavailable_session
    try:
        with caplog.at_level(logging.ERROR, logger='app.main'):
            response = client.post('/api/auth/login', json={'email': private_email, 'password': secret_password})
        assert response.status_code == 503
        assert response.headers['cache-control'] == 'no-store'
        assert private_email not in response.text + caplog.text
        assert secret_password not in response.text + caplog.text
        assert 'SELECT * FROM users' not in caplog.text
        assert 'private-driver-message' not in caplog.text
        records = [record for record in caplog.records if record.name == 'app.main']
        assert len(records) == 1 and records[0].exc_info is None
        assert 'OperationalError' in records[0].getMessage()
    finally:
        app.dependency_overrides.pop(get_session, None)
