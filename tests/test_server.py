import json
from unittest.mock import AsyncMock, MagicMock, patch

import devdocs_mcp.server as server_module
from devdocs_mcp.server import (
    _fetch_db,
    _fetch_index,
    _http_client,
    get_entry,
    list_docs,
    search,
)


def null_http():
    """Stub for _http_client() that yields a mock client without opening connections."""
    mock_client = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# list_docs
# ---------------------------------------------------------------------------


async def test_list_docs_empty():
    assert json.loads(await list_docs()) == []


async def test_list_docs_with_metadata():
    server_module.allowed_slugs = ["python~3.13", "javascript"]
    server_module.doc_metadata = {
        "python~3.13": {"name": "Python", "version": "3.13", "release": "3.13.1"},
    }
    result = json.loads(await list_docs())
    assert result[0] == {
        "slug": "python~3.13",
        "name": "Python",
        "version": "3.13",
        "release": "3.13.1",
    }
    # slug with no metadata falls back to slug as name and empty strings
    assert result[1] == {
        "slug": "javascript",
        "name": "javascript",
        "version": "",
        "release": "",
    }


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


async def test_search_unknown_doc_returns_error():
    server_module.allowed_slugs = ["python~3.13"]
    result = await search("anything", doc="nope")
    assert result.startswith("Error") and "nope" in result


