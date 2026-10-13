"""Regression tests for ``_strip_json_text``.

Local OpenAI-compatible providers (oMLX, GLM, gemma) sometimes wrap
``json_schema`` output in a markdown fence (````` ```json ... ``` `````) or
prefix it with prose even though ``response_format`` requested strict JSON.
The extractor must normalize those to a string that ``json.loads`` accepts.

The old ``JsonSchemaModelWrapper._parse_response`` method (which used this
helper) was removed in the litellm refactor; the helper survives in
:mod:`soothe_nano.llm.response_text` and is reused by the structured-output
runnable's JSON-text recovery path.
"""

from __future__ import annotations

import json

import pytest

from soothe_nano.llm.response_text import _strip_json_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Raw JSON — passes through unchanged.
        ('{"word": "GOJSON"}', {"word": "GOJSON"}),
        # Markdown-fenced json.
        ('```json\n{\n  "word": "GOJSON"\n}\n```', {"word": "GOJSON"}),
        # Bare fence (no language tag).
        ('```\n{"word": "GOJSON"}\n```', {"word": "GOJSON"}),
        # Prose prefix before the object.
        ('Here is the JSON: {"word": "GOJSON"}', {"word": "GOJSON"}),
        # Fence with leading newline (observed from gemma on oMLX).
        ('\n```json\n{\n  "word": "GOJSON"\n}\n```', {"word": "GOJSON"}),
    ],
)
def test_strip_json_text_parses_wrapped_output(raw: str, expected: dict) -> None:
    assert json.loads(_strip_json_text(raw)) == expected
