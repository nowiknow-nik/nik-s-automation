from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from change_detection import compare_numeric


def test_unchanged_zero():
    result = compare_numeric(0, 0)

    assert result["change_type"] == "UNCHANGED"
    assert result["absolute_change"] == 0
    assert result["percentage_change"] is None


def test_zero_to_positive():
    result = compare_numeric(0, 25)

    assert result["change_type"] == "CHANGED"
    assert result["absolute_change"] == 25
    assert result["percentage_change"] is None


def test_positive_growth():
    result = compare_numeric(25, 50)

    assert result["change_type"] == "CHANGED"
    assert result["absolute_change"] == 25
    assert result["percentage_change"] == 100


def test_positive_decline():
    result = compare_numeric(50, 25)

    assert result["change_type"] == "CHANGED"
    assert result["absolute_change"] == -25
    assert result["percentage_change"] == -50


def test_missing_previous_value():
    result = compare_numeric(None, 25)

    assert result["change_type"] == "UNAVAILABLE"
    assert result["absolute_change"] is None
    assert result["percentage_change"] is None


def test_missing_current_value():
    result = compare_numeric(25, None)

    assert result["change_type"] == "UNAVAILABLE"
    assert result["absolute_change"] is None
    assert result["percentage_change"] is None