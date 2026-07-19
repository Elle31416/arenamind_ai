import os
import re
from datetime import datetime
from backend.database import get_db_connection
from backend.routing import get_route, dijkstra, build_graph
import backend.state as state

# Try importing google-generativeai, default to None if import/config fails
try:
    import google.generativeai as genai
    HAS_GEMINI_SDK = True
except ImportError:
    HAS_GEMINI_SDK = False

# Quick database session manager helper
def get_or_create_session(user_id: str, current_zone: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Ensure user exists in users table
    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (id) VALUES (?)", (user_id,))
        conn.commit()
        
    cursor.execute("SELECT id FROM sessions WHERE user_id = ? ORDER BY started_at DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    if row:
        session_id = row["id"]
        # Update current zone
        cursor.execute("UPDATE sessions SET current_zone = ? WHERE id = ?", (current_zone, session_id))
        conn.commit()
    else:
        session_id = f"sess_{user_id}_{int(datetime.utcnow().timestamp())}"
        cursor.execute("INSERT INTO sessions (id, user_id, current_zone) VALUES (?, ?, ?)", (session_id, user_id, current_zone))
        conn.commit()
    conn.close()
    return session_id

def log_decision(session_id: str, rule_fired: str, action_taken: str, rationale: str) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO decision_log (session_id, rule_fired, action_taken, rationale) VALUES (?, ?, ?, ?)",
        (session_id, rule_fired, action_taken, rationale)
    )
    log_id = cursor.lastrowid
    conn.commit()
    
    cursor.execute("SELECT id, session_id, rule_fired, action_taken, rationale, timestamp FROM decision_log WHERE id = ?", (log_id,))
    log_row = dict(cursor.fetchone())
    conn.close()
    return log_row

def log_message(session_id: str, role: str, content: str, detected_lang: str = "en"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, detected_language) VALUES (?, ?, ?, ?)",
        (session_id, role, content, detected_lang)
    )
    conn.commit()
    conn.close()

# 1. Local Emergency Detection Heuristics
def check_emergency(message: str, current_zone: str) -> tuple:
    """
    Checks if a query contains severe emergency signals.
    Bypasses LLM roundtrips completely to satisfy zero-latency safety limits.
    """
    msg_lower = message.lower()
    
    high_severity_terms = [
        "fire", "medical emergency", "can't breathe", "cardiac", "heart attack", 
        "bleeding", "unconscious", "explosion", "bomb", "shooter", "weapon", "hazard"
    ]
    
    milder_emergency_terms = ["help", "security", "assistance", "pain", "hurt", "stuck", "police", "medic"]
    
    # Check high severity terms
    for term in high_severity_terms:
        if term in msg_lower:
            return True, f"CRITICAL_EMERGENCY ({term})"
            
    # Check milder emergency terms with local heuristics
    for term in milder_emergency_terms:
        if term in msg_lower:
            # Heuristic A: All caps (indicating shouting)
            is_shouting = len(message) > 4 and message.strip() == message.upper()
            
            # Heuristic B: Exclamation density
            exclamation_count = message.count("!")
            high_punctuation = exclamation_count >= 2
            
            # Heuristic C: Secondary high-urgency keywords
            urgency_modifiers = ["please", "hurt", "trapped", "danger", "dying", "choking", "collapsed", "urgent", "immediate", "panic"]
            has_modifier = any(mod in msg_lower for mod in urgency_modifiers)
            
            # Heuristic D: Active incident flag in the user's current zone
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT incident_flag, name FROM zones WHERE id = ?", (current_zone,))
            zone_row = cursor.fetchone()
            conn.close()
            
            zone_has_incident = False
            if zone_row and zone_row["incident_flag"] != "none":
                zone_has_incident = True
                
            if is_shouting or high_punctuation or has_modifier or zone_has_incident:
                rationale = f"Milder emergency word '{term}' triggered override due to: "
                reasons = []
                if is_shouting: reasons.append("shouting (ALL CAPS)")
                if high_punctuation: reasons.append("high exclamation density")
                if has_modifier: reasons.append("secondary urgency modifiers")
                if zone_has_incident: reasons.append(f"active zone incident ({zone_row['incident_flag']})")
                return True, rationale + ", ".join(reasons)
                
    return False, None

