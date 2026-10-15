"""Lead Desk backend: a REST API that stores CRM customer leads in SQLite."""
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse

from .database import get_conn, init_db
from .schemas import Lead, LeadCreate, LeadUpdate, PipelineStats, Status

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Lead Desk API", version="1.0.0")


@app.on_event("startup")
def startup() -> None:
    init_db()


def _row_to_lead(row) -> Lead:
    return Lead(**dict(row))


def _find_duplicate(conn, email: str, phone: str, exclude_id: Optional[int] = None):
    """Return an existing lead with the same mail ID or phone number, if any."""
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


def _get_or_404(conn, lead_id: int):
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    return row


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/leads", response_model=List[Lead])
def list_leads(
    q: Optional[str] = Query(None, description="Search name, phone, mail ID or address"),
    status: Optional[Status] = None,
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    sql, params = "SELECT * FROM leads WHERE 1=1", []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if q:
        like = f"%{q.strip().lower()}%"
        sql += " AND (lower(name) LIKE ? OR lower(phone) LIKE ? OR lower(email) LIKE ? OR lower(address) LIKE ?)"
        params += [like] * 4
    sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with get_conn() as conn:
        return [_row_to_lead(r) for r in conn.execute(sql, params).fetchall()]


@app.get("/api/leads/stats", response_model=PipelineStats)
def pipeline_stats():
    with get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM leads GROUP BY status").fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    return PipelineStats(total=sum(counts.values()), **counts)


@app.get("/api/leads/{lead_id}", response_model=Lead)
def get_lead(lead_id: int):
    with get_conn() as conn:
        return _row_to_lead(_get_or_404(conn, lead_id))


@app.post("/api/leads", response_model=Lead, status_code=201)
def create_lead(lead: LeadCreate):
    with get_conn() as conn:
        dup = _find_duplicate(conn, lead.email, lead.phone)
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"A lead with this phone no. or mail ID already exists: {dup['name']} (#{dup['id']})",
            )
        cur = conn.execute(
            "INSERT INTO leads (name, phone, email, address, status, source) VALUES (?, ?, ?, ?, ?, ?)",
            (lead.name, lead.phone, lead.email, lead.address, lead.status, lead.source),
        )
        return _row_to_lead(_get_or_404(conn, cur.lastrowid))


@app.patch("/api/leads/{lead_id}", response_model=Lead)
def update_lead(lead_id: int, changes: LeadUpdate):
    data = changes.model_dump(exclude_unset=True)
    with get_conn() as conn:
        current = dict(_get_or_404(conn, lead_id))
        if not data:
            return Lead(**current)
        merged = {**current, **data}
        if not merged["phone"] and not merged["email"]:
            raise HTTPException(status_code=422, detail="A lead needs a phone number or a mail ID")
        dup = _find_duplicate(conn, merged["email"], merged["phone"], exclude_id=lead_id)
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"A lead with this phone no. or mail ID already exists: {dup['name']} (#{dup['id']})",
            )
        sets = ", ".join(f"{k} = ?" for k in data)
        conn.execute(
            f"UPDATE leads SET {sets}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            [*data.values(), lead_id],
        )
        return _row_to_lead(_get_or_404(conn, lead_id))


@app.delete("/api/leads/{lead_id}", status_code=204)
def delete_lead(lead_id: int):
    with get_conn() as conn:
        _get_or_404(conn, lead_id)
        conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
