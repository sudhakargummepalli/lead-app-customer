"""Lead Desk MCP server.

Exposes the CRM leads stored in leads.db as MCP tools over stdio, so an MCP
client (Claude Code, Claude Desktop, ...) can list, search, add, update and
delete customer leads. Uses only the Python standard library and shares the
database with the FastAPI backend (app/database.py).

Run:  python mcp_server.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import DB_PATH, get_conn, init_db  # noqa: E402

SERVER_INFO = {"name": "lead-desk", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"
STAGES = ["new", "contacted", "qualified", "won", "lost"]
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
FIELDS = ["name", "phone", "email", "address", "status", "source"]


class ToolError(Exception):
    """An error the model should see as a failed tool call."""


def log(*args):
    print("[lead-desk]", *args, file=sys.stderr, flush=True)


# --- validation -------------------------------------------------------------

def clean(data: dict) -> dict:
    out = {}
    for key in FIELDS:
        if key not in data or data[key] is None:
            continue
        value = str(data[key]).strip()
        if key == "email" and value:
            if not EMAIL_RE.match(value):
                raise ToolError("Mail ID must look like name@domain.com")
            value = value.lower()
        if key == "phone" and value and len(re.sub(r"\D", "", value)) < 7:
            raise ToolError("Phone number needs at least 7 digits")
        if key == "status" and value not in STAGES:
            raise ToolError(f"Stage must be one of: {', '.join(STAGES)}")
        if key == "name" and not value:
            raise ToolError("Customer name cannot be empty")
        out[key] = value
    return out


def find_duplicate(conn, email, phone, exclude_id=None):
    clauses, params = [], []
    if email:
        clauses.append("lower(email) = lower(?)")
        params.append(email)
    if phone:
        clauses.append("phone = ?")
        params.append(phone)
    if not clauses:
        return None
    sql = f"SELECT id, name FROM leads WHERE ({' OR '.join(clauses)})"
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    return conn.execute(sql, params).fetchone()


def fetch(conn, lead_id):
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    if row is None:
        raise ToolError(f"No lead with id {lead_id}")
    return dict(row)


# --- tools ------------------------------------------------------------------

def list_leads(query=None, status=None, limit=50):
    sql, params = "SELECT * FROM leads WHERE 1=1", []
    if status:
        if status not in STAGES:
            raise ToolError(f"Stage must be one of: {', '.join(STAGES)}")
        sql += " AND status = ?"
        params.append(status)
    if query:
        like = f"%{query.strip().lower()}%"
        sql += " AND (lower(name) LIKE ? OR lower(phone) LIKE ? OR lower(email) LIKE ? OR lower(address) LIKE ?)"
        params += [like] * 4
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with get_conn() as conn:
        leads = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return {"count": len(leads), "leads": leads}


def get_lead(id):
    with get_conn() as conn:
        return fetch(conn, int(id))


def create_lead(**data):
    lead = clean(data)
    if not lead.get("name"):
        raise ToolError("Customer name is required")
    if not lead.get("phone") and not lead.get("email"):
        raise ToolError("Add a phone number or a mail ID")
    with get_conn() as conn:
        dup = find_duplicate(conn, lead.get("email"), lead.get("phone"))
        if dup:
            raise ToolError(f"A lead with this phone no. or mail ID already exists: {dup['name']} (#{dup['id']})")
        cols = ", ".join(lead)
        cur = conn.execute(f"INSERT INTO leads ({cols}) VALUES ({', '.join('?' * len(lead))})", list(lead.values()))
        return fetch(conn, cur.lastrowid)


def update_lead(id, **changes):
    lead_id = int(id)
    data = clean(changes)
    with get_conn() as conn:
        current = fetch(conn, lead_id)
        if not data:
            return current
        merged = {**current, **data}
        if not merged["phone"] and not merged["email"]:
            raise ToolError("A lead needs a phone number or a mail ID")
        dup = find_duplicate(conn, merged["email"], merged["phone"], exclude_id=lead_id)
        if dup:
            raise ToolError(f"A lead with this phone no. or mail ID already exists: {dup['name']} (#{dup['id']})")
        sets = ", ".join(f"{k} = ?" for k in data)
        conn.execute(
            f"UPDATE leads SET {sets}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            [*data.values(), lead_id],
        )
        return fetch(conn, lead_id)


def delete_lead(id):
    with get_conn() as conn:
        lead = fetch(conn, int(id))
        conn.execute("DELETE FROM leads WHERE id = ?", (lead["id"],))
    return {"deleted": True, "id": lead["id"], "name": lead["name"]}


def pipeline_stats():
    with get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM leads GROUP BY status").fetchall()
    counts = {s: 0 for s in STAGES}
    counts.update({r["status"]: r["n"] for r in rows})
    return {"total": sum(counts.values()), **counts}


LEAD_PROPS = {
    "name": {"type": "string", "description": "Customer name"},
    "phone": {"type": "string", "description": "Phone number, e.g. +91 98765 43210"},
    "email": {"type": "string", "description": "Mail ID"},
    "address": {"type": "string", "description": "Postal address"},
    "status": {"type": "string", "enum": STAGES, "description": "Pipeline stage"},
    "source": {"type": "string", "description": "Where the lead came from, e.g. Website, Referral, Walk-in"},
}
ID_PROP = {"id": {"type": "integer", "description": "Lead id"}}

TOOLS = {
    "list_leads": {
        "fn": list_leads,
        "description": "List or search customer leads, newest first. Searches name, phone, mail ID and address.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Text to search for"},
            "status": {"type": "string", "enum": STAGES, "description": "Only leads in this stage"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
        }},
        "annotations": {"readOnlyHint": True},
    },
    "get_lead": {
        "fn": get_lead,
        "description": "Get one customer lead by id.",
        "inputSchema": {"type": "object", "properties": ID_PROP, "required": ["id"]},
        "annotations": {"readOnlyHint": True},
    },
    "create_lead": {
        "fn": create_lead,
        "description": "Add a customer lead. Needs a name and a phone number or mail ID. Refuses a duplicate phone or mail ID.",
        "inputSchema": {"type": "object", "properties": LEAD_PROPS, "required": ["name"]},
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    "update_lead": {
        "fn": update_lead,
        "description": "Change fields of a customer lead, such as its stage or contact details. Only the fields given are changed.",
        "inputSchema": {"type": "object", "properties": {**ID_PROP, **LEAD_PROPS}, "required": ["id"]},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    "delete_lead": {
        "fn": delete_lead,
        "description": "Permanently delete a customer lead by id.",
        "inputSchema": {"type": "object", "properties": ID_PROP, "required": ["id"]},
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
    "pipeline_stats": {
        "fn": pipeline_stats,
        "description": "Count leads in each pipeline stage (new, contacted, qualified, won, lost).",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
}


# --- JSON-RPC / MCP plumbing ------------------------------------------------

def handle(msg: dict):
    method, params = msg.get("method"), msg.get("params") or {}

    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", DEFAULT_PROTOCOL),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": "Tools for the Lead Desk CRM: customer leads with name, phone, mail ID, address and pipeline stage.",
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [
            {"name": n, "description": t["description"], "inputSchema": t["inputSchema"], "annotations": t["annotations"]}
            for n, t in TOOLS.items()
        ]}
    if method == "tools/call":
        tool = TOOLS.get(params.get("name"))
        if tool is None:
            raise RpcError(-32602, f"Unknown tool: {params.get('name')}")
        args = params.get("arguments") or {}
        allowed = set(tool["inputSchema"]["properties"])
        unknown = set(args) - allowed
        try:
            if unknown:
                raise ToolError(f"Unknown argument(s): {', '.join(sorted(unknown))}")
            result = tool["fn"](**args)
        except (ToolError, ValueError, TypeError) as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "structuredContent": result,
        }
    raise RpcError(-32601, f"Method not found: {method}")


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    init_db()
    log(f"ready, database: {DB_PATH}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        is_request = "id" in msg and "method" in msg
        try:
            result = handle(msg) if "method" in msg else None
            if is_request:
                send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
        except RpcError as e:
            if is_request:
                send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": e.code, "message": str(e)}})
        except Exception as e:  # keep the server alive on unexpected errors
            log("error:", repr(e))
            if is_request:
                send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": "Internal error"}})


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    main()
