import asyncio
import json
import os
import random
from datetime import datetime
from typing import List, Dict, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.database import get_db_connection, init_db
import backend.state as state

app = FastAPI(title="ArenaMind AI API")

# Allow CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active WebSocket connections
telemetry_clients: Set[WebSocket] = set()
staff_clients: Set[WebSocket] = set()

# State of the mock telemetry engine
CURRENT_PHASE = "PRE_MATCH"
PHASES = ["PRE_MATCH", "INGRESS", "MATCH", "HALFTIME", "MATCH", "EGRESS", "POST_MATCH"]
PHASE_INDEX = 0
PHASE_TIMER = 0  # ticks until auto transition

# Pydantic schemas
class UserQueryInput(BaseModel):
    userId: str
    message: str
    currentZone: str
    language: str = "en"
    accessibilityNeeds: List[str] = [] # e.g. ["wheelchair"]
    ticketSection: str = None

class ScenarioInput(BaseModel):
    zoneId: str
    density: float = None
    incidentFlag: str = None # none, congestion, medical, security

# Connection managers for WebSockets
async def connect_telemetry(websocket: WebSocket):
    await websocket.accept()
    telemetry_clients.add(websocket)
    # Send initial state
    await send_initial_telemetry(websocket)

def disconnect_telemetry(websocket: WebSocket):
    telemetry_clients.remove(websocket)

async def connect_staff(websocket: WebSocket):
    await websocket.accept()
    staff_clients.add(websocket)
    # Send current active alerts
    await send_initial_alerts(websocket)

def disconnect_staff(websocket: WebSocket):
    staff_clients.remove(websocket)

async def broadcast_telemetry(data: dict):
    if not telemetry_clients:
        return
    message = json.dumps(data)
    # Broadcast to all telemetry clients (includes staff dashboard)
    inactive = []
    for client in telemetry_clients:
        try:
            await client.send_text(message)
        except Exception:
            inactive.append(client)
    for client in inactive:
        telemetry_clients.remove(client)

async def broadcast_staff_alert(alert_data: dict):
    if not staff_clients:
        return
    message = json.dumps({
        "type": "alert",
        "alert": alert_data
    })
    inactive = []
    for client in staff_clients:
        try:
            await client.send_text(message)
        except Exception:
            inactive.append(client)
    for client in inactive:
        staff_clients.remove(client)

async def broadcast_decision_log(log_data: dict):
    if not staff_clients:
        return
    message = json.dumps({
        "type": "decision_log",
        "log": log_data
    })
    inactive = []
    for client in staff_clients:
        try:
            await client.send_text(message)
        except Exception:
            inactive.append(client)
    for client in inactive:
        staff_clients.remove(client)

async def send_initial_telemetry(websocket: WebSocket):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, type, accessible, current_density, queue_est_min, incident_flag, x, y FROM zones")
    zones = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    await websocket.send_text(json.dumps({
        "type": "telemetry",
        "phase": CURRENT_PHASE,
        "zones": zones
    }))

async def send_initial_alerts(websocket: WebSocket):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, zone_id, severity, message, created_at, resolved FROM staff_alerts WHERE resolved = 0 ORDER BY id DESC")
    alerts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    await websocket.send_text(json.dumps({
        "type": "initial_alerts",
        "alerts": alerts
    }))

# WebSocket Endpoints
@app.websocket("/ws/telemetry")
async def ws_telemetry_endpoint(websocket: WebSocket):
    await connect_telemetry(websocket)
    try:
        while True:
            # Keep-alive loop
            await websocket.receive_text()
    except WebSocketDisconnect:
        disconnect_telemetry(websocket)
    except Exception:
        disconnect_telemetry(websocket)

@app.websocket("/ws/staff")
async def ws_staff_endpoint(websocket: WebSocket):
    await connect_staff(websocket)
    try:
        while True:
            # Keep-alive loop
            await websocket.receive_text()
    except WebSocketDisconnect:
        disconnect_staff(websocket)
    except Exception:
        disconnect_staff(websocket)

