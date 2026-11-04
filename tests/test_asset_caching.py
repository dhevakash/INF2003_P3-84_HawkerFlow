"""Reloads must revalidate assets so UI fixes reach browsers with cached files."""


def test_page_and_assets_require_cache_revalidation(client):
    for path in ('/', '/static/style.css?v=20261104-2', '/static/app.js'):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-cache'


def test_unchanged_styles_can_revalidate_with_etag(client):
    path = '/static/style.css?v=20261104-2'
    response = client.get(path)
    cached = client.get(path, headers={'If-None-Match': response.headers['etag']})
    assert cached.status_code == 304
    assert cached.headers['cache-control'] == 'no-cache'