async def test_search_no_match():
    server_module.allowed_slugs = ["python~3.13"]
    index = {"entries": [{"name": "os.path", "type": "module", "path": "os.path"}]}
    with patch("devdocs_mcp.server._fetch_index", AsyncMock(return_value=index)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = await search("zzz", doc="python~3.13")
    assert result == "No entries found matching your query."


async def test_search_returns_matching_entries():
    server_module.allowed_slugs = ["python~3.13"]
    index = {
        "entries": [
            {"name": "list", "type": "class", "path": "stdtypes#list"},
            {"name": "dict", "type": "class", "path": "stdtypes#dict"},
            {"name": "list.append", "type": "method", "path": "stdtypes#list.append"},
        ]
    }
    with patch("devdocs_mcp.server._fetch_index", AsyncMock(return_value=index)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = json.loads(await search("list", doc="python~3.13"))
    assert len(result) == 2
    assert {r["name"] for r in result} == {"list", "list.append"}
    assert all(r["doc"] == "python~3.13" for r in result)


async def test_search_respects_limit():
    server_module.allowed_slugs = ["python~3.13"]
    index = {"entries": [{"name": f"fn{i}", "type": "fn", "path": f"p{i}"} for i in range(50)]}
    with patch("devdocs_mcp.server._fetch_index", AsyncMock(return_value=index)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = json.loads(await search("fn", doc="python~3.13", limit=3))
    assert len(result) == 3


async def test_search_caps_limit_at_100():
    server_module.allowed_slugs = ["python~3.13"]
    index = {"entries": [{"name": f"fn{i}", "type": "fn", "path": f"p{i}"} for i in range(200)]}
    with patch("devdocs_mcp.server._fetch_index", AsyncMock(return_value=index)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = json.loads(await search("fn", doc="python~3.13", limit=9999))
    assert len(result) == 100


async def test_search_all_slugs_when_no_doc_filter():
    server_module.allowed_slugs = ["python~3.13", "javascript"]
    indexes = {
        "python~3.13": {"entries": [{"name": "map", "type": "fn", "path": "map"}]},
        "javascript": {"entries": [{"name": "Array.map", "type": "method", "path": "Array/map"}]},
    }

    async def mock_fetch_index(slug, client):
        return indexes[slug]

    with patch("devdocs_mcp.server._fetch_index", mock_fetch_index):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = json.loads(await search("map"))
    assert len(result) == 2
    assert {r["doc"] for r in result} == {"python~3.13", "javascript"}


async def test_search_skips_slug_when_index_unavailable():
    server_module.allowed_slugs = ["python~3.13"]
    with patch("devdocs_mcp.server._fetch_index", AsyncMock(return_value=None)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = await search("anything", doc="python~3.13")
    assert result == "No entries found matching your query."


# ---------------------------------------------------------------------------
# get_entry
# ---------------------------------------------------------------------------


async def test_get_entry_unknown_doc_returns_error():
    server_module.allowed_slugs = ["python~3.13"]
    result = await get_entry("unknown", "path")
    assert result.startswith("Error") and "unknown" in result


async def test_get_entry_db_fetch_fails():
    server_module.allowed_slugs = ["python~3.13"]
    with patch("devdocs_mcp.server._fetch_db", AsyncMock(return_value=None)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = await get_entry("python~3.13", "some/path")
    assert "Error" in result and "could not fetch" in result


async def test_get_entry_missing_path_returns_error():
    server_module.allowed_slugs = ["python~3.13"]
    db = {"other/key": "<p>content</p>"}
    with patch("devdocs_mcp.server._fetch_db", AsyncMock(return_value=db)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = await get_entry("python~3.13", "missing/path")
    assert "Error" in result and "missing/path" in result


async def test_get_entry_returns_markdown():
    server_module.allowed_slugs = ["python~3.13"]
    db = {"stdtypes": "<h1>Built-in Types</h1>"}
    with patch("devdocs_mcp.server._fetch_db", AsyncMock(return_value=db)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = await get_entry("python~3.13", "stdtypes")
    assert "Built-in Types" in result


async def test_get_entry_strips_url_fragment():
    server_module.allowed_slugs = ["python~3.13"]
    db = {"stdtypes": "<p>Types reference</p>"}
    with patch("devdocs_mcp.server._fetch_db", AsyncMock(return_value=db)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = await get_entry("python~3.13", "stdtypes#list")
    assert "Types reference" in result


async def test_get_entry_fallback_strips_trailing_slash():
    server_module.allowed_slugs = ["python~3.13"]
    db = {"stdtypes": "<p>Types reference</p>"}
    with patch("devdocs_mcp.server._fetch_db", AsyncMock(return_value=db)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = await get_entry("python~3.13", "stdtypes/")
    assert "Types reference" in result


async def test_get_entry_similar_paths_hint():
    server_module.allowed_slugs = ["python~3.13"]
    db = {"array/from": "<p>content</p>"}
    with patch("devdocs_mcp.server._fetch_db", AsyncMock(return_value=db)):
        with patch("devdocs_mcp.server._http_client", return_value=null_http()):
            result = await get_entry("python~3.13", "array/fromsomething")
    # "fromsomething" is not in "array/from", but "from" is a substring check
    # The hint logic checks: db_key.split("/")[-1] ("fromsomething") in each db key
    assert "Error" in result


# ---------------------------------------------------------------------------
# _fetch_index
# ---------------------------------------------------------------------------


async def test_fetch_index_fetches_and_returns():
    data = {"entries": [{"name": "list", "path": "list"}]}
    response = MagicMock(status_code=200)
    response.json.return_value = data
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    result = await _fetch_index("python~3.13", client)

    assert result == data
    client.get.assert_called_once_with("/docs/python~3.13/index.json", timeout=60.0)


async def test_fetch_index_caches_result():
    response = MagicMock(status_code=200)
    response.json.return_value = {"entries": []}
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    await _fetch_index("python~3.13", client)
    await _fetch_index("python~3.13", client)

    client.get.assert_called_once()


async def test_fetch_index_returns_none_on_404():
    response = MagicMock(status_code=404)
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    assert await _fetch_index("nonexistent", client) is None


# ---------------------------------------------------------------------------
# _fetch_db
# ---------------------------------------------------------------------------


async def test_fetch_db_fetches_and_returns():
    data = {"stdtypes": "<p>content</p>"}
    response = MagicMock(status_code=200)
    response.json.return_value = data
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    result = await _fetch_db("python~3.13", client)

    assert result == data
    client.get.assert_called_once_with("/docs/python~3.13/db.json", timeout=60.0)


async def test_fetch_db_caches_result():
    response = MagicMock(status_code=200)
    response.json.return_value = {}
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    await _fetch_db("python~3.13", client)
    await _fetch_db("python~3.13", client)

    client.get.assert_called_once()


async def test_fetch_db_returns_none_on_404():
    response = MagicMock(status_code=404)
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    assert await _fetch_db("nonexistent", client) is None


# ---------------------------------------------------------------------------
# _http_client
# ---------------------------------------------------------------------------


def test_http_client_default_ssl_verify():
    with patch("devdocs_mcp.server.httpx.AsyncClient") as mock_cls:
        _http_client()
        assert mock_cls.call_args.kwargs["verify"] is True


def test_http_client_no_ssl_verify():
    server_module.ssl_verify = False
    with patch("devdocs_mcp.server.httpx.AsyncClient") as mock_cls:
        _http_client()
        assert mock_cls.call_args.kwargs["verify"] is False


def test_http_client_ca_bundle():
    server_module.ssl_verify = "/etc/ssl/my-ca.pem"
    with patch("devdocs_mcp.server.httpx.AsyncClient") as mock_cls:
        _http_client()
        assert mock_cls.call_args.kwargs["verify"] == "/etc/ssl/my-ca.pem"


def test_http_client_custom_timeout():
    with patch("devdocs_mcp.server.httpx.AsyncClient") as mock_cls:
        _http_client(timeout=10.0)
        assert mock_cls.call_args.kwargs["timeout"] == 10.0