# 2. Predictive Congestion Rule
def check_predictive_congestion() -> list:
    """
    Scans recent telemetry ticks in global state.
    Returns list of zone_ids that have increased by >15% crowd density in the last 3 ticks.
    """
    congested = []
    for zone_id, history in state.ZONE_DENSITY_HISTORY.items():
        if len(history) >= 3:
            # Ticks: [first, second, third] -> history[0] to history[-1]
            diff = history[-1] - history[0]
            if diff > 0.15:
                congested.append(zone_id)
    return congested

# 3. Pathfinding target extraction
def extract_routing_target(message: str) -> str:
    """
    Simple local keyword scanner to match zone IDs in message (used for offline fallback & predictive checks).
    """
    msg_lower = message.lower()
    
    # Map synonyms to Zone IDs
    mappings = {
        "gate 1": "GATE_1", "gate1": "GATE_1", "north entrance": "GATE_1",
        "gate 2": "GATE_2", "gate2": "GATE_2", "east entrance": "GATE_2",
        "gate 3": "GATE_3", "gate3": "GATE_3", "south entrance": "GATE_3",
        "gate 4": "GATE_4", "gate4": "GATE_4", "west entrance": "GATE_4",
        "concourse north": "CONCOURSE_N", "concourse n": "CONCOURSE_N",
        "concourse east": "CONCOURSE_E", "concourse e": "CONCOURSE_E",
        "concourse south": "CONCOURSE_S", "concourse s": "CONCOURSE_S",
        "concourse west": "CONCOURSE_W", "concourse w": "CONCOURSE_W",
        "section 101": "SECTION_101", "premium section": "SECTION_101", "101": "SECTION_101",
        "section 102": "SECTION_102", "upper deck": "SECTION_102", "102": "SECTION_102",
        "restroom": "RESTROOM_A", "bathroom": "RESTROOM_A", "toilet": "RESTROOM_A", "wc": "RESTROOM_A",
        "concession": "CONCESSIONS_A", "food": "CONCESSIONS_A", "drink": "CONCESSIONS_A", "court": "CONCESSIONS_A"
    }
    
    for key, zone_id in mappings.items():
        if key in msg_lower:
            return zone_id
    return None

# Local routing logic with congestion warning and alternate path suggestion
def get_congested_alternative_route(start: str, end: str, accessibility_needed: bool, congested_zones: list) -> dict:
    """
    If path intersects a congested zone, computes an alternative route by inflating congestion weight.
    """
    # 1. Standard route
    standard_result = get_route(start, end, accessibility_needed)
    if not standard_result["success"]:
        return standard_result
        
    # Check if standard path intersects with any congested zones (excluding the starting zone)
    path = standard_result["path"]
    intersects_congestion = any(z in congested_zones for z in path[1:])
    
    if not intersects_congestion:
        return standard_result
        
    # 2. Compute alternate route by modifying weight of congested zones in dijkstra
    graph, zones = build_graph(accessibility_needed)
    
    # Temporarily inflate congested weights by 10x
    inflated_graph = {}
    for node, edges in graph.items():
        inflated_graph[node] = []
        for dest, weight in edges:
            if dest in congested_zones:
                weight = weight * 10.0
            inflated_graph[node].append((dest, weight))
            
    alt_path, alt_cost = dijkstra(inflated_graph, start, end)
    
    # If a distinct alternate path is found, return it
    if alt_path and alt_path != path:
        congested_names = [zones[z]["name"] for z in congested_zones if z in path[1:]]
        congested_str = ", ".join(congested_names)
        
        # Build explanation
        warning_msg = (
            f"TRAFFIC WARNING: {congested_str} is experiencing rapidly increasing crowd density "
            f"and is predicted to be congested within 10 minutes. We have calculated an alternate path to avoid delays.\n"
            f"- Standard Route: {' -> '.join(zones[z]['name'] for z in path)}\n"
            f"- Suggested Alternate Route: {' -> '.join(zones[z]['name'] for z in alt_path)}"
        )
        
        return {
            "success": True,
            "path": alt_path,
            "cost": alt_cost,
            "is_fallback": False,
            "fallback_target": None,
            "warning": warning_msg,
            "message": warning_msg
        }
        
    return standard_result

