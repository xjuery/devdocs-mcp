#!/usr/bin/env python3
"""DevDocs MCP Server — provides access to devdocs.io documentation."""

import argparse
import asyncio
import json
import sys
from typing import Annotated

import html2text
import httpx
from fastmcp import FastMCP
from pydantic import Field

DEVDOCS_BASE = "https://devdocs.io"
FETCH_TIMEOUT = 60.0


# ssl_verify: True = system CAs (default), False = no verification, str = path to CA bundle
ssl_verify: bool | str = True


def _http_client(timeout: float = FETCH_TIMEOUT) -> httpx.AsyncClient:
    # trust_env=True picks up HTTP_PROXY, HTTPS_PROXY, http_proxy, https_proxy
    return httpx.AsyncClient(
        base_url=DEVDOCS_BASE, 
        follow_redirects=True, 
        trust_env=True, 
        timeout=timeout, 
        verify=ssl_verify
    )

mcp = FastMCP("devdocs-mcp")

# Runtime state populated on startup
allowed_slugs: list[str] = []
doc_metadata: dict[str, dict] = {}
doc_indexes: dict[str, dict] = {}
doc_databases: dict[str, dict] = {}

_html = html2text.HTML2Text()
_html.ignore_links = False
_html.ignore_images = True
_html.body_width = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_index(slug: str, client: httpx.AsyncClient) -> dict | None:
    if slug not in doc_indexes:
        r = await client.get(f"/docs/{slug}/index.json", timeout=FETCH_TIMEOUT)
        if r.status_code != 200:
            return None
        doc_indexes[slug] = r.json()
    return doc_indexes[slug]


async def _fetch_db(slug: str, client: httpx.AsyncClient) -> dict | None:
    if slug not in doc_databases:
        r = await client.get(f"/docs/{slug}/db.json", timeout=FETCH_TIMEOUT)
        if r.status_code != 200:
            return None
        doc_databases[slug] = r.json()
    return doc_databases[slug]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_docs() -> str:
    """List the documentation sets available on this server. Returns slugs, human-readable names, and version info."""
    rows = []
    for slug in allowed_slugs:
        meta = doc_metadata.get(slug, {})
        rows.append({
            "slug": slug,
            "name": meta.get("name", slug),
            "version": meta.get("version", ""),
            "release": meta.get("release", ""),
        })
    return json.dumps(rows, indent=2)


@mcp.tool()
async def search(
    query: Annotated[str, Field(description="Case-insensitive substring to search for in entry names.")],
    doc: Annotated[str | None, Field(description="Restrict search to this doc slug (e.g. 'python~3.13'). Omit to search all.")] = None,
    limit: Annotated[int, Field(description="Maximum number of results to return (default 20, max 100).")] = 20,
) -> str:
    """Search documentation entry names across configured docs. Returns matches with their doc slug, type category, and path — use get_entry to fetch content."""
    async with _http_client() as client:
        query_lower = query.lower()
        limit = min(limit, 100)

        if doc and doc not in allowed_slugs:
            return f"Error: '{doc}' is not in the allowed docs list."

        slugs = [doc] if doc else allowed_slugs
        results: list[dict] = []

        for slug in slugs:
            index = await _fetch_index(slug, client)
            if index is None:
                continue
            for entry in index.get("entries", []):
                if query_lower in entry["name"].lower():
                    results.append({
                        "doc": slug,
                        "name": entry["name"],
                        "type": entry.get("type", ""),
                        "path": entry["path"],
                    })
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break

        if not results:
            return "No entries found matching your query."
        return json.dumps(results, indent=2)


