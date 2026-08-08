"""Provider-neutral normalization for Helix function declarations.

Helix historically stored declarations in the shape accepted by Gemini::

    {"name": "...", "description": "...", "parameters": {JSON Schema}}

The schema itself is ordinary JSON Schema.  This module keeps that storage
format compatible while giving every provider one validated representation.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List


_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_EMPTY_OBJECT_SCHEMA = {"type": "object", "properties": {}}


def normalize_function_declarations(
    declarations: Iterable[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """Return validated declarations with a provider-neutral ``input_schema``.

    Both legacy ``parameters`` and provider-neutral ``input_schema`` inputs are
    accepted.  Names are deliberately restricted to the common denominator of
    Gemini, Anthropic, and Codex function tools.
    """
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for raw in declarations or []:
        if not isinstance(raw, dict):
            raise ValueError("Tool declarations must be dictionaries")
        name = str(raw.get("name", "")).strip()
        if not name or not _TOOL_NAME_RE.fullmatch(name):
            raise ValueError(
                f"Invalid tool name {name!r}; use only letters, digits, '_' or '-'"
            )
        if name in seen:
            raise ValueError(f"Duplicate tool declaration: {name}")
        seen.add(name)

        schema = raw.get("input_schema", raw.get("parameters"))
        if schema is None:
            schema = _EMPTY_OBJECT_SCHEMA
        if not isinstance(schema, dict):
            raise ValueError(f"Input schema for {name!r} must be a dictionary")
        schema = copy.deepcopy(schema)
        if not schema:
            schema = copy.deepcopy(_EMPTY_OBJECT_SCHEMA)
        schema.setdefault("type", "object")
        if schema.get("type") != "object":
            raise ValueError(f"Top-level input schema for {name!r} must be an object")
        schema.setdefault("properties", {})
        if not isinstance(schema["properties"], dict):
            raise ValueError(f"Schema properties for {name!r} must be a dictionary")

        normalized.append({
            "name": name,
            "description": str(raw.get("description", "")).strip(),
            "input_schema": schema,
        })
    return normalized


def to_anthropic_tools(
    declarations: Iterable[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """Convert legacy or normalized declarations to Anthropic's tool shape."""
    return normalize_function_declarations(declarations)


def to_codex_tool_catalog(
    declarations: Iterable[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """Convert declarations to the compact catalog embedded for Codex."""
    return normalize_function_declarations(declarations)


def validate_tool_arguments(arguments: Any, schema: Dict[str, Any], path: str = "arguments") -> None:
    """Validate the JSON-Schema subset used by Helix tool declarations.

    The declarations use ordinary object/property/required/type/enum/array
    constraints.  Keeping this lightweight validator in-tree avoids adding a
    runtime dependency merely for the Codex host bridge.
    """
    expected = schema.get("type")
    allowed_types = expected if isinstance(expected, list) else [expected]
    type_ok = not expected
    for type_name in allowed_types:
        if type_name == "null" and arguments is None:
            type_ok = True
        elif type_name == "object" and isinstance(arguments, dict):
            type_ok = True
        elif type_name == "array" and isinstance(arguments, list):
            type_ok = True
        elif type_name == "string" and isinstance(arguments, str):
            type_ok = True
        elif type_name == "integer" and isinstance(arguments, int) and not isinstance(arguments, bool):
            type_ok = True
        elif type_name == "number" and isinstance(arguments, (int, float)) and not isinstance(arguments, bool):
            type_ok = True
        elif type_name == "boolean" and isinstance(arguments, bool):
            type_ok = True
    if not type_ok:
        raise ValueError(f"{path} must have JSON type {expected!r}")

    if "enum" in schema and arguments not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']!r}")

    if isinstance(arguments, dict):
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in arguments]
        if missing:
            raise ValueError(f"{path} is missing required fields: {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(arguments) - set(properties))
            if extras:
                raise ValueError(f"{path} has unsupported fields: {', '.join(extras)}")
        for key, value in arguments.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                validate_tool_arguments(value, child_schema, f"{path}.{key}")
    elif isinstance(arguments, list) and isinstance(schema.get("items"), dict):
        for index, value in enumerate(arguments):
            validate_tool_arguments(value, schema["items"], f"{path}[{index}]")
    elif isinstance(arguments, str):
        if "minLength" in schema and len(arguments) < int(schema["minLength"]):
            raise ValueError(f"{path} is shorter than minLength")
        if "maxLength" in schema and len(arguments) > int(schema["maxLength"]):
            raise ValueError(f"{path} is longer than maxLength")
    elif isinstance(arguments, (int, float)) and not isinstance(arguments, bool):
        if "minimum" in schema and arguments < schema["minimum"]:
            raise ValueError(f"{path} is below minimum")
        if "maximum" in schema and arguments > schema["maximum"]:
            raise ValueError(f"{path} is above maximum")
