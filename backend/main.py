from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os, hashlib, json

app = FastAPI(
    title="Nagarik — Civic Intelligence Platform",
    description="AI-first civic reporting and escalation backend",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Civic Categories ────────────────────────────────────────────────────────
CIVIC_CATEGORIES = {
    "roads":        {"dept": "PWD",                  "sla_hours": 72,  "label": "Roads & Potholes"},
    "water":        {"dept": "Jal Board",             "sla_hours": 24,  "label": "Water Supply"},
    "garbage":      {"dept": "Municipal Corporation", "sla_hours": 48,  "label": "Garbage Collection"},
    "electricity":  {"dept": "DISCOM",                "sla_hours": 12,  "label": "Street Lights / Power"},
    "sewage":       {"dept": "Municipal Corporation", "sla_hours": 48,  "label": "Drainage & Sewage"},
    "encroachment": {"dept": "Revenue Department",    "sla_hours": 96,  "label": "Encroachment"},
    "parks":        {"dept": "Parks Department",      "sla_hours": 72,  "label": "Parks & Public Spaces"},
}

ESCALATION_MATRIX = {
    "roads":        {"L1": "Ward Officer",       "L2": "Circle Officer",    "L3": "Commissioner"},
    "water":        {"L1": "Jal Board AE",        "L2": "Jal Board EE",      "L3": "MD Jal Board"},
    "garbage":      {"L1": "Sanitation Inspector","L2": "Zonal Officer",     "L3": "Commissioner"},
    "electricity":  {"L1": "DISCOM JE",           "L2": "DISCOM AE",         "L3": "Superintending Engg"},
    "sewage":       {"L1": "Sanitation Inspector","L2": "Zonal Officer",     "L3": "Commissioner"},
    "encroachment": {"L1": "Revenue Inspector",   "L2": "Tehsildar",         "L3": "SDM"},
    "parks":        {"L1": "Parks Inspector",     "L2": "Zonal Officer",     "L3": "Commissioner"},
}

# In-memory store (replace with PostgreSQL in production)
issues_db: List[dict] = []
polls_db:  List[dict] = []
issue_counter = 1000

# ── Models ──────────────────────────────────────────────────────────────────
class IssueCreate(BaseModel):
    title:          Optional[str] = None
    description:    Optional[str] = None
    category_id:    str
    city_id:        str = "mumbai"
    ward:           Optional[str] = None
    address:        Optional[str] = None
    geo_lat:        Optional[float] = None
    geo_lng:        Optional[float] = None
    photo_urls:     Optional[List[str]] = []
    reporter_phone: Optional[str] = None
    source:         str = "app"

class IssueStatusUpdate(BaseModel):
    status:             str
    resolution_remarks: Optional[str] = None
    proof_photo_url:    Optional[str] = None

class PollCreate(BaseModel):
    title:       str
    description: Optional[str] = None
    city_id:     str = "mumbai"
    ward:        Optional[str] = None
    options:     List[str]
    ends_at:     Optional[str] = None

class WhatsAppMessage(BaseModel):
    mobile:  Optional[str] = None
    type:    Optional[str] = None
    message: Optional[dict] = None

# ── Helpers ─────────────────────────────────────────────────────────────────
def hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()

def compute_urgency(issue: dict) -> int:
    cat = CIVIC_CATEGORIES.get(issue["category_id"], {})
    sla_hours = cat.get("sla_hours", 72)
    created = datetime.fromisoformat(issue["created_at"])
    elapsed = (datetime.utcnow() - created).total_seconds() / 3600
    sla_ratio   = min(elapsed / sla_hours, 2)
    sla_score   = sla_ratio * 50
    dup_score   = min(issue.get("duplicate_count", 0) * 7, 35)
    vote_score  = min(issue.get("upvote_count", 0) * 1.5, 15)
    return round(min(sla_score + dup_score + vote_score, 100))

def get_escalation_level(issue: dict) -> dict:
    cat = CIVIC_CATEGORIES.get(issue["category_id"], {})
    sla_hours = cat.get("sla_hours", 72)
    created = datetime.fromisoformat(issue["created_at"])
    elapsed = (datetime.utcnow() - created).total_seconds() / 3600
    matrix = ESCALATION_MATRIX.get(issue["category_id"], {})
    if elapsed > sla_hours * 2: return {"level": "L3", "role": matrix.get("L3", "Commissioner")}
    if elapsed > sla_hours:     return {"level": "L2", "role": matrix.get("L2", "Circle Officer")}
    return                             {"level": "L1", "role": matrix.get("L1", "Ward Officer")}

def make_public_id(counter: int) -> str:
    return f"NGK-{counter}"

# ── Root & Health ────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "nagarik-backend",
        "platform": "Nagarik Civic Intelligence Platform",
        "status": "running",
        "version": "1.0.0",
        "run_mode": os.getenv("RUN_MODE", "api"),
        "tagline": "Civic Visibility. Smarter Cities."
    }

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "issues_total": len(issues_db),
        "polls_total": len(polls_db),
        "timestamp": datetime.utcnow().isoformat()
    }