# Local offline response generator
def local_offline_fallback(message: str, current_zone: str, accessibility_needed: bool) -> tuple:
    """
    Failsafe router if Gemini fails or is offline.
    """
    target = extract_routing_target(message)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM zones WHERE id = ?", (current_zone,))
    start_name = cursor.fetchone()["name"]
    
    if target:
        # Check congestion
        congested = check_predictive_congestion()
        route_res = get_congested_alternative_route(current_zone, target, accessibility_needed, congested)
        
        cursor.execute("SELECT name FROM zones WHERE id = ?", (target,))
        target_name = cursor.fetchone()["name"]
        conn.close()
        
        # Format the response
        if route_res["success"]:
            route_str = " -> ".join(route_res["path"])
            warning = route_res.get("warning", "")
            
            # Accessibility warning if fallback occurred
            fallback_append = ""
            if route_res.get("is_fallback"):
                fallback_append = f"\n{route_res['message']}"
                
            reply = (
                f"Offline Mode Routing:\n"
                f"I have mapped a path from {start_name} to {target_name}.\n"
                f"Route: {route_str}\n"
                f"{warning}{fallback_append}\n"
                f"Note: Gemini Smart Reasoning is currently offline. Basic routing remains active."
            )
            return reply, route_res
        else:
            return f"Offline Mode:\n{route_res['message']}", route_res
            
    conn.close()
    return (
        "Offline Mode:\n"
        "Welcome to ArenaMind AI. Gemini Smart Reasoning is currently offline. "
        "You can request navigation directions by typing the destination zone name (e.g. 'restroom', 'section 101', 'gate 1')."
    , None)

