import pytest


@pytest.fixture(scope="module")
def clxs_input_param_model():
    from freshquant.sim.clxs_strategy.input_param_models import ClxsInputParamModel

    return ClxsInputParamModel


def test_clxs_model_option_rejects_unknown_value(clxs_input_param_model) -> None:
    with pytest.raises(ValueError, match="var_model_opt"):
        clxs_input_param_model(var_model_opt=999)
