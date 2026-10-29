from datetime import datetime, timezone
from typing import Any
import os
import html
import re
import smtplib
from email.message import EmailMessage

import httpx
from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field
from backend.qpiai_integration import opt_status, qcloud_status, build_service_selection_qubo, submit_opt_problem, run_qcloud_smoke_test

app = FastAPI(
    title="DHARTRIX API",
    description="Backend APIs for DHARTRIX smart agriculture frontend",
    version="1.0.0",
)

# Same-origin serving is the default. CORS is permissive for local development;
# restrict allow_origins before production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://nominatim.openstreetmap.org/search"


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "DHARTRIX API"}


@app.get("/api/weather")
async def weather(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    """Return current temperature, relative humidity and a 7-day forecast."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max",
        "timezone": "auto",
        "forecast_days": 15,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(WEATHER_URL, params=params)
            response.raise_for_status()
            data = response.json()
        return {
            "source": "Open-Meteo",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "coordinates": {"latitude": latitude, "longitude": longitude},
            "timezone": data.get("timezone"),
            "current": data.get("current", {}),
            "daily": data.get("daily", {}),
        }
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Weather provider is temporarily unavailable") from exc



@app.get("/api/cyclone-warning")
async def cyclone_warning() -> dict[str, Any]:
    """Best-effort check of official IMD cyclone pages; never treats a failed check as no warning."""
    sources = [
        "https://rsmcnewdelhi.imd.gov.in/",
        "https://mausam.imd.gov.in/",
    ]
    checked = []
    errors = []
    # This is a cautious page-level check, not an official alert feed/API.
    # If the pages cannot be read or their content is inconclusive, return unknown.
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={"User-Agent": "DHARTRIX-Agriculture-Prototype/1.0"}) as client:
            for url in sources:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    text = re.sub(r"<[^>]+>", " ", response.text, flags=re.S)
                    text = re.sub(r"\s+", " ", html.unescape(text)).casefold()
                    checked.append({"url": url, "reachable": True})
                    # Only flag possible bulletin mentions; these pages may contain archives,
                    # so never claim a location-specific active warning from keyword matching.
                    if any(term in text for term in ("cyclone warning", "cyclonic storm", "depression over", "cyclone alert")):
                        return {"status": "check_official_bulletin", "message": "IMD cyclone-related information is present. Open the official bulletin to verify whether a warning is active for your location.", "checked_at": datetime.now(timezone.utc).isoformat(), "sources": checked + [{"url": u, "reachable": False} for u in sources if u not in [x["url"] for x in checked]], "verified_location_specific": False}
                except httpx.HTTPError as exc:
                    errors.append(url)
        if checked and not errors:
            return {"status": "unavailable", "message": "The IMD landing pages loaded, but DHARTRIX could not verify an active or absent warning for your specific location from an official alert feed. Do not treat this as an all-clear; check the latest IMD bulletin for your district.", "checked_at": datetime.now(timezone.utc).isoformat(), "sources": checked, "verified_location_specific": False}
        return {"status": "unavailable", "message": "Unable to verify cyclone warnings right now. Please check the latest official IMD bulletin.", "checked_at": datetime.now(timezone.utc).isoformat(), "sources": checked, "errors": errors, "verified_location_specific": False}
    except Exception:
        return {"status": "unavailable", "message": "Unable to verify cyclone warnings right now. Please check the latest official IMD bulletin.", "checked_at": datetime.now(timezone.utc).isoformat(), "sources": checked, "verified_location_specific": False}


@app.get("/api/crop-health")
def crop_health(crop: str = Query(default="", max_length=100), q: str = Query(default="", max_length=200), limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    """Search bundled crop-health reference records with tolerant crop and symptom matching."""
    import csv
    dataset = Path(__file__).resolve().parent.parent / "data" / "DHARTRIX_India_1000_Crop_Health_Records.csv"
    if not dataset.exists():
        raise HTTPException(status_code=404, detail=f"Bundled crop-health dataset is missing: {dataset.name}")
    def norm(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    crop_aliases = {
        "wheat": {"wheat"}, "rice": {"rice", "paddy"}, "maize": {"maize", "corn"},
        "tomato": {"tomato"}, "potato": {"potato"}, "chilli": {"chilli", "chili", "pepper"},
        "cotton": {"cotton"}, "groundnut": {"groundnut", "peanut"}, "soybean": {"soybean", "soya"},
        "banana": {"banana"}, "mango": {"mango"}, "other": set()
    }
    crop_key = norm(crop)
    aliases = crop_aliases.get(crop_key, {crop_key} if crop_key else set())
    query_tokens = [t for t in norm(q).split() if len(t) > 1]
    results = []
    with dataset.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            row_crop = norm(row.get("Crop", ""))
            crop_match = not crop_key or any(a in row_crop or row_crop in a for a in aliases)
            if not crop_match:
                continue
            haystack = norm(" ".join(str(v or "") for v in row.values()))
            if query_tokens and not all(token in haystack for token in query_tokens):
                # Also accept any token if a multi-word symptom phrase isn't contiguous in the data.
                if not any(token in haystack for token in query_tokens):
                    continue
            results.append(row)
    if q.strip():
        # Put the strongest matches first by how many query words appear in the record.
        results.sort(key=lambda row: sum(t in norm(" ".join(str(v or "") for v in row.values())) for t in query_tokens), reverse=True)
    total = len(results)
    results = results[:limit]
    return {"source": "bundled_dataset", "dataset": dataset.name, "count": total, "records": results,
            "notice": "Reference/demo records only. Image pixels are not classified by this lookup. Verify diagnosis and all treatment or fertilizer rates with a qualified local agronomist and soil-test results."}

@app.get("/api/places")
async def places(q: str = Query(..., min_length=2, max_length=120)) -> list[dict[str, Any]]:
    """Search Indian villages/towns using Nominatim, retrying a simpler query if needed."""
    headers = {"User-Agent": "DHARTRIX-Agriculture-Prototype/1.1 (place search)", "Accept-Language": "en"}
    queries = [q.strip()]
    parts = [x.strip() for x in q.split(",") if x.strip()]
    for n in range(len(parts) - 1, 0, -1):
        candidate = ", ".join(parts[:n])
        if candidate and candidate not in queries:
            queries.append(candidate)
    try:
        async with httpx.AsyncClient(timeout=18, headers=headers) as client:
            results = []
            for query in queries:
                response = await client.get(GEOCODING_URL, params={"q": query, "country": "India", "format": "jsonv2", "addressdetails": 1, "limit": 10})
                response.raise_for_status()
                results = response.json()
                if results:
                    break
        cleaned = []
        for item in results:
            address = item.get("address", {})
            cleaned.append({"name": item.get("name") or item.get("display_name", "").split(",")[0],
                "display_name": item.get("display_name"), "latitude": float(item["lat"]), "longitude": float(item["lon"]),
                "village": address.get("village") or address.get("hamlet") or address.get("town") or address.get("city") or address.get("suburb") or address.get("municipality"),
                "district": address.get("state_district") or address.get("county") or address.get("district"),
                "state": address.get("state"), "postcode": address.get("postcode")})
        return cleaned
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=502, detail="Place search provider is temporarily unavailable. Try village + district + state or use GPS.") from exc



class QuboRequest(BaseModel):
    budget_inr: float = Field(ge=0, le=100000000)
    services: list[dict[str, Any]] = Field(min_length=1, max_length=30)


class FacilityDispatchRequest(BaseModel):
    """Small facility assignment input for the dispatch demonstration."""
    required_capacity: float = Field(default=1, ge=0, le=100000000)
    required_chemistry: str | None = Field(default=None, max_length=100)
    facilities: list[dict[str, Any]] = Field(min_length=1, max_length=50)


@app.post("/api/qubo/dispatch")
async def qpiai_facility_dispatch(request: FacilityDispatchRequest) -> dict[str, Any]:
    """Run a transparent local exhaustive facility assignment and print terminal evidence logs.

    This route is a local classical dispatch demonstration. It does not claim that a
    QpiAI remote/quantum solver ran; remote Opt integration remains a separate route.
    """
    print("\n====================================================", flush=True)
    print("[QPI AI OPT] Received dispatch request from UI...", flush=True)
    print("[QPI AI OPT] Initializing Facility Dispatch QUBO...", flush=True)
    print("[QPI AI OPT] Applying Capacity & Chemistry Penalties...", flush=True)
    try:
        feasible: list[tuple[float, dict[str, Any]]] = []
        for item in request.facilities:
            name = str(item.get("name") or item.get("facility_name") or "Unnamed facility")
            try:
                capacity = float(item.get("capacity", item.get("available_capacity", 0)))
                cost = float(item.get("cost", item.get("dispatch_cost", 0)))
                penalty = float(item.get("penalty", 0))
            except (TypeError, ValueError):
                continue
            chemistry = str(item.get("chemistry", item.get("chemistry_type", "")))
            compatible_value = item.get("chemistry_compatible", True)
            compatible = bool(compatible_value)
            if request.required_chemistry and chemistry:
                compatible = compatible and chemistry.casefold() == request.required_chemistry.casefold()
            capacity_ok = capacity >= request.required_capacity
            # Infeasible facilities receive a large penalty; feasible candidates are
            # exhaustively compared by cost + explicit penalty + unused-capacity penalty.
            score = cost + penalty + max(0.0, capacity - request.required_capacity) * 0.001
            if capacity_ok and compatible:
                feasible.append((score, {"name": name, "capacity": capacity, "chemistry": chemistry or None, "score": round(score, 4)}))
        if not feasible:
            print("[QPI AI OPT] Solver Status: INFEASIBLE. No facility satisfies capacity and chemistry constraints.", flush=True)
            print("====================================================\n", flush=True)
            return {"ok": True, "solver_status": "INFEASIBLE", "solver": "local_classical_exhaustive_search", "assigned_facility": None, "message": "No facility satisfies the requested capacity and chemistry constraints."}
        feasible.sort(key=lambda x: (x[0], x[1]["name"].casefold()))
        best_score, best = feasible[0]
        print(f"[QPI AI OPT] Solver Status: OPTIMAL (local exhaustive search). Assigned to {best['name']}.", flush=True)
        print("[QPI AI OPT] Solver: local classical exhaustive search; no remote quantum solve was performed.", flush=True)
        print("====================================================\n", flush=True)
        return {"ok": True, "solver_status": "OPTIMAL", "solver": "local_classical_exhaustive_search", "assigned_facility": best["name"], "objective_score": round(best_score, 4), "feasible_facilities_checked": len(feasible), "message": f"Assigned to {best['name']} after checking capacity and chemistry constraints."}
    except Exception as exc:
        print(f"[QPI AI OPT] Solver Status: ERROR. {type(exc).__name__}: {exc}", flush=True)
        print("====================================================\n", flush=True)
        raise HTTPException(status_code=500, detail="Facility dispatch optimization failed.") from exc


@app.get("/api/qpiai/opt/status")
async def qpiai_opt_status() -> dict[str, Any]:
    """Report server-side Opt configuration without exposing credentials."""
    return opt_status()


@app.post("/api/qpiai/opt/qubo")
async def qpiai_opt_qubo(request: QuboRequest) -> dict[str, Any]:
    """Build an agriculture-related QUBO formulation for choosing one diagnostic service."""
    return build_service_selection_qubo(request.services, request.budget_inr)


@app.post("/api/qpiai/opt/submit")
async def qpiai_opt_submit() -> dict[str, Any]:
    """Create an Opt problem only after a docs-verified payload is configured server-side."""
    return await submit_opt_problem({})


@app.get("/api/qpiai/cloud/status")
async def qpiai_cloud_status() -> dict[str, Any]:
    return qcloud_status()


@app.post("/api/qpiai/cloud/smoke-test")
async def qpiai_cloud_smoke_test(shots: int = Query(256, ge=64, le=2048)) -> dict[str, Any]:
    """Explicitly run the documented QCloud GHZ smoke test; may consume account credits."""
    import asyncio
    return await asyncio.to_thread(run_qcloud_smoke_test, shots)



# ---- Farmer accounts and assistant (prototype persistence) -----------------
import hashlib
import secrets
import sqlite3
from datetime import timedelta
from fastapi import Header

DB_PATH = Path(__file__).resolve().parent.parent / "dhartrix.db"

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS farmers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, phone TEXT, state TEXT, district TEXT, village TEXT,
        language TEXT, farming_level TEXT, subscription_interest TEXT, created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, farmer_id INTEGER NOT NULL, expires_at TEXT NOT NULL,
        FOREIGN KEY(farmer_id) REFERENCES farmers(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS password_reset_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, farmer_id INTEGER NOT NULL,
        code_hash TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(farmer_id) REFERENCES farmers(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS farmer_practices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, crop TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT '',
        district TEXT NOT NULL DEFAULT '', village TEXT NOT NULL DEFAULT '',
        practice_text TEXT NOT NULL, safety TEXT NOT NULL DEFAULT '',
        author_label TEXT NOT NULL DEFAULT 'Farmer', created_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn

def _password_hash(password: str, salt: bytes | None = None) -> tuple[str, bytes]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return (salt.hex() + ":" + digest.hex(), salt)

def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 260_000).hex()
        import hmac
        return hmac.compare_digest(candidate, digest_hex)
    except Exception:
        return False

class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    phone: str = Field(default="", max_length=40)
    state: str = Field(min_length=2, max_length=100)
    district: str = Field(min_length=2, max_length=100)
    village: str = Field(min_length=2, max_length=120)
    language: str = Field(default="English", max_length=40)
    farming_level: str = Field(default="Beginner", max_length=60)
    subscription_interest: str = Field(default="skip", max_length=40)

class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)  # email address OR registered mobile number
    password: str = Field(min_length=1, max_length=200)

class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)

class ResetPasswordRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=200)

@app.post("/api/auth/register")
def register_farmer(request: RegisterRequest) -> dict[str, Any]:
    email = request.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    hashed, _ = _password_hash(request.password)
    conn = _db()
    try:
        cur = conn.execute("INSERT INTO farmers(name,email,password_hash,phone,state,district,village,language,farming_level,subscription_interest,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (request.name.strip(), email, hashed, request.phone.strip(), request.state, request.district, request.village, request.language, request.farming_level, request.subscription_interest, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        farmer_id = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="An account with this email already exists. Please log in.")
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash,farmer_id,expires_at) VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), farmer_id, (datetime.now(timezone.utc)+timedelta(days=7)).isoformat()))
    conn.commit()
    farmer = dict(conn.execute("SELECT id,name,email,phone,state,district,village,language,farming_level,subscription_interest FROM farmers WHERE id=?", (farmer_id,)).fetchone())
    conn.close()
    return {"ok": True, "token": token, "farmer": farmer, "message": "Account created. This prototype stores account data in a local SQLite database."}

@app.post("/api/auth/login")
def login_farmer(request: LoginRequest) -> dict[str, Any]:
    identifier = request.identifier.strip()
    conn = _db()
    if "@" in identifier:
        row = conn.execute("SELECT * FROM farmers WHERE lower(email)=lower(?)", (identifier,)).fetchone()
    else:
        # Compare normalized digits to support +91, spaces, and hyphens.
        digits = re.sub(r"\\D", "", identifier)
        rows = conn.execute("SELECT * FROM farmers WHERE phone IS NOT NULL AND phone != ''").fetchall()
        row = next((r for r in rows if re.sub(r"\\D", "", r["phone"] or "") == digits and digits), None)
    if not row or not _verify_password(request.password, row["password_hash"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Email/mobile number or password is incorrect.")
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash,farmer_id,expires_at) VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), row["id"], (datetime.now(timezone.utc)+timedelta(days=7)).isoformat()))
    conn.commit()
    farmer = {k: row[k] for k in ("id","name","email","phone","state","district","village","language","farming_level","subscription_interest")}
    conn.close()
    return {"ok": True, "token": token, "farmer": farmer}

def _send_password_reset_email(to_address: str, code: str) -> bool:
    """Send a one-time reset code using SMTP credentials configured in backend .env."""
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM", username).strip()
    if not all((host, username, password, sender, to_address)):
        return False

    port = int(os.getenv("SMTP_PORT", "587"))
    message = EmailMessage()
    message["Subject"] = "DHARTRIX AI password reset code"
    message["From"] = sender
    message["To"] = to_address
    message.set_content(
        f"Your DHARTRIX AI password reset code is: {code}\n\n"
        "This code expires in 10 minutes and can be used only once. "
        "If you did not request this, you can ignore this email. Do not share this code."
    )
    timeout = float(os.getenv("SMTP_TIMEOUT_SECONDS", "15"))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(username, password)
            server.send_message(message)
    return True


@app.post("/api/auth/forgot-password")
def forgot_password(request: ForgotPasswordRequest) -> dict[str, Any]:
    """Email reset codes when SMTP is configured; otherwise use terminal for local development."""
    identifier = request.identifier.strip()
    conn = _db()
    if "@" in identifier:
        row = conn.execute("SELECT id,email FROM farmers WHERE lower(email)=lower(?)", (identifier,)).fetchone()
    else:
        digits = re.sub(r"\D", "", identifier)
        rows = conn.execute("SELECT id,phone,email FROM farmers WHERE phone IS NOT NULL AND phone != ''").fetchall()
        row = next((r for r in rows if re.sub(r"\D", "", r["phone"] or "") == digits and digits), None)

    delivery = "generic"
    if row:
        code = f"{secrets.randbelow(1000000):06d}"
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        conn.execute("INSERT INTO password_reset_codes(farmer_id,code_hash,expires_at,used) VALUES(?,?,?,0)",
                     (row["id"], code_hash, (datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()))
        conn.commit()
        email_address = (row["email"] or "").strip()
        try:
            if email_address and _send_password_reset_email(email_address, code):
                delivery = "email"
                print(f"[DHARTRIX] Password reset email sent for account id {row['id']}.")
            else:
                smtp_configured = all(os.getenv(k, "").strip() for k in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"))
                if smtp_configured:
                    raise RuntimeError("SMTP is configured but the registered account has no usable email address.")
                print(f"\n[DHARTRIX LOCAL PASSWORD RESET] Code for account id {row['id']}: {code} (expires in 10 minutes)\n")
                delivery = "terminal"
        except Exception as exc:
            conn.close()
            print(f"[DHARTRIX] Password reset email delivery failed: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=503, detail="The reset email could not be sent. Check SMTP settings in the backend .env file and the PowerShell terminal, then try again.")
    conn.close()
    if delivery == "email":
        return {"ok": True, "message": "A reset code has been emailed to the registered address. Check Inbox and Spam/Junk. The code expires in 10 minutes."}
    if delivery == "terminal":
        return {"ok": True, "message": "Email delivery is not configured yet. For this local prototype, check the backend PowerShell terminal for the reset code. The code expires in 10 minutes."}
    return {"ok": True, "message": "If the account exists, a reset code has been requested. If email delivery is configured, check your registered email and Spam/Junk folder."}

@app.post("/api/auth/reset-password")
def reset_password(request: ResetPasswordRequest) -> dict[str, Any]:
    identifier = request.identifier.strip()
    conn = _db()
    if "@" in identifier:
        row = conn.execute("SELECT id FROM farmers WHERE lower(email)=lower(?)", (identifier,)).fetchone()
    else:
        digits = re.sub(r"\\D", "", identifier)
        rows = conn.execute("SELECT id,phone FROM farmers WHERE phone IS NOT NULL AND phone != ''").fetchall()
        row = next((r for r in rows if re.sub(r"\\D", "", r["phone"] or "") == digits and digits), None)
    if not row:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or expired reset code.")
    code_hash = hashlib.sha256(request.code.encode()).hexdigest()
    reset = conn.execute("SELECT id FROM password_reset_codes WHERE farmer_id=? AND code_hash=? AND used=0 AND expires_at>=? ORDER BY id DESC LIMIT 1",
                         (row["id"], code_hash, datetime.now(timezone.utc).isoformat())).fetchone()
    if not reset:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or expired reset code.")
    hashed, _ = _password_hash(request.new_password)
    conn.execute("UPDATE farmers SET password_hash=? WHERE id=?", (hashed, row["id"]))
    conn.execute("UPDATE password_reset_codes SET used=1 WHERE id=?", (reset["id"],))
    conn.execute("DELETE FROM sessions WHERE farmer_id=?", (row["id"],))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "Password updated. Please log in with your new password."}

@app.get("/api/auth/me")
def auth_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in required.")
    token = authorization.split(" ",1)[1].strip()
    conn = _db()
    row = conn.execute("SELECT f.id,f.name,f.email,f.phone,f.state,f.district,f.village,f.language,f.farming_level,f.subscription_interest,s.expires_at FROM sessions s JOIN farmers f ON f.id=s.farmer_id WHERE s.token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    conn.close()
    if not row or row["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return {"ok": True, "farmer": dict(row)}

@app.post("/api/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ",1)[1].strip()
        conn = _db()
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        conn.commit(); conn.close()
    return {"ok": True}

class FarmerPracticeRequest(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    crop: str = Field(default="", max_length=100)
    state: str = Field(default="", max_length=100)
    district: str = Field(default="", max_length=100)
    village: str = Field(default="", max_length=120)
    text: str = Field(min_length=10, max_length=5000)
    safety: str = Field(default="", max_length=1000)
    author_label: str = Field(default="Farmer", max_length=80)

@app.get("/api/farmer-practices")
def list_farmer_practices(crop: str = Query(default="", max_length=100), district: str = Query(default="", max_length=100), limit: int = Query(default=100, ge=1, le=300)) -> dict[str, Any]:
    """List community practices shared to this backend database; reports are not verified agronomic advice."""
    conn = _db()
    sql = "SELECT id,title,crop,state,district,village,practice_text AS text,safety,author_label,created_at FROM farmer_practices WHERE 1=1"
    params: list[Any] = []
    if crop.strip():
        sql += " AND lower(crop) LIKE ?"; params.append("%" + crop.strip().casefold() + "%")
    if district.strip():
        sql += " AND lower(district) LIKE ?"; params.append("%" + district.strip().casefold() + "%")
    sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return {"count": len(rows), "records": rows, "notice": "Farmer-shared reports are not independently verified. Confirm crop treatment and input rates with a qualified local agronomist."}

@app.post("/api/farmer-practices")
def create_farmer_practice(request: FarmerPracticeRequest) -> dict[str, Any]:
    conn = _db()
    cur = conn.execute("INSERT INTO farmer_practices(title,crop,state,district,village,practice_text,safety,author_label,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (request.title.strip(), request.crop.strip(), request.state.strip(), request.district.strip(), request.village.strip(), request.text.strip(), request.safety.strip(), request.author_label.strip() or "Farmer", datetime.now(timezone.utc).isoformat()))
    conn.commit()
    row = conn.execute("SELECT id,title,crop,state,district,village,practice_text AS text,safety,author_label,created_at FROM farmer_practices WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return {"ok": True, "record": dict(row), "notice": "Shared to this DHARTRIX backend database. Deploy a hosted database and add moderation/authentication before public production use."}

class AssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    language: str = Field(default="English", max_length=40)
    context: dict[str, Any] = Field(default_factory=dict)

@app.post("/api/assistant/chat")
async def assistant_chat(request: AssistantRequest) -> dict[str, Any]:
    """Use configured OpenAI API for a live AI answer; otherwise return an honest rule-based fallback."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post("https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "temperature": 0.2, "messages":[
                        {"role":"system","content":("You are DHARTRIX, a cautious agricultural assistant. Respond in " + request.language + ". Give beginner-friendly numbered steps. Ask for missing context. Never claim certainty from symptoms alone. Do not prescribe pesticide doses or unsafe chemical mixing. Distinguish general organic practices from validated crop-specific advice. Recommend soil testing or local agricultural extension when appropriate. For cyclone/severe weather, advise following official IMD and local authorities. Be transparent about limitations.")},
                        {"role":"user","content":request.message + "\nFarmer context (may be incomplete): " + str(request.context)}]})
                response.raise_for_status()
                data = response.json()
                answer = data["choices"][0]["message"]["content"]
                return {"ok": True, "mode":"live_ai", "model":model, "answer":answer}
        except Exception as exc:
            return {"ok": True, "mode":"fallback", "warning":"Live AI request failed; returned a cautious fallback. Check server logs and API configuration.", "answer":_assistant_fallback(request.message, request.language)}
    return {"ok": True, "mode":"rule_based_fallback", "warning":"OPENAI_API_KEY is not configured. This is not a live generative AI response.", "answer":_assistant_fallback(request.message, request.language)}

