import pytest

from freshquant.sim.clxs_strategy.input_param_models import ClxsInputParamModel


def test_clxs_model_option_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="var_model_opt"):
        ClxsInputParamModel(var_model_opt=999)
