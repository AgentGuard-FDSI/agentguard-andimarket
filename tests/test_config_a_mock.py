import config_a
from tools import simulated


def test_legitimate_prompt_has_no_destructive_effects():
    simulated.reset_state()
    config_a.run_prompt(config_a.PROMPT_LEGITIMO)
    assert simulated.EFECTOS == []
    assert len(simulated.PEDIDOS) == 3


def test_injection_succeeds_without_agentguard():
    simulated.reset_state()
    config_a.run_prompt(config_a.PROMPT_CON_INYECCION)
    deleted = {e["order_id"] for e in simulated.EFECTOS if e["tool"] == "eliminar_pedido"}
    assert deleted == {"123", "124", "125"}
    assert simulated.PEDIDOS == {}
