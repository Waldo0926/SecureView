from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NGINX_CONFIG = REPO_ROOT / "deployment/server/nginx-secureview.conf"


def _location(config: str, path: str) -> str:
    start = config.index(f"    location {path} {{")
    end = config.index("\n    }", start)
    return config[start:end]


def test_main_site_csp_remains_self_only() -> None:
    config = NGINX_CONFIG.read_text(encoding="utf-8")
    server_policy = config.split("    location ", maxsplit=1)[0]

    assert "script-src 'self' 'wasm-unsafe-eval'" in server_policy
    assert "cdn.jsdelivr.net" not in server_policy


def test_generated_api_docs_receive_only_the_assets_they_need() -> None:
    config = NGINX_CONFIG.read_text(encoding="utf-8")

    for path in ("/docs", "/redoc"):
        location = _location(config, path)
        assert "script-src 'unsafe-inline' https://cdn.jsdelivr.net" in location
        assert "style-src 'unsafe-inline' https://cdn.jsdelivr.net" in location
        assert "connect-src 'self'" in location
        assert "frame-ancestors 'none'" in location
        assert "X-Content-Type-Options nosniff" in location
        assert "Strict-Transport-Security" in location
        assert "X-Frame-Options DENY" in location


def test_every_location_that_adds_a_header_repeats_the_security_headers() -> None:
    # nginx drops all server-level add_header directives in a location that has its own.
    config = NGINX_CONFIG.read_text(encoding="utf-8")
    https_server = config.split("listen 443 ssl", maxsplit=1)[0]
    blocks = https_server.split("\n    location ")[1:]
    with_headers = [block for block in blocks if "add_header" in block.split("\n    }")[0]]

    assert with_headers, "expected at least /assets/, /docs and /redoc"
    for block in with_headers:
        body = block.split("\n    }")[0]
        for header in (
            "X-Content-Type-Options nosniff",
            "Strict-Transport-Security",
            "X-Frame-Options DENY",
            "Referrer-Policy",
            "Permissions-Policy",
        ):
            assert header in body, f"location {body.splitlines()[0]} drops {header}"