@mcp.tool()
async def get_entry(
    doc: Annotated[str, Field(description="Doc slug (e.g. 'python~3.13', 'angular~20').")],
    path: Annotated[str, Field(description="Entry path as returned by search (may include a # fragment).")],
) -> str:
    """Fetch the full documentation content of a specific entry as Markdown. Use the doc slug and path returned by search."""
    if doc not in allowed_slugs:
        return f"Error: '{doc}' is not in the allowed docs list."

    async with _http_client() as client:
        db_key = path.split("#")[0]

        db = await _fetch_db(doc, client)
        if db is None:
            return f"Error: could not fetch content database for '{doc}'."

        html = db.get(db_key)
        if html is None:
            alt = db_key.rstrip("/")
            html = db.get(alt) or db.get(alt + "/")

        if html is None:
            available = [k for k in db if db_key.split("/")[-1] in k][:5]
            hint = f" Similar paths: {available}" if available else ""
            return f"Error: path '{db_key}' not found in '{doc}'.{hint}"

        return _html.handle(html).strip()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _list_available_slugs(filter_: str | None) -> None:
    """Fetch docs.json and print all available slugs to stdout, then exit."""
    try:
        async with _http_client(timeout=30.0) as client:
            r = await client.get("/docs.json")
            r.raise_for_status()
            docs = r.json()
    except Exception as exc:
        print(f"Error fetching docs list: {exc}", file=sys.stderr)
        sys.exit(1)

    if filter_:
        needle = filter_.lower()
        docs = [d for d in docs if needle in d["slug"].lower() or needle in d["name"].lower()]

    col = max((len(d["slug"]) for d in docs), default=0)
    for d in sorted(docs, key=lambda d: d["slug"]):
        version = f"  ({d['version']})" if d.get("version") else ""
        print(f"{d['slug']:<{col}}  {d['name']}{version}")


async def _prefetch_metadata() -> None:
    """Populate doc_metadata from devdocs.io/docs.json for the allowed slugs."""
    try:
        async with _http_client(timeout=30.0) as client:
            r = await client.get("/docs.json")
            if r.status_code == 200:
                for doc in r.json():
                    if doc["slug"] in allowed_slugs:
                        doc_metadata[doc["slug"]] = doc
                unknown = [s for s in allowed_slugs if s not in doc_metadata]
                if unknown:
                    print(f"Warning: slugs not found on devdocs.io: {unknown}", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: could not fetch docs.json: {exc}", file=sys.stderr)


def main_sync() -> None:
    parser = argparse.ArgumentParser(
        description="DevDocs MCP Server — expose devdocs.io documentation via MCP."
    )
    parser.add_argument(
        "--docs",
        nargs="+",
        metavar="SLUG",
        help=(
            "One or more devdocs.io doc slugs to expose "
            "(e.g. --docs python~3.13 angular~20 javascript). "
            "Use the exact slug from https://devdocs.io/docs.json."
        ),
    )
    parser.add_argument(
        "--list-slugs",
        nargs="?",
        const="",
        metavar="FILTER",
        help=(
            "Print all available devdocs.io slugs and exit. "
            "Pass an optional substring to filter by name or slug "
            "(e.g. --list-slugs python)."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="http",
        help="Transport to use: 'http' (default, streamable-HTTP) or 'stdio'.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind when using --transport http (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind when using --transport http (default: 8000).",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        metavar="PATH",
        help="HTTP transport only: URL path to serve on (default: /mcp).",
    )
    parser.add_argument(
        "--stateless",
        action="store_true",
        help=(
            "HTTP transport only: disable session tracking. "
            "Each request is handled independently with no shared state."
        ),
    )
    ssl_group = parser.add_mutually_exclusive_group()
    ssl_group.add_argument(
        "--no-ssl-verify",
        action="store_true",
        help="Disable SSL certificate verification (insecure, use only when necessary).",
    )
    ssl_group.add_argument(
        "--ssl-ca-bundle",
        metavar="PATH",
        help="Path to a CA certificate bundle file to use for SSL verification.",
    )
    args = parser.parse_args()

    if args.list_slugs is not None:
        asyncio.run(_list_available_slugs(args.list_slugs or None))
        return

    if not args.docs:
        parser.error("--docs is required when not using --list-slugs")

    global allowed_slugs, ssl_verify
    allowed_slugs = args.docs
    if args.no_ssl_verify:
        ssl_verify = False
    elif args.ssl_ca_bundle:
        ssl_verify = args.ssl_ca_bundle

    asyncio.run(_prefetch_metadata())

    if args.transport == "http":
        print(f"DevDocs MCP server listening on http://{args.host}:{args.port}{args.path}", file=sys.stderr)
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            path=args.path,
            stateless_http=args.stateless,
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main_sync()