# ── Categories ───────────────────────────────────────────────────────────────
@app.get("/api/categories")
def get_categories():
    return {"categories": [
        {"id": k, **v, "escalation": ESCALATION_MATRIX.get(k, {})}
        for k, v in CIVIC_CATEGORIES.items()
    ]}

# ── Issues ───────────────────────────────────────────────────────────────────
@app.post("/api/issues")
def create_issue(body: IssueCreate, background_tasks: BackgroundTasks):
    global issue_counter
    issue_counter += 1

    if body.category_id not in CIVIC_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category: {body.category_id}")

    cat = CIVIC_CATEGORIES[body.category_id]
    now = datetime.utcnow().isoformat()

    issue = {
        "id":               issue_counter,
        "public_id":        make_public_id(issue_counter),
        "title":            body.title or cat["label"],
        "description":      body.description,
        "category_id":      body.category_id,
        "dept":             cat["dept"],
        "city_id":          body.city_id,
        "ward":             body.ward,
        "address":          body.address,
        "geo_lat":          body.geo_lat,
        "geo_lng":          body.geo_lng,
        "photo_urls":       body.photo_urls or [],
        "status":           "open",
        "escalation_level": "L1",
        "escalation_role":  ESCALATION_MATRIX.get(body.category_id, {}).get("L1", "Ward Officer"),
        "urgency_score":    0,
        "duplicate_count":  0,
        "upvote_count":     0,
        "reporter_hash":    hash_phone(body.reporter_phone) if body.reporter_phone else None,
        "source":           body.source,
        "created_at":       now,
        "updated_at":       now,
    }

    # Compute initial urgency
    issue["urgency_score"] = compute_urgency(issue)
    issues_db.append(issue)

    # Background: forward to dept (placeholder)
    background_tasks.add_task(forward_to_dept, issue)

    return {
        "success": True,
        "issue": issue,
        "tracking_url": f"https://nagarik.care/t/{issue_counter}",
        "message": f"Issue reported successfully! Forwarded to {cat['dept']}."
    }

@app.get("/api/issues")
def list_issues(
    city_id:     Optional[str] = None,
    category_id: Optional[str] = None,
    status:      Optional[str] = None,
    ward:        Optional[str] = None,
    limit:       int = 50,
    offset:      int = 0
):
    results = issues_db.copy()
    if city_id:     results = [i for i in results if i.get("city_id") == city_id]
    if category_id: results = [i for i in results if i.get("category_id") == category_id]
    if status:      results = [i for i in results if i.get("status") == status]
    if ward:        results = [i for i in results if i.get("ward") == ward]

    # Update urgency scores
    for issue in results:
        issue["urgency_score"] = compute_urgency(issue)

    # Sort by urgency desc
    results.sort(key=lambda x: x["urgency_score"], reverse=True)
    return {"issues": results[offset:offset+limit], "total": len(results)}

@app.get("/api/issues/{issue_id}")
def get_issue(issue_id: int):
    issue = next((i for i in issues_db if i["id"] == issue_id), None)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    issue["urgency_score"] = compute_urgency(issue)
    issue["escalation"]    = get_escalation_level(issue)
    return issue

@app.patch("/api/issues/{issue_id}/status")
def update_issue_status(issue_id: int, body: IssueStatusUpdate):
    issue = next((i for i in issues_db if i["id"] == issue_id), None)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue["status"]     = body.status
    issue["updated_at"] = datetime.utcnow().isoformat()
    if body.resolution_remarks: issue["resolution_remarks"] = body.resolution_remarks
    if body.proof_photo_url:    issue["proof_photo_url"]    = body.proof_photo_url
    if body.status == "resolved":
        issue["resolved_at"] = datetime.utcnow().isoformat()

    return {"success": True, "issue": issue}

