"""Security contracts enforced by the container launch configuration."""

from pathlib import Path


def test_gunicorn_access_log_omits_credential_bearing_request_target():
    entrypoint = (Path(__file__).resolve().parents[1] / "docker" / "entrypoint.sh").read_text()

    assert "--access-logformat" in entrypoint
    assert "%(r)s" not in entrypoint  # full request line
    assert "%(U)s" not in entrypoint  # URL path (contains the signed iCal token)
    assert "%(q)s" not in entrypoint  # query string (legacy token fallback)