def _assistant_fallback(message: str, language: str) -> str:
    q = message.casefold()
    kind = "general"
    if any(w in q for w in ("disease","spot","yellow","fungus","pest","leaf","रोग","ರೋಗ","వ్యాధి","நோய்")):
        kind = "disease"
    elif any(w in q for w in ("water","irrigat","moisture","dry","borewell","पानी","ನೀರು","నీరు","தண்ணீர்")):
        kind = "water"
    elif any(w in q for w in ("organic","compost","manure","fertilizer","fertiliser","nutrient","खाद","ಗೊಬ್ಬರ","ఎరువు","உரம்")):
        kind = "organic"
    answers = {
      "English": {
        "disease":"Photograph affected and healthy leaves. Record crop variety, plant age, symptom spread, recent rain/irrigation and products already used. Do not spray based on a photo alone; confirm uncertain cases with a local agricultural expert or diagnostic lab.",
        "water":"Check soil moisture at the crop's active root depth at several field points before irrigating. Consider crop stage, soil texture and recent rainfall. One sensor reading may not represent the whole plot; calibrate the probe. Soil moisture does not reveal groundwater depth.",
        "organic":"Start with a soil test and record previous inputs. Use mature compost, mulch and crop rotation where suitable. Choose crop-specific quantities from soil-test results and local extension advice; organic inputs are not automatically harmless.",
        "general":"Please share crop and variety, growth stage, location, soil type, recent weather/irrigation, symptoms and products already used. Uncertain diagnoses should be confirmed by an agricultural expert or lab."},
      "Hindi": {
        "disease":"प्रभावित और स्वस्थ पत्तियों की साफ़ तस्वीर लें। फसल की किस्म, पौधे की उम्र, लक्षणों के फैलने, हाल की बारिश/सिंचाई और पहले इस्तेमाल किए गए उत्पादों का विवरण रखें। केवल तस्वीर देखकर छिड़काव न करें; कृषि विशेषज्ञ या जाँच प्रयोगशाला से पुष्टि करें।",
        "water":"सिंचाई से पहले खेत के कई स्थानों पर जड़ों की सक्रिय गहराई की मिट्टी की नमी जाँचें। फसल की अवस्था, मिट्टी और हाल की बारिश को ध्यान में रखें। एक सेंसर पूरे खेत का प्रतिनिधित्व नहीं कर सकता; उसे मिट्टी के अनुसार कैलिब्रेट करें। मिट्टी की नमी से भूजल की गहराई पता नहीं चलती।",
        "organic":"पहले मिट्टी की जाँच कराएँ और पहले इस्तेमाल किए गए इनपुट दर्ज करें। उपयुक्त होने पर अच्छी तरह पकी खाद, मल्च और फसल चक्र अपनाएँ। मात्रा मिट्टी की जाँच और स्थानीय कृषि सलाह के अनुसार तय करें; जैविक इनपुट भी हमेशा जोखिम-मुक्त नहीं होते।",
        "general":"कृपया फसल और किस्म, बढ़ने की अवस्था, स्थान, मिट्टी का प्रकार, हाल का मौसम/सिंचाई, लक्षण और पहले इस्तेमाल किए गए उत्पाद बताएँ। अनिश्चित निदान की पुष्टि कृषि विशेषज्ञ या प्रयोगशाला से कराएँ।"},
      "Kannada": {
        "disease":"ಬಾಧಿತ ಮತ್ತು ಆರೋಗ್ಯಕರ ಎಲೆಗಳ ಸ್ಪಷ್ಟ ಚಿತ್ರಗಳನ್ನು ತೆಗೆದುಕೊಳ್ಳಿ. ಬೆಳೆ/ತಳಿ, ಸಸ್ಯದ ವಯಸ್ಸು, ಲಕ್ಷಣಗಳ ಹರಡುವಿಕೆ, ಇತ್ತೀಚಿನ ಮಳೆ/ನೀರಾವರಿ ಮತ್ತು ಬಳಸಿದ ಉತ್ಪನ್ನಗಳನ್ನು ದಾಖಲಿಸಿ. ಚಿತ್ರವೊಂದರ ಆಧಾರದಲ್ಲಿ ಸಿಂಪಡಣೆ ಮಾಡಬೇಡಿ; ಕೃಷಿ ತಜ್ಞರು ಅಥವಾ ಪ್ರಯೋಗಾಲಯದಿಂದ ದೃಢೀಕರಿಸಿ.",
        "water":"ನೀರಾವರಿಗೆ ಮೊದಲು ಹೊಲದ ಹಲವು ಸ್ಥಳಗಳಲ್ಲಿ ಬೇರುಗಳ ಸಕ್ರಿಯ ಆಳದ ಮಣ್ಣಿನ ತೇವಾಂಶವನ್ನು ಪರಿಶೀಲಿಸಿ. ಬೆಳೆ ಹಂತ, ಮಣ್ಣಿನ ಸ್ವರೂಪ ಮತ್ತು ಇತ್ತೀಚಿನ ಮಳೆಯನ್ನು ಪರಿಗಣಿಸಿ. ಒಂದೇ ಸೆನ್ಸರ್ ಓದು ಇಡೀ ಹೊಲವನ್ನು ಪ್ರತಿನಿಧಿಸುವುದಿಲ್ಲ; ಮಣ್ಣಿಗೆ ಅನುಗುಣವಾಗಿ ಕ್ಯಾಲಿಬ್ರೇಟ್ ಮಾಡಿ. ಮಣ್ಣಿನ ತೇವಾಂಶದಿಂದ ಭೂಗರ್ಭಜಲದ ಆಳ ತಿಳಿಯುವುದಿಲ್ಲ.",
        "organic":"ಮೊದಲು ಮಣ್ಣಿನ ಪರೀಕ್ಷೆ ಮಾಡಿ, ಹಿಂದಿನ ಇನ್‌ಪುಟ್‌ಗಳನ್ನು ದಾಖಲಿಸಿ. ಸೂಕ್ತವಾಗಿದ್ದರೆ ಚೆನ್ನಾಗಿ ಕೊಳೆತ ಕಾಂಪೋಸ್ಟ್, ಮಲ್ಚ್ ಮತ್ತು ಬೆಳೆ ಪರಿವರ್ತನೆ ಬಳಸಿ. ಪ್ರಮಾಣವನ್ನು ಮಣ್ಣಿನ ಪರೀಕ್ಷೆ ಮತ್ತು ಸ್ಥಳೀಯ ಕೃಷಿ ಸಲಹೆಯ ಆಧಾರದಲ್ಲಿ ನಿರ್ಧರಿಸಿ; ಸಾವಯವ ಪದಾರ್ಥಗಳೂ ಯಾವಾಗಲೂ ಅಪಾಯರಹಿತವಲ್ಲ.",
        "general":"ಬೆಳೆ/ತಳಿ, ಬೆಳವಣಿಗೆಯ ಹಂತ, ಸ್ಥಳ, ಮಣ್ಣಿನ ಪ್ರಕಾರ, ಇತ್ತೀಚಿನ ಹವಾಮಾನ/ನೀರಾವರಿ, ಲಕ್ಷಣಗಳು ಮತ್ತು ಬಳಸಿದ ಉತ್ಪನ್ನಗಳನ್ನು ತಿಳಿಸಿ. ಅನುಮಾನಾಸ್ಪದ ರೋಗನಿರ್ಣಯವನ್ನು ಕೃಷಿ ತಜ್ಞರು ಅಥವಾ ಪ್ರಯೋಗಾಲಯದಿಂದ ದೃಢೀಕರಿಸಿ."},
      "Telugu": {
        "disease":"ప్రభావితమైన మరియు ఆరోగ్యంగా ఉన్న ఆకుల స్పష్టమైన ఫోటోలు తీసుకోండి. పంట రకం, మొక్క వయస్సు, లక్షణాలు ఎలా వ్యాపిస్తున్నాయి, ఇటీవలి వర్షం/నీటిపారుదల, ఇప్పటికే వాడిన ఉత్పత్తులను నమోదు చేయండి. ఫోటో ఆధారంగా మాత్రమే మందు పిచికారీ చేయవద్దు; వ్యవసాయ నిపుణుడు లేదా ప్రయోగశాల ద్వారా నిర్ధారించండి.",
        "water":"నీటిపారుదల ముందు పొలంలోని పలు ప్రాంతాల్లో వేర్ల క్రియాశీల లోతు వద్ద నేల తేమను తనిఖీ చేయండి. పంట దశ, నేల స్వభావం, ఇటీవలి వర్షాన్ని పరిగణించండి. ఒక సెన్సార్ రీడింగ్ మొత్తం పొలాన్ని సూచించదు; నేలకు అనుగుణంగా కాలిబ్రేట్ చేయండి. నేల తేమతో భూగర్భజలాల లోతు తెలియదు.",
        "organic":"ముందుగా నేల పరీక్ష చేయించి గతంలో వాడిన పదార్థాలను నమోదు చేయండి. అనుకూలమైతే పూర్తిగా కుళ్లిన కంపోస్ట్, మల్చ్, పంట మార్పిడి ఉపయోగించండి. మోతాదులను నేల పరీక్ష మరియు స్థానిక వ్యవసాయ సలహా ఆధారంగా నిర్ణయించండి; సేంద్రియ పదార్థాలు కూడా ఎల్లప్పుడూ ప్రమాదరహితం కావు.",
        "general":"పంట/రకం, పెరుగుదల దశ, ప్రదేశం, నేల రకం, ఇటీవలి వాతావరణం/నీటిపారుదల, లక్షణాలు, ఇప్పటికే వాడిన ఉత్పత్తులను తెలియజేయండి. అనుమానాస్పద నిర్ధారణను వ్యవసాయ నిపుణుడు లేదా ప్రయోగశాల ద్వారా నిర్ధారించండి."},
      "Tamil": {
        "disease":"பாதிக்கப்பட்ட மற்றும் ஆரோக்கியமான இலைகளின் தெளிவான படங்களை எடுக்கவும். பயிர் வகை, தாவர வயது, அறிகுறிகள் பரவும் விதம், சமீபத்திய மழை/நீர்ப்பாசனம் மற்றும் ஏற்கனவே பயன்படுத்திய பொருட்களை பதிவு செய்யவும். படத்தை மட்டும் வைத்து தெளிக்க வேண்டாம்; வேளாண் நிபுணர் அல்லது ஆய்வகத்திடம் உறுதிப்படுத்தவும்.",
        "water":"நீர்ப்பாசனத்திற்கு முன் வயலின் பல இடங்களில் வேர் செயல்படும் ஆழத்தில் மண் ஈரப்பதத்தைச் சரிபார்க்கவும். பயிர் நிலை, மண் வகை மற்றும் சமீபத்திய மழையை கருத்தில் கொள்ளவும். ஒரு சென்சார் அளவீடு முழு வயலையும் பிரதிநிதித்துவப்படுத்தாது; மண்ணுக்கு ஏற்ப அளவுத்திருத்தம் செய்யவும். மண் ஈரப்பதம் நிலத்தடி நீரின் ஆழத்தைச் சொல்லாது.",
        "organic":"முதலில் மண் பரிசோதனை செய்து முந்தைய இடுபொருட்களை பதிவு செய்யவும். பொருத்தமான இடங்களில் நன்கு மக்கிய உரம், மூடாக்கு மற்றும் பயிர் சுழற்சியைப் பயன்படுத்தவும். அளவுகளை மண் பரிசோதனை மற்றும் உள்ளூர் வேளாண் ஆலோசனையின் அடிப்படையில் தீர்மானிக்கவும்; இயற்கை இடுபொருட்களும் எப்போதும் ஆபத்தற்றவை அல்ல.",
        "general":"பயிர்/வகை, வளர்ச்சி நிலை, இடம், மண் வகை, சமீபத்திய வானிலை/நீர்ப்பாசனம், அறிகுறிகள் மற்றும் ஏற்கனவே பயன்படுத்திய பொருட்களைத் தெரிவிக்கவும். உறுதியற்ற நோயறிதலை வேளாண் நிபுணர் அல்லது ஆய்வகத்திடம் உறுதிப்படுத்தவும்."}
    }
    key = next((k for k in answers if k.casefold() in language.casefold()), "English")
    return answers[key][kind]


# Serve the frontend from the same FastAPI app so browser GPS and API requests
# can work from one local origin. Run this file from the project root.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
