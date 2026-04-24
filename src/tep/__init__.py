"""Trust Evidence Protocol core primitives."""

from .crypto import AgentIdentity, generate_agent_identity
from .ids import ledger_id, new_id
from .indexes import IndexService
from .jsoncanon import canonical_bytes, canonical_dumps, canonical_hash
from .ledger import Ledger, LedgerAppendResult, LedgerValidation
from .mcp_adapter import MCPAdapter, MCPToolSpec
from .http_server import TEPHTTPApp, make_app
from .ingest import document_kind_for_path, ingest_file_payload, ingest_text_payload
from .project_context import ProjectPointer, init_project_pointer, read_project_pointer, write_project_pointer
from .responses import RuntimeResponse
from .runtime import Runtime
from .secrets import classify_secrets, decrypt_text, encrypt_text, has_secrets
from .stdio_server import TEPStdioApp, make_stdio_app
from .storage import TEPHome

__all__ = [
    "AgentIdentity",
    "IndexService",
    "Ledger",
    "LedgerAppendResult",
    "LedgerValidation",
    "MCPAdapter",
    "MCPToolSpec",
    "ProjectPointer",
    "Runtime",
    "RuntimeResponse",
    "TEPHTTPApp",
    "TEPStdioApp",
    "TEPHome",
    "canonical_bytes",
    "canonical_dumps",
    "canonical_hash",
    "classify_secrets",
    "decrypt_text",
    "document_kind_for_path",
    "encrypt_text",
    "generate_agent_identity",
    "has_secrets",
    "init_project_pointer",
    "ingest_file_payload",
    "ingest_text_payload",
    "ledger_id",
    "make_app",
    "make_stdio_app",
    "new_id",
    "read_project_pointer",
    "write_project_pointer",
]
