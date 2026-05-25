# devdocs-mcp

An MCP server that exposes [devdocs.io](https://devdocs.io) documentation to LLMs. Configure which documentation sets to serve at startup; the server handles search and content retrieval on demand.

## Tools

| Tool | Description |
|---|---|
| `list_docs` | List the configured documentation sets with name and version |
| `search` | Search entry names across all (or a specific) configured doc |
| `get_entry` | Fetch a documentation entry as Markdown by doc slug and path |

## Installation from source

**Prerequisites:** [uv](https://docs.astral.sh/uv/getting-started/installation/)

```bash
git clone https://github.com/your-org/devdocs-mcp.git
cd devdocs-mcp
uv sync
```

That's it — `uv sync` creates the virtual environment and installs all dependencies.

## Usage

### Find available doc slugs

```bash
# List all ~800 available slugs
uv run devdocs-mcp --list-slugs

# Filter by name or slug substring
uv run devdocs-mcp --list-slugs python
uv run devdocs-mcp --list-slugs angular
```

### Start the server

**HTTP transport (default)** — streamable-HTTP on `127.0.0.1:8000/mcp`:

```bash
uv run devdocs-mcp --docs python~3.13 javascript
```

**stdio transport** — for direct process-based MCP clients:

```bash
uv run devdocs-mcp --docs python~3.13 javascript --transport stdio
```

### HTTP options

| Flag | Default | Description |
|---|---|---|
| `--host HOST` | `127.0.0.1` | Bind address |
| `--port PORT` | `8000` | Port |
| `--path PATH` | `/mcp` | URL path |
| `--stateless` | off | Disable session tracking (one transport per request) |

```bash
# Public-facing, stateless
uv run devdocs-mcp --docs javascript react --host 0.0.0.0 --port 8080 --stateless
```

## MCP client configuration

### Claude Desktop / Claude Code (stdio)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "devdocs": {
      "command": "/path/to/devdocs-mcp/.venv/bin/devdocs-mcp",
      "args": ["--docs", "python~3.13", "javascript", "--transport", "stdio"]
    }
  }
}
```

Replace `/path/to/devdocs-mcp` with the absolute path to your clone.

### opencode

Add to `opencode.json` (or `opencode.jsonc`) at the root of your project.

**HTTP (recommended)** — start the server separately, then point opencode at it:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "devdocs": {
      "type": "remote",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

**stdio** — opencode spawns the process itself:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "devdocs": {
      "type": "local",
      "command": [
        "/path/to/devdocs-mcp/.venv/bin/devdocs-mcp",
        "--docs", "python~3.13", "javascript",
        "--transport", "stdio"
      ]
    }
  }
}
```

Replace `/path/to/devdocs-mcp` with the absolute path to your clone.

### Other HTTP-based clients

Point the client at:

```
http://127.0.0.1:8000/mcp
```