@app.post("/api/issues/{issue_id}/upvote")
def upvote_issue(issue_id: int, voter_hash: str):
    issue = next((i for i in issues_db if i["id"] == issue_id), None)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    issue["upvote_count"] = issue.get("upvote_count", 0) + 1
    issue["urgency_score"] = compute_urgency(issue)
    return {"success": True, "upvote_count": issue["upvote_count"], "urgency_score": issue["urgency_score"]}

# ── Escalation ────────────────────────────────────────────────────────────────
@app.post("/api/escalation/run")
def run_escalation():
    """Called by hourly cron job"""
    escalated = []
    for issue in issues_db:
        if issue["status"] not in ["open", "in_progress"]:
            continue
        current = get_escalation_level(issue)
        if current["level"] != issue.get("escalation_level", "L1"):
            issue["escalation_level"] = current["level"]
            issue["escalation_role"]  = current["role"]
            issue["updated_at"]       = datetime.utcnow().isoformat()
            escalated.append({
                "issue_id":   issue["id"],
                "public_id":  issue["public_id"],
                "to_level":   current["level"],
                "to_role":    current["role"],
                "reason":     "SLA breached — auto-escalated"
            })
    return {"escalated": escalated, "count": len(escalated), "checked": len(issues_db)}

@app.get("/api/issues/{issue_id}/urgency")
def get_urgency(issue_id: int):
    issue = next((i for i in issues_db if i["id"] == issue_id), None)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {
        "urgency_score":    compute_urgency(issue),
        "escalation":       get_escalation_level(issue),
        "duplicate_count":  issue.get("duplicate_count", 0),
        "upvote_count":     issue.get("upvote_count", 0),
    }

# ── Civic Health Score ────────────────────────────────────────────────────────
@app.get("/api/health-score/{city_id}")
def get_civic_health_score(city_id: str, ward: Optional[str] = None):
    city_issues = [i for i in issues_db if i.get("city_id") == city_id]
    if ward:
        city_issues = [i for i in city_issues if i.get("ward") == ward]

    if not city_issues:
        return {"city_id": city_id, "ward": ward, "score": 0, "message": "No issues found"}

    resolved   = [i for i in city_issues if i.get("status") == "resolved"]
    resolution_rate   = len(resolved) / len(city_issues) if city_issues else 0

    # Avg resolution time (hours)
    resolve_times = []
    for i in resolved:
        if i.get("resolved_at"):
            created  = datetime.fromisoformat(i["created_at"])
            resolv   = datetime.fromisoformat(i["resolved_at"])
            resolve_times.append((resolv - created).total_seconds() / 3600)
    avg_resolution_hours = sum(resolve_times) / len(resolve_times) if resolve_times else 999

    # Score: resolution_rate 50% + speed 30% + repeat 20% (simplified)
    speed_score = max(0, 100 - (avg_resolution_hours / 2))
    score = round((resolution_rate * 50) + (speed_score * 0.30) + 20)
    score = min(100, max(0, score))

    return {
        "city_id":             city_id,
        "ward":                ward,
        "score":               score,
        "total_issues":        len(city_issues),
        "resolved":            len(resolved),
        "resolution_rate":     round(resolution_rate * 100, 1),
        "avg_resolution_hours": round(avg_resolution_hours, 1),
        "computed_at":         datetime.utcnow().isoformat()
    }

# ── Polls ─────────────────────────────────────────────────────────────────────
@app.post("/api/polls")
def create_poll(body: PollCreate):
    poll_id = len(polls_db) + 1
    poll = {
        "id":          poll_id,
        "title":       body.title,
        "description": body.description,
        "city_id":     body.city_id,
        "ward":        body.ward,
        "ends_at":     body.ends_at,
        "status":      "active",
        "options":     [{"id": i+1, "text": opt, "votes": 0} for i, opt in enumerate(body.options)],
        "created_at":  datetime.utcnow().isoformat()
    }
    polls_db.append(poll)
    return {"success": True, "poll": poll}

@app.get("/api/polls")
def list_polls(city_id: Optional[str] = None, ward: Optional[str] = None):
    results = polls_db.copy()
    if city_id: results = [p for p in results if p.get("city_id") == city_id]
    if ward:    results = [p for p in results if p.get("ward") == ward]
    return {"polls": results, "total": len(results)}

