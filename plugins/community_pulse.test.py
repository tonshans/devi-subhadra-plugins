from unittest.mock import patch, MagicMock
from plugins.community_pulse import CommunityPulsePlugin

@patch('httpx.Client.get')
def test_community_pulse_execute_success(mock_get):
    # Mocking response dari Reddit JSON API
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "children": [
                {"data": {"title": "Is FastAPI still good?", "url": "http://reddit.com/r/fastapi", "score": 150}}
            ]
        }
    }
    mock_get.return_value = mock_response

    plugin = CommunityPulsePlugin()
    plugin.initialize({})

    payload = {"query": "FastAPI", "subreddit": "Python"}
    result = plugin.execute(payload)

    # Assertion-Driven Execution Check
    assert result.success is True
    assert len(result.data["threads"]) == 1
    assert result.data["threads"][0]["score"] == 150
    # Memastikan custom header terpasang pada client Reddit
    mock_get.assert_called_once()
    assert "DeviSubhadra-Agent" in plugin.client.headers["User-Agent"]
