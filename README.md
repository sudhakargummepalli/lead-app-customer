# Lead Desk backend

A FastAPI + SQLite backend that stores CRM customer leads (name, phone no., mail ID, address, stage, source) and serves the Lead Desk page.

## Run it

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000 for the page, or http://127.0.0.1:8000/docs for the interactive API docs.

Leads are saved in `leads.db` in this folder. Set the `LEADS_DB` environment variable to use a different file.

## API

| Method | Path | What it does |
|---|---|---|
| GET | `/api/leads?q=&status=&limit=&offset=` | List leads, newest first. `q` searches name, phone, mail ID and address. |
| GET | `/api/leads/stats` | Count of leads in each pipeline stage. |
| GET | `/api/leads/{id}` | One lead. |
| POST | `/api/leads` | Create a lead. Needs a name and a phone no. or mail ID. |
| PATCH | `/api/leads/{id}` | Change some fields of a lead. |
| DELETE | `/api/leads/{id}` | Delete a lead. |

Stages: `new`, `contacted`, `qualified`, `won`, `lost`.

Validation: mail IDs must look like `name@domain.com` and are stored in lowercase, phone numbers need at least 7 digits, and a second lead with the same phone no. or mail ID is refused with `409 Conflict`.

## MCP server

`mcp_server.py` is a local MCP server (stdio) that lets Claude or any MCP client work with the same `leads.db`. It needs only the Python standard library.

Tools: `list_leads`, `get_lead`, `create_lead`, `update_lead`, `delete_lead`, `pipeline_stats`.

**Claude Code:** `.mcp.json` in this folder registers it as `lead-desk`. Open Claude Code in this folder and approve the server when asked, or add it yourself:

```powershell
claude mcp add lead-desk -- python C:\full\path\to\lead-desk-backend\mcp_server.py
```

**Claude Desktop:** add this to `claude_desktop_config.json` (use the full path):

```json
{ "mcpServers": { "lead-desk": { "command": "python", "args": ["C:\\full\\path\\to\\lead-desk-backend\\mcp_server.py"] } } }
```

## Tests

```powershell
.venv\Scripts\python -m pytest
```
