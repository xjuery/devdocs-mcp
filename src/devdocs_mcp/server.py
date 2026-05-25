#!/usr/bin/env python3
"""DevDocs MCP Server — provides access to devdocs.io documentation via stdio."""

import argparse
import asyncio
import json
import sys
from typing import Any

import html2text
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

DEVDOCS_BASE = "https://devdocs.io"
FETCH_TIMEOUT = 60.0

server = Server("devdocs-mcp")

# Runtime state populated on startup
allowed_slugs: list[str] = []
doc_metadata: dict[str, dict] = {}   # slug -> entry from docs.json
doc_indexes: dict[str, dict] = {}    # slug -> index.json (cached)
doc_databases: dict[str, dict] = {}  # slug -> db.json  (cached, large)

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


def _text(content: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=content)]


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_docs",
            description=(
                "List the documentation sets available on this server. "
                "Returns slugs, human-readable names, and version info."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="search",
            description=(
                "Search documentation entry names across configured docs. "
                "Returns a list of matches with their doc slug, type category, "
                "and path — use get_entry to fetch the actual content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Case-insensitive substring to search for in entry names.",
                    },
                    "doc": {
                        "type": "string",
                        "description": "Restrict search to this doc slug (e.g. 'python~3.13'). Omit to search all.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 20, max 100).",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_entry",
            description=(
                "Fetch the full documentation content of a specific entry as Markdown. "
                "Use the doc slug and path returned by search."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "doc": {
                        "type": "string",
                        "description": "Doc slug (e.g. 'python~3.13', 'angular~20').",
                    },
                    "path": {
                        "type": "string",
                        "description": "Entry path as returned by search (may include a # fragment).",
                    },
                },
                "required": ["doc", "path"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    async with httpx.AsyncClient(base_url=DEVDOCS_BASE, follow_redirects=True) as client:

        # -- list_docs -------------------------------------------------------
        if name == "list_docs":
            rows = []
            for slug in allowed_slugs:
                meta = doc_metadata.get(slug, {})
                rows.append({
                    "slug": slug,
                    "name": meta.get("name", slug),
                    "version": meta.get("version", ""),
                    "release": meta.get("release", ""),
                })
            return _text(json.dumps(rows, indent=2))

        # -- search ----------------------------------------------------------
        elif name == "search":
            query = arguments["query"].lower()
            doc_filter: str | None = arguments.get("doc")
            limit = min(int(arguments.get("limit", 20)), 100)

            if doc_filter and doc_filter not in allowed_slugs:
                return _text(f"Error: '{doc_filter}' is not in the allowed docs list.")

            slugs = [doc_filter] if doc_filter else allowed_slugs
            results: list[dict] = []

            for slug in slugs:
                index = await _fetch_index(slug, client)
                if index is None:
                    continue
                for entry in index.get("entries", []):
                    if query in entry["name"].lower():
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
                return _text("No entries found matching your query.")
            return _text(json.dumps(results, indent=2))

        # -- get_entry -------------------------------------------------------
        elif name == "get_entry":
            doc = arguments["doc"]
            path = arguments["path"]

            if doc not in allowed_slugs:
                return _text(f"Error: '{doc}' is not in the allowed docs list.")

            # db.json keys never include the # fragment
            db_key = path.split("#")[0]

            db = await _fetch_db(doc, client)
            if db is None:
                return _text(f"Error: could not fetch content database for '{doc}'.")

            html = db.get(db_key)
            if html is None:
                # Try without trailing slash variations
                alt = db_key.rstrip("/")
                html = db.get(alt) or db.get(alt + "/")

            if html is None:
                available = [k for k in db if db_key.split("/")[-1] in k][:5]
                hint = f" Similar paths: {available}" if available else ""
                return _text(f"Error: path '{db_key}' not found in '{doc}'.{hint}")

            markdown = _html.handle(html)
            return _text(markdown.strip())

        return _text(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _list_available_slugs(filter_: str | None) -> None:
    """Fetch docs.json and print all available slugs to stdout, then exit."""
    try:
        async with httpx.AsyncClient(base_url=DEVDOCS_BASE, timeout=30.0, follow_redirects=True) as client:
            r = await client.get("/docs.json")
            r.raise_for_status()
            docs = r.json()
    except Exception as exc:
        print(f"Error fetching docs list: {exc}", file=sys.stderr)
        sys.exit(1)

    if filter_:
        needle = filter_.lower()
        docs = [d for d in docs if needle in d["slug"].lower() or needle in d["name"].lower()]

    # Align columns for readability
    col = max((len(d["slug"]) for d in docs), default=0)
    for d in sorted(docs, key=lambda d: d["slug"]):
        version = f"  ({d['version']})" if d.get("version") else ""
        print(f"{d['slug']:<{col}}  {d['name']}{version}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="DevDocs MCP Server — expose devdocs.io documentation via MCP stdio."
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
    args = parser.parse_args()

    if args.list_slugs is not None:
        await _list_available_slugs(args.list_slugs or None)
        return

    if not args.docs:
        parser.error("--docs is required when not using --list-slugs")

    global allowed_slugs
    allowed_slugs = args.docs

    # Pre-fetch docs.json to populate human-readable metadata
    try:
        async with httpx.AsyncClient(base_url=DEVDOCS_BASE, timeout=30.0, follow_redirects=True) as client:
            r = await client.get("/docs.json")
            if r.status_code == 200:
                for doc in r.json():
                    if doc["slug"] in allowed_slugs:
                        doc_metadata[doc["slug"]] = doc
                unknown = [s for s in allowed_slugs if s not in doc_metadata]
                if unknown:
                    print(
                        f"Warning: these slugs were not found in devdocs.io: {unknown}",
                        file=sys.stderr,
                    )
    except Exception as exc:
        print(f"Warning: could not fetch docs.json: {exc}", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main_sync() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
