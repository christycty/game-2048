from app.telemetry import traces_url


def test_phoenix_base_url_gets_traces_path() -> None:
    assert traces_url("http://localhost:6006") == "http://localhost:6006/v1/traces"
    assert traces_url("http://phoenix:6006/") == "http://phoenix:6006/v1/traces"


def test_full_traces_url_is_kept() -> None:
    url = "http://localhost:6006/v1/traces"
    assert traces_url(url) == url