# Helper to inject a staff alert and broadcast it
def create_staff_alert(zone_id: str, severity: str, message: str) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO staff_alerts (zone_id, severity, message) VALUES (?, ?, ?)",
        (zone_id, severity, message)
    )
    alert_id = cursor.lastrowid
    conn.commit()
    
    cursor.execute("SELECT id, zone_id, severity, message, created_at, resolved FROM staff_alerts WHERE id = ?", (alert_id,))
    alert_row = dict(cursor.fetchone())
    conn.close()
    
    # Broadcast alert asynchronously in running event loop
    asyncio.create_task(broadcast_staff_alert(alert_row))
    return alert_row

# REST APIs
@app.post("/api/query")
async def handle_user_query(payload: UserQueryInput):
    # Process request using Decision Engine
    from backend.engine import process_user_query
    
    response = await process_user_query(
        user_id=payload.userId,
        message=payload.message,
        current_zone=payload.currentZone,
        language=payload.language,
        accessibility_needs=payload.accessibilityNeeds,
        ticket_section=payload.ticketSection
    )
    
    # Broadcast the decision log if logged
    if "decision_log" in response:
        asyncio.create_task(broadcast_decision_log(response["decision_log"]))
        
    return response

@app.post("/api/admin/scenario")
async def inject_scenario(payload: ScenarioInput):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify zone exists
    cursor.execute("SELECT id, name FROM zones WHERE id = ?", (payload.zoneId,))
    zone = cursor.fetchone()
    if not zone:
        conn.close()
        raise HTTPException(status_code=404, detail="Zone not found")
        
    updates = []
    params = []
    if payload.density is not None:
        updates.append("current_density = ?")
        params.append(payload.density)
        # Recalculate queue minutes
        updates.append("queue_est_min = ?")
        params.append(int(payload.density * 30))
    if payload.incidentFlag is not None:
        updates.append("incident_flag = ?")
        params.append(payload.incidentFlag)
        
    if updates:
        params.append(payload.zoneId)
        cursor.execute(f"UPDATE zones SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        
    conn.close()
    
    # If a critical incident was injected, generate a staff alert
    if payload.incidentFlag and payload.incidentFlag != "none":
        severity = "critical" if payload.incidentFlag in ["security", "medical"] else "warning"
        create_staff_alert(
            zone_id=payload.zoneId,
            severity=severity,
            message=f"MANUAL INJECTION: {payload.incidentFlag.upper()} incident reported in {zone['name']}."
        )
        
    # Trigger an immediate telemetry broadcast
    asyncio.create_task(tick_telemetry(manual=True))
    
    return {"status": "success", "message": f"Scenario applied to {payload.zoneId}."}

@app.post("/api/admin/phase")
async def set_tournament_phase(phase: str):
    global CURRENT_PHASE, PHASE_INDEX
    if phase not in PHASES:
        raise HTTPException(status_code=400, detail="Invalid phase name")
    
    CURRENT_PHASE = phase
    state.CURRENT_PHASE = phase
    PHASE_INDEX = PHASES.index(phase)
    
    # Trigger an immediate telemetry broadcast
    asyncio.create_task(tick_telemetry(manual=True))
    return {"status": "success", "phase": CURRENT_PHASE}

@app.get("/api/zones")
async def list_zones_status():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, type, accessible, current_density, queue_est_min, incident_flag, x, y FROM zones")
    zones = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return zones

@app.post("/api/alerts/resolve")
async def resolve_alert(alert_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE staff_alerts SET resolved = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()
    
    # Broadcast refresh to staff
    asyncio.create_task(broadcast_refresh_alerts())
    return {"status": "success"}

async def broadcast_refresh_alerts():
    if not staff_clients:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, zone_id, severity, message, created_at, resolved FROM staff_alerts WHERE resolved = 0 ORDER BY id DESC")
    alerts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    for client in staff_clients:
        try:
            await client.send_text(json.dumps({
                "type": "initial_alerts",
                "alerts": alerts
            }))
        except Exception:
            pass

# Background telemetry ticker
async def tick_telemetry(manual=False):
    global CURRENT_PHASE, PHASE_INDEX, PHASE_TIMER
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # If not triggered manually, increment timers and handle phase transitions
    if not manual:
        PHASE_TIMER += 1
        # Auto-advance phase every 45 ticks (~3 minutes of real time)
        if PHASE_TIMER >= 45:
            PHASE_TIMER = 0
            PHASE_INDEX = (PHASE_INDEX + 1) % len(PHASES)
            CURRENT_PHASE = PHASES[PHASE_INDEX]
            state.CURRENT_PHASE = CURRENT_PHASE
            
    # Load all zones to update them
    cursor.execute("SELECT id, type, current_density, incident_flag FROM zones")
    zones = cursor.fetchall()
    
    for zone in zones:
        zone_id = zone["id"]
        zone_type = zone["type"]
        density = zone["current_density"]
        incident = zone["incident_flag"]
        
        # Bounded random walk density targets based on phase
        # PRE_MATCH -> INGRESS -> MATCH -> HALFTIME -> MATCH -> EGRESS -> POST_MATCH
        if CURRENT_PHASE == "PRE_MATCH":
            target_density = 0.3 if zone_type == "GATE" else 0.15
        elif CURRENT_PHASE == "INGRESS":
            target_density = 0.8 if zone_type == "GATE" else 0.4
        elif CURRENT_PHASE == "MATCH":
            if zone_type == "GATE":
                target_density = 0.05
            elif zone_type == "SECTION":
                target_density = 0.8
            else:
                target_density = 0.2
        elif CURRENT_PHASE == "HALFTIME":
            if zone_type == "CONCOURSE" or zone_type == "RESTROOM" or zone_type == "CONCESSIONS":
                target_density = 0.85
            else:
                target_density = 0.2
        elif CURRENT_PHASE == "EGRESS":
            if zone_type == "GATE" or zone_type == "CONCOURSE" or zone_id == "GATE_3":
                target_density = 0.9
            else:
                target_density = 0.1
        else: # POST_MATCH
            target_density = 0.05
            
        # Add random walk factor
        step = random.uniform(-0.08, 0.08)
        new_density = density + (target_density - density) * 0.15 + step
        new_density = max(0.0, min(1.0, new_density))
        
        # Recalculate queue times based on density
        new_queue = int(new_density * 25)
        if zone_type == "CONCESSIONS":
            new_queue = int(new_density * 35) # Concessions have longer lines
            
        # Update SQLite
        cursor.execute(
            "UPDATE zones SET current_density = ?, queue_est_min = ? WHERE id = ?",
            (new_density, new_queue, zone_id)
        )
        
        # Track history in global state
        if zone_id not in state.ZONE_DENSITY_HISTORY:
            state.ZONE_DENSITY_HISTORY[zone_id] = []
        state.ZONE_DENSITY_HISTORY[zone_id].append(new_density)
        if len(state.ZONE_DENSITY_HISTORY[zone_id]) > 3:
            state.ZONE_DENSITY_HISTORY[zone_id].pop(0)
        
    conn.commit()
    
    # Reload updated zones to broadcast
    cursor.execute("SELECT id, name, type, accessible, current_density, queue_est_min, incident_flag, x, y FROM zones")
    updated_zones = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    # Broadcast updated telemetry to all subscribers
    await broadcast_telemetry({
        "type": "telemetry",
        "phase": CURRENT_PHASE,
        "zones": updated_zones
    })

async def telemetry_loop():
    while True:
        try:
            await asyncio.sleep(4.0)
            await tick_telemetry()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in telemetry loop: {e}")
            await asyncio.sleep(4.0)

# Lifecycle tasks
@app.on_event("startup")
async def startup_event():
    init_db()
    # Start background telemetry tick
    app.state.telemetry_task = asyncio.create_task(telemetry_loop())

@app.on_event("shutdown")
async def shutdown_event():
    app.state.telemetry_task.cancel()
    await app.state.telemetry_task

# Mount static files to serve the frontend
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
