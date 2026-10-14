"""Static assets are served under a content-hashed prefix so deploys never mix old and new files."""
import re

PAGES = ["/", "/track", "/quiz", "/admin"]


def versioned_refs(html):
    return re.findall(r'"(/static/v/[0-9a-f]{12}/[^"]+)"', html)


def test_pages_reference_only_versioned_assets(client):
    for page in PAGES:
        r = client.get(page)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache"
        assert '"/static/' not in r.text.replace('"/static/v/', "")
        refs = versioned_refs(r.text)
        assert refs, page
        for ref in refs:
            asset = client.get(ref)
            assert asset.status_code == 200, ref
            assert "immutable" in asset.headers["cache-control"]


def test_relative_module_imports_resolve_under_the_version(client):
    script = next(ref for ref in versioned_refs(client.get("/track").text) if ref.endswith("track.js"))
    base = script.rsplit("/", 1)[0]
    for module in ("i18n.js", "animate.js", "sticker.js", "common.js"):
        assert client.get(f"{base}/{module}").status_code == 200


def test_plain_static_paths_still_work_and_revalidate(client):
    r = client.get("/static/js/i18n.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_missing_versioned_file_is_not_cached_forever(client):
    ref = versioned_refs(client.get("/").text)[0]
    missing = ref.rsplit("/", 1)[0] + "/does-not-exist.js"
    r = client.get(missing)
    assert r.status_code == 404
    assert "immutable" not in r.headers.get("cache-control", "")
