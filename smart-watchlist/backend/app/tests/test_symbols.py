import pytest

from app.services.symbols import SymbolError, is_india_listing, normalize_symbol


def test_normalize_accepts_us_and_nse():
    assert normalize_symbol(" aapl ") == "AAPL"
    assert normalize_symbol("reliance.ns") == "RELIANCE.NS"
    assert normalize_symbol("TCS.BO") == "TCS.BO"
    assert normalize_symbol("brk-b") == "BRK-B"


def test_normalize_rejects_junk():
    with pytest.raises(SymbolError):
        normalize_symbol("")
    with pytest.raises(SymbolError):
        normalize_symbol("AAPL USD")
    with pytest.raises(SymbolError):
        normalize_symbol("../../etc")


def test_india_listing_detection():
    assert is_india_listing("RELIANCE.NS") is True
    assert is_india_listing("TCS.BO") is True
    assert is_india_listing("AAPL") is False
    assert is_india_listing("INFY") is False
