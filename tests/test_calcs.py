"""
Tests for choosing ALIGNN-FF models in setup_calculator.

alignn.ff.ff is replaced by a stand-in, so no model is downloaded or loaded.
"""
import sys
import types

import pytest

from chipsff.calcs import setup_calculator


@pytest.fixture
def downloads(monkeypatch):
    """Install a stand-in alignn.ff.ff and return the list of downloaded models."""
    downloaded = []

    class FakeCalculator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def get_figshare_model_ff(model_name):
        downloaded.append(model_name)
        return f"/cache/{model_name}"

    ff = types.ModuleType("alignn.ff.ff")
    ff.AlignnAtomwiseCalculator = FakeCalculator
    ff.get_all_models = lambda: {"alignn_ff_mptrj": "https://example/1"}
    ff.get_figshare_model_ff = get_figshare_model_ff
    for name in ("alignn", "alignn.ff"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "alignn.ff.ff", ff)
    return downloaded


def test_alignn_ff_keeps_default_model(downloads):
    assert setup_calculator("alignn_ff", {}).kwargs == {}
    assert downloads == []


def test_named_alignn_ff_model_is_downloaded(downloads):
    calc = setup_calculator("alignn_ff_mptrj", {})
    assert calc.kwargs == {"path": "/cache/alignn_ff_mptrj"}
    assert downloads == ["alignn_ff_mptrj"]


def test_alignn_ff_model_path_and_options(downloads):
    settings = {"path": "/models/mine", "stress_wt": 0.5, "unrelated": 1}
    calc = setup_calculator("alignn_ff_mine", settings)
    assert calc.kwargs == {"path": "/models/mine", "stress_wt": 0.5}
    assert downloads == []


def test_unknown_alignn_ff_model_without_path(downloads):
    with pytest.raises(ValueError, match="alignn_ff_unknown"):
        setup_calculator("alignn_ff_unknown", {})
    assert downloads == []
