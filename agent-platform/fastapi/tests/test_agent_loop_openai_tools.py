"""
Tests puros del schema de tools enviado a OpenAI.
"""

from app.services.agent_loop import _build_openai_tools


def _parameters(tool):
    return tool["function"]["parameters"]


def test_build_openai_tools_propagates_required_from_params_schema():
    tools = _build_openai_tools(
        [
            {
                "tool_name": "sim_cuenta_corriente_cliente",
                "description": "Cuenta corriente",
            }
        ],
        {
            "sim_cuenta_corriente_cliente": {
                "params_schema": {
                    "cliente": {
                        "type": "string",
                        "description": "Cliente",
                        "required": True,
                    },
                    "debug": {"type": "boolean", "description": "Debug"},
                }
            }
        },
    )
    params = _parameters(tools[0])
    assert params["required"] == ["cliente"]
    assert params["properties"]["cliente"]["description"] == "Cliente"
    assert "debug" not in params["required"]


def test_build_openai_tools_omits_required_when_only_require_any_exists():
    tools = _build_openai_tools(
        [{"tool_name": "sim_compras_bienes_cambio", "description": "Compras"}],
        {
            "sim_compras_bienes_cambio": {
                "params_schema": {
                    "boleta": {"type": "string"},
                    "orden_carga": {"type": "string"},
                },
                "http_config": {"require_any": ["boleta", "orden_carga"]},
            }
        },
    )
    assert "required" not in _parameters(tools[0])


def test_build_openai_tools_preserves_existing_optional_tools():
    tools = _build_openai_tools(
        [{"tool_name": "sim_compras", "description": "Compras por filtros"}],
        {"sim_compras": {"params_schema": {"mes": {"type": "string"}}}},
    )
    params = _parameters(tools[0])
    assert params["properties"]["mes"]["type"] == "string"
    assert "required" not in params
