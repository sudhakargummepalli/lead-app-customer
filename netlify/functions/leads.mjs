// Lead Desk API for Netlify: the same endpoints as the FastAPI backend
// (app/main.py), with leads stored in Netlify Blobs instead of SQLite.
import { getStore } from "@netlify/blobs";

const STAGES = ["new", "contacted", "qualified", "won", "lost"];
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const LIMITS = { name: 120, phone: 30, email: 254, address: 500, source: 60 };
const KEY = "leads";

class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

const json = (body, status = 200) =>
  new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: body === null ? {} : { "Content-Type": "application/json" },
  });

const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");

// --- storage ------------------------------------------------------------------

const store = () => getStore({ name: "lead-desk", consistency: "strong" });

async function load() {
  const data = await store().get(KEY, { type: "json" });
  return data || { nextId: 1, leads: [] };
}

async function save(data) {
  await store().setJSON(KEY, data);
}

// --- validation ---------------------------------------------------------------

function clean(input, { partial }) {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    throw new ApiError(422, "Request body must be a JSON object");
  }
  const out = {};
  for (const key of ["name", "phone", "email", "address", "status", "source"]) {
    if (input[key] === undefined || input[key] === null) continue;
    let value = String(input[key]).trim();
    if (LIMITS[key] && value.length > LIMITS[key]) {
      throw new ApiError(422, `${key} must be at most ${LIMITS[key]} characters`);
    }
    if (key === "name" && !value) throw new ApiError(422, "Customer name cannot be empty");
    if (key === "email" && value) {
      if (!EMAIL_RE.test(value)) throw new ApiError(422, "Mail ID must look like name@domain.com");
      value = value.toLowerCase();
    }
    if (key === "phone" && value && value.replace(/\D/g, "").length < 7) {
      throw new ApiError(422, "Phone number needs at least 7 digits");
    }
    if (key === "status" && !STAGES.includes(value)) {
      throw new ApiError(422, `Stage must be one of: ${STAGES.join(", ")}`);
    }
    out[key] = value;
  }
  if (!partial) {
    if (!out.name) throw new ApiError(422, "Customer name is required");
    if (!out.phone && !out.email) throw new ApiError(422, "Add a phone number or a mail ID");
  }
  return out;
}

function assertNoDuplicate(leads, email, phone, excludeId) {
  const dup = leads.find(
    (l) =>
      l.id !== excludeId &&
      ((email && l.email.toLowerCase() === email.toLowerCase()) || (phone && l.phone === phone)),
  );
  if (dup) {
    throw new ApiError(409, `A lead with this phone no. or mail ID already exists: ${dup.name} (#${dup.id})`);
  }
}

async function readBody(req) {
  try {
    return await req.json();
  } catch {
    throw new ApiError(422, "Request body must be valid JSON");
  }
}

function findOr404(leads, id) {
  const lead = leads.find((l) => l.id === id);
  if (!lead) throw new ApiError(404, `Lead ${id} not found`);
  return lead;
}

// --- routes -------------------------------------------------------------------

async function route(req) {
  const url = new URL(req.url);
  const parts = url.pathname.replace(/\/+$/, "").split("/").filter(Boolean); // ["api", "leads", ...]
  const method = req.method;

  if (parts[1] === "health") return json({ status: "ok" });
  if (parts[1] !== "leads" || parts.length > 3) throw new ApiError(404, "Not found");

  const sub = parts[2];

  if (!sub) {
    if (method === "GET") {
      const { leads } = await load();
      const q = (url.searchParams.get("q") || "").trim().toLowerCase();
      const status = url.searchParams.get("status");
      if (status && !STAGES.includes(status)) throw new ApiError(422, `Stage must be one of: ${STAGES.join(", ")}`);
      const limit = Math.min(Math.max(parseInt(url.searchParams.get("limit") || "500", 10) || 500, 1), 1000);
      const offset = Math.max(parseInt(url.searchParams.get("offset") || "0", 10) || 0, 0);
      const list = leads
        .filter((l) => !status || l.status === status)
        .filter((l) => !q || [l.name, l.phone, l.email, l.address].join(" ").toLowerCase().includes(q))
        .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
      return json(list.slice(offset, offset + limit));
    }
    if (method === "POST") {
      const lead = clean(await readBody(req), { partial: false });
      const data = await load();
      assertNoDuplicate(data.leads, lead.email, lead.phone);
      const ts = now();
      const created = {
        id: data.nextId,
        name: lead.name,
        phone: lead.phone || "",
        email: lead.email || "",
        address: lead.address || "",
        status: lead.status || "new",
        source: lead.source || "Website",
        created_at: ts,
        updated_at: ts,
      };
      data.leads.push(created);
      data.nextId += 1;
      await save(data);
      return json(created, 201);
    }
    throw new ApiError(405, "Method not allowed");
  }

  if (sub === "stats" && method === "GET") {
    const { leads } = await load();
    const counts = Object.fromEntries(STAGES.map((s) => [s, 0]));
    for (const l of leads) counts[l.status] = (counts[l.status] || 0) + 1;
    return json({ total: leads.length, ...counts });
  }

  const id = Number(sub);
  if (!Number.isInteger(id)) throw new ApiError(422, "Lead id must be a whole number");

  if (method === "GET") {
    const { leads } = await load();
    return json(findOr404(leads, id));
  }
  if (method === "PATCH") {
    const changes = clean(await readBody(req), { partial: true });
    const data = await load();
    const lead = findOr404(data.leads, id);
    if (!Object.keys(changes).length) return json(lead);
    const merged = { ...lead, ...changes };
    if (!merged.phone && !merged.email) throw new ApiError(422, "A lead needs a phone number or a mail ID");
    assertNoDuplicate(data.leads, merged.email, merged.phone, id);
    Object.assign(lead, changes, { updated_at: now() });
    await save(data);
    return json(lead);
  }
  if (method === "DELETE") {
    const data = await load();
    findOr404(data.leads, id);
    data.leads = data.leads.filter((l) => l.id !== id);
    await save(data);
    return json(null, 204);
  }
  throw new ApiError(405, "Method not allowed");
}

export default async (req) => {
  try {
    return await route(req);
  } catch (err) {
    if (err instanceof ApiError) return json({ detail: err.message }, err.status);
    console.error(err);
    return json({ detail: "Internal server error" }, 500);
  }
};

export const config = {
  path: ["/api/health", "/api/leads", "/api/leads/*"],
};
