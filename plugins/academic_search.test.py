import pytest
from unittest.mock import patch, MagicMock
from plugins.academic_search import AcademicSearchPlugin

def test_academic_search_plugin_schema():
    plugin = AcademicSearchPlugin()
    # Menguji Pydantic Schema (extra="forbid")
    with pytest.raises(ValueError):
        plugin.input_schema(query="AGI", extra_field="hacker")

@patch('httpx.Client.get')
def test_academic_search_execute_success(mock_get):
    # Mocking response dari OpenAlex API
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"title": "Attention Is All You Need", "doi": "https://doi.org/10.48550/arXiv.1706.03762", "publication_year": 2017}
        ]
    }
    mock_get.return_value = mock_response

    plugin = AcademicSearchPlugin()
    plugin.initialize({})

    payload = {"query": "Transformer models", "max_results": 1}
    result = plugin.execute(payload)

    # Assertion-Driven Execution Check
    assert result.success is True
    assert len(result.data["papers"]) == 1
    assert result.data["papers"][0]["title"] == "Attention Is All You Need"
    assert result.assertions_passed is True
