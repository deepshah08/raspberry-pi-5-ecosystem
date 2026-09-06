import pytest
import requests
from unittest.mock import patch, Mock
from search_client import SearXNGClient

@pytest.fixture
def client():
    return SearXNGClient(base_url="http://localhost:8888")

@pytest.fixture
def mock_response_data():
    return {
        "query": "test query",
        "number_of_results": 2,
        "results": [
            {
                "title": "First Result",
                "url": "https://example.com/1",
                "content": "This is the first snippet."
            },
            {
                "title": "Second Result",
                "url": "https://example.com/2",
                "snippet": "This is the second snippet using snippet key."
            }
        ]
    }

def test_search_success(client, mock_response_data):
    with patch("requests.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = client.search(query="test query")

        mock_get.assert_called_once_with(
            "http://localhost:8888/search",
            params={"q": "test query", "format": "json", "language": "en", "pageno": 1},
            timeout=10
        )
        assert result == mock_response_data

def test_search_with_params(client, mock_response_data):
    with patch("requests.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = client.search(
            query="python",
            engines=["github", "google"],
            pageno=2,
            time_range="year"
        )

        mock_get.assert_called_once_with(
            "http://localhost:8888/search",
            params={
                "q": "python",
                "format": "json",
                "language": "en",
                "pageno": 2,
                "engines": "github,google",
                "time_range": "year"
            },
            timeout=10
        )

def test_search_timeout(client):
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        with pytest.raises(TimeoutError) as exc_info:
            client.search(query="test query", timeout=5)

        assert "Search request timed out after 5 seconds" in str(exc_info.value)

def test_search_http_error(client):
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.HTTPError("404 Not Found")

        with pytest.raises(RuntimeError) as exc_info:
            client.search(query="test query")

        assert "Search request failed" in str(exc_info.value)

def test_format_as_markdown(client, mock_response_data):
    markdown = client._format_as_markdown(mock_response_data)

    expected = (
        "### 1. [First Result](https://example.com/1)\n"
        "This is the first snippet.\n\n"
        "### 2. [Second Result](https://example.com/2)\n"
        "This is the second snippet using snippet key."
    )

    assert markdown == expected

def test_format_as_markdown_empty(client):
    markdown = client._format_as_markdown({"results": []})
    assert markdown == "No results found."

def test_search_as_markdown(client, mock_response_data):
    with patch("requests.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        markdown = client.search_as_markdown("test query")

        assert "### 1. [First Result](https://example.com/1)" in markdown
        assert "### 2. [Second Result](https://example.com/2)" in markdown
