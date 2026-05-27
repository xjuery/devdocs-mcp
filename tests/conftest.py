import pytest
import devdocs_mcp.server as server_module


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all module-level globals before each test."""
    server_module.allowed_slugs = []
    server_module.doc_metadata = {}
    server_module.doc_indexes = {}
    server_module.doc_databases = {}
    server_module.ssl_verify = True
    yield
    server_module.allowed_slugs = []
    server_module.doc_metadata = {}
    server_module.doc_indexes = {}
    server_module.doc_databases = {}
    server_module.ssl_verify = True
