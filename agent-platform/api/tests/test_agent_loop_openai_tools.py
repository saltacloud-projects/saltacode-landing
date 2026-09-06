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
                "tool_name": "inventory_item_status",
                "description": "Estado de inventario",
            }
        ],
        {
            "inventory_item_status": {
                "params_schema": {
                    "item": {
                        "type": "string",
                        "description": "Artículo",
                        "required": True,
                    },
                    "debug": {"type": "boolean", "description": "Debug"},
                }
            }
        },
    )
    params = _parameters(tools[0])
    assert params["required"] == ["item"]
    assert params["properties"]["item"]["description"] == "Artículo"
    assert "debug" not in params["required"]


def test_build_openai_tools_omits_required_when_only_require_any_exists():
    tools = _build_openai_tools(
        [
            {
                "tool_name": "inventory_movement_lookup",
                "description": "Movimientos de inventario",
            }
        ],
        {
            "inventory_movement_lookup": {
                "params_schema": {
                    "reference": {"type": "string"},
                    "region": {"type": "string"},
                },
                "http_config": {"require_any": ["reference", "region"]},
            }
        },
    )
    assert "required" not in _parameters(tools[0])


def test_build_openai_tools_preserves_existing_optional_tools():
    tools = _build_openai_tools(
        [
            {
                "tool_name": "inventory_movements",
                "description": "Movimientos por filtros",
            }
        ],
        {"inventory_movements": {"params_schema": {"month": {"type": "string"}}}},
    )
    params = _parameters(tools[0])
    assert params["properties"]["month"]["type"] == "string"
    assert "required" not in params
