import pytest

from app.auth import normalize_email
from app.config import JWT_SECRET_DEFAULT, require_jwt_secret


def test_normalize_email_lowercases_and_strips():
    assert normalize_email("  User@Example.COM ") == "user@example.com"


def test_dev_allows_default_jwt_secret():
    require_jwt_secret(secret=JWT_SECRET_DEFAULT, env="dev")


def test_production_refuses_default_jwt_secret():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        require_jwt_secret(secret=JWT_SECRET_DEFAULT, env="production")


def test_production_accepts_a_real_jwt_secret():
    require_jwt_secret(secret="not-the-default", env="production")