# Main Query Handler
async def process_user_query(user_id: str, message: str, current_zone: str, language: str = "en", accessibility_needs: list = [], ticket_section: str = None) -> dict:
    session_id = get_or_create_session(user_id, current_zone)
    log_message(session_id, "user", message, language)
    
    # Prepare details for client response
    response_data = {
        "text": "",
        "route": None,
        "decision_log": None
    }
    
    # 1. RULE: Emergency Override Check (Local heuristic)
    is_emergency, emergency_reason = check_emergency(message, current_zone)
    if is_emergency:
        # Generate staff alert
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM zones WHERE id = ?", (current_zone,))
        zone_name = cursor.fetchone()["name"]
        conn.close()
        
        # Import main server alerts creator asynchronously
        from backend.main import create_staff_alert
        alert_msg = f"EMERGENCY OVERRIDE: User at {zone_name} reports emergency: '{message}' ({emergency_reason})"
        create_staff_alert(zone_id=current_zone, severity="critical", message=alert_msg)
        
        # Get exit directions
        exit_route = get_route(current_zone, "GATE_1", "wheelchair" in accessibility_needs)
        exit_str = " -> ".join(exit_route["path"]) if exit_route["success"] else "Nearest Gate"
        
        reply = (
            "EMERGENCY DETECTED: Please remain calm. We have notified emergency services and stadium security of your location. "
            f"If safe to do so, proceed immediately to the nearest exit gate.\n"
            f"Evacuation Route: {exit_str}\n"
            "Do not use elevators or stairs during an evacuation unless guided by security staff."
        )
        
        log_row = log_decision(
            session_id=session_id,
            rule_fired="EMERGENCY_OVERRIDE",
            action_taken="Escalated critical security alert to staff and output emergency route.",
            rationale=emergency_reason
        )
        
        log_message(session_id, "assistant", reply, language)
        response_data["text"] = reply
        response_data["route"] = exit_route if exit_route["success"] else None
        response_data["decision_log"] = log_row
        return response_data
        
    # 2. RULE: Accessibility Override (Check fallback disconnection)
    needs_access = "wheelchair" in accessibility_needs or "visual-impairment" in accessibility_needs
    target_zone = extract_routing_target(message)
    
    if needs_access and target_zone:
        route_res = get_route(current_zone, target_zone, accessibility_needed=True)
        if route_res["success"] and route_res.get("is_fallback"):
            # Trigger Staff alert
            from backend.main import create_staff_alert
            fallback_target_zone = route_res["fallback_target"]
            alert_msg = f"ACCESSIBILITY ASSIST: Route fallback triggered. User at {current_zone} cannot access {target_zone}. Routed to nearest accessible zone {fallback_target_zone}."
            create_staff_alert(zone_id=current_zone, severity="warning", message=alert_msg)
            
            log_row = log_decision(
                session_id=session_id,
                rule_fired="ACCESSIBILITY_OVERRIDE",
                action_taken="Calculated fallback route to nearest accessible zone and logged staff assistance ticket.",
                rationale=route_res["message"]
            )
            
            log_message(session_id, "assistant", route_res["message"], language)
            response_data["text"] = route_res["message"]
            response_data["route"] = route_res
            response_data["decision_log"] = log_row
            return response_data
            
    # 3. RULE: Predictive Congestion (Check Route Warnings)
    if target_zone:
        congested = check_predictive_congestion()
        route_res = get_congested_alternative_route(current_zone, target_zone, needs_access, congested)
        if route_res["success"] and "warning" in route_res:
            log_row = log_decision(
                session_id=session_id,
                rule_fired="PREDICTIVE_CONGESTION",
                action_taken="Diverted path to alternate route due to dynamic crowd congestion warning.",
                rationale=route_res["warning"]
            )
            
            log_message(session_id, "assistant", route_res["message"], language)
            response_data["text"] = route_res["message"]
            response_data["route"] = route_res
            response_data["decision_log"] = log_row
            return response_data
    # 3.5. RULE: Deterministic Routing Bypass (Bypasses Gemini API call to guarantee 0ms latency and conserve API key limits)
    msg_lower = message.lower()
    is_routing_intent = any(keyword in msg_lower for keyword in ["where", "route", "direction", "navigate", "path", "how to get", "go to", "find", "directions"])
    if target_zone and (is_routing_intent or current_zone != target_zone):
        congested = check_predictive_congestion()
        route_res = get_congested_alternative_route(current_zone, target_zone, needs_access, congested)
        if route_res["success"]:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM zones WHERE id = ?", (target_zone,))
            dest_name = cursor.fetchone()["name"]
            cursor.execute("SELECT name FROM zones WHERE id = ?", (current_zone,))
            start_name = cursor.fetchone()["name"]
            conn.close()
            
            route_str = " -> ".join(route_res["path"])
            warning = route_res.get("warning", "")
            
            # Format clean user response
            reply = f"Navigation Guide:\nHere is the path from {start_name} to {dest_name}.\nRoute: {route_str}\n"
            if warning:
                reply += f"\n{warning}"
            if route_res.get("is_fallback"):
                reply += f"\n{route_res['message']}"
                
            log_row = log_decision(
                session_id=session_id,
                rule_fired="ROUTING_DETERMINISTIC_BYPASS",
                action_taken="Resolved routing request locally with Dijkstra.",
                rationale="Detected routing intent. Bypassed LLM to save API quota and ensure zero latency."
            )
            
            log_message(session_id, "assistant", reply, language)
            response_data["text"] = reply
            response_data["route"] = route_res
            response_data["decision_log"] = log_row
            return response_data

    # 4. LLM FALLBACK: Try Gemini Reasoning
    api_key = os.environ.get("GEMINI_API_KEY")
    if HAS_GEMINI_SDK and api_key:
        try:
            genai.configure(api_key=api_key)
            
            # Fetch stadium context
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, type, accessible, current_density, queue_est_min, incident_flag FROM zones")
            zones_list = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            # Build full prompt
            system_prompt = (
                f"You are ArenaMind AI, the smart assistant for stadium operations.\n"
                f"Current Tournament Phase: {state.CURRENT_PHASE}\n"
                f"RULE FOR THE PHASE: During 'MATCH' and 'EGRESS' phases, you MUST suppress concessions/promotional recommendations. Keep instructions centered on safety/routing.\n"
                f"Current Stadium Telemetry:\n{json_format_zones(zones_list)}\n"
                f"User Profile:\n"
                f"- User ID: {user_id}\n"
                f"- Current Zone: {current_zone}\n"
                f"- Accessibility Needs: {accessibility_needs}\n"
                f"- Ticket Section: {ticket_section}\n\n"
                f"Conversation Instructions:\n"
                f"- Always respond in the detected language: {language}.\n"
                f"- Maintain security awareness. If the user asks for routes, search for zone names. You have access to local Dijkstra tools.\n"
                f"- You can recommend routing by advising the user to type directions. If you want to compute a route, output the tag '[ROUTE:START_ZONE:END_ZONE]' in your text. We will intercept it to draw the route map."
            )
            
            # Gemini models config
            model = genai.GenerativeModel(
                model_name='gemini-2.5-flash',
                system_instruction=system_prompt
            )
            
            # We fetch chat history (last 5 messages)
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT 5", (session_id,))
            history_rows = cursor.fetchall()
            conn.close()
            
            # Standard chat model call
            chat = model.start_chat()
            
            # Seed history (reverse chronological to chronological)
            for h in reversed(history_rows[:-1]): # Exclude the user message we just inserted
                # Convert roles to gemini expectations ('user', 'model')
                gemini_role = 'user' if h['role'] == 'user' else 'model'
                chat.send_message(h['content']) # Just load state
                
            gemini_response = chat.send_message(message, safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ])
            
            reply_text = gemini_response.text
            
            # Parse route requests if Gemini outputs [ROUTE:START:END]
            route_obj = None
            route_match = re.search(r'\[ROUTE:([A-Za-z0-9_]+):([A-Za-z0-9_]+)\]', reply_text)
            if route_match:
                start_extracted = route_match.group(1)
                end_extracted = route_match.group(2)
                route_obj = get_route(start_extracted, end_extracted, needs_access)
                # Remove tag from text
                reply_text = re.sub(r'\[ROUTE:([A-Za-z0-9_]+):([A-Za-z0-9_]+)\]', '', reply_text).strip()
            elif target_zone:
                # If Gemini doesn't output the route tag, but we detected a target zone locally, attach route
                route_obj = get_route(current_zone, target_zone, needs_access)
                
            log_row = log_decision(
                session_id=session_id,
                rule_fired="GEMINI_REASONING_LAYER",
                action_taken="Processed query via Gemini reasoning model.",
                rationale="No deterministic rules fired. Queried Gemini 2.5 Flash."
            )
            
            log_message(session_id, "assistant", reply_text, language)
            response_data["text"] = reply_text
            response_data["route"] = route_obj
            response_data["decision_log"] = log_row
            return response_data
            
        except Exception as e:
            # Fallback to local routing if Gemini fails/timeouts
            print(f"Gemini API Exception: {e}")
            reply, route_res = local_offline_fallback(message, current_zone, needs_access)
            
            log_row = log_decision(
                session_id=session_id,
                rule_fired="GEMINI_API_TIMEOUT_FALLBACK",
                action_taken="Offline router activated due to Gemini API exception/timeout.",
                rationale=str(e)
            )
            
            log_message(session_id, "assistant", reply, language)
            response_data["text"] = reply
            response_data["route"] = route_res
            response_data["decision_log"] = log_row
            return response_data
            
    # 5. Local Offline Fallback if Gemini not available or API key not present
    reply, route_res = local_offline_fallback(message, current_zone, needs_access)
    log_row = log_decision(
        session_id=session_id,
        rule_fired="LOCAL_OFFLINE_ROUTER",
        action_taken="Offline router activated.",
        rationale="Gemini SDK/API Key not configured."
    )
    
    log_message(session_id, "assistant", reply, language)
    response_data["text"] = reply
    response_data["route"] = route_res
    response_data["decision_log"] = log_row
    return response_data

def json_format_zones(zones: list) -> str:
    lines = []
    for z in zones:
        lines.append(f"- Zone {z['id']} ({z['name']}): Type={z['type']}, Accessible={z['accessible']}, Density={z['current_density']:.2f}, Queue={z['queue_est_min']} min, Incident={z['incident_flag']}")
    return "\n".join(lines)