@app.post("/api/polls/{poll_id}/vote")
def vote_poll(poll_id: int, option_id: int, voter_hash: str):
    poll = next((p for p in polls_db if p["id"] == poll_id), None)
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    option = next((o for o in poll["options"] if o["id"] == option_id), None)
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")
    option["votes"] += 1
    return {"success": True, "poll": poll}

# ── WhatsApp Webhook ──────────────────────────────────────────────────────────
whatsapp_sessions: dict = {}

@app.post("/api/whatsapp/incoming")
async def whatsapp_incoming(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    background_tasks.add_task(process_whatsapp, body)
    return {"status": "ok"}

async def process_whatsapp(body: dict):
    phone = body.get("mobile") or ""
    msg   = body.get("message", {})
    mtype = body.get("type", "text")
    text  = msg.get("text", "")

    session = whatsapp_sessions.get(phone, {"step": "idle"})

    if mtype == "image":
        whatsapp_sessions[phone] = {"step": "awaiting_location", "imageUrl": msg.get("url")}
        print(f"[WhatsApp→{phone}]: Got photo. Asking for location.")
        return

    if session.get("step") == "awaiting_location":
        lat = msg.get("latitude"); lng = msg.get("longitude")
        location = {"lat": lat, "lng": lng} if lat else {"address": text}
        cat = get_category_by_keyword(text)
        whatsapp_sessions[phone] = {**session, "step": "awaiting_confirmation",
                                    "location": location, "category": cat}
        print(f"[WhatsApp→{phone}]: Location received. Category: {cat}. Asking confirm.")
        return

    if session.get("step") == "awaiting_confirmation":
        if text.strip() in ["1", "yes", "YES"]:
            sess = whatsapp_sessions.get(phone, {})
            cat_id = sess.get("category", "roads")
            cat = CIVIC_CATEGORIES.get(cat_id, {})
            global issue_counter
            issue_counter += 1
            print(f"[WhatsApp→{phone}]: Issue #NGK-{issue_counter} created. Dept: {cat.get('dept')}")
            whatsapp_sessions.pop(phone, None)
        elif text.strip() == "2":
            whatsapp_sessions[phone] = {**session, "step": "selecting_category"}
        return

    if session.get("step") == "selecting_category":
        cats = list(CIVIC_CATEGORIES.keys())
        try:
            idx = int(text.strip()) - 1
            if 0 <= idx < len(cats):
                whatsapp_sessions[phone] = {**session, "step": "awaiting_confirmation",
                                            "category": cats[idx]}
        except ValueError:
            pass
        return

    print(f"[WhatsApp→{phone}]: Welcome message sent.")

def get_category_by_keyword(text: str) -> str:
    text = text.lower()
    kw_map = {
        "roads":        ["pothole","road","crater","broken","tar"],
        "water":        ["water","pipe","leak","burst","flood"],
        "garbage":      ["garbage","waste","trash","dump","smell"],
        "electricity":  ["light","electricity","power","dark","outage"],
        "sewage":       ["drain","sewage","overflow","blocked","sewer"],
        "encroachment": ["encroachment","illegal","obstruction","footpath"],
        "parks":        ["park","garden","bench","tree"],
    }
    for cat_id, kws in kw_map.items():
        if any(kw in text for kw in kws):
            return cat_id
    return "roads"

# ── Background tasks ──────────────────────────────────────────────────────────
async def forward_to_dept(issue: dict):
    """Forward issue to relevant department — hook up email/SMS here"""
    cat = CIVIC_CATEGORIES.get(issue["category_id"], {})
    print(f"[Nagarik] Issue #{issue['public_id']} forwarded to {cat.get('dept')} | "
          f"Ward: {issue.get('ward')} | Urgency: {issue['urgency_score']}")

# ── Analytics endpoints ───────────────────────────────────────────────────────
@app.get("/api/analytics/{city_id}")
def get_analytics(city_id: str):
    city_issues = [i for i in issues_db if i.get("city_id") == city_id]
    by_category = {}
    by_status   = {}
    for issue in city_issues:
        cat = issue.get("category_id", "unknown")
        st  = issue.get("status", "open")
        by_category[cat] = by_category.get(cat, 0) + 1
        by_status[st]    = by_status.get(st, 0) + 1

    return {
        "city_id":        city_id,
        "total_issues":   len(city_issues),
        "by_category":    by_category,
        "by_status":      by_status,
        "open":           by_status.get("open", 0),
        "in_progress":    by_status.get("in_progress", 0),
        "resolved":       by_status.get("resolved", 0),
        "computed_at":    datetime.utcnow().isoformat()
    }
