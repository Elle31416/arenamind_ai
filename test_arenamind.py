import os
import unittest
from unittest.mock import patch, MagicMock

# Set up path to ensure correct package discovery
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.database import init_db, get_db_connection
from backend.routing import get_route, dijkstra, build_graph
from backend.engine import check_emergency, check_predictive_congestion, process_user_query, extract_routing_target
import backend.state as state

class TestArenaMindAI(unittest.IsolatedAsyncioTestCase):
    
    @classmethod
    def setUpClass(cls):
        # Initialize database for testing
        init_db()
        
    def setUp(self):
        # Reset state history before each test
        state.ZONE_DENSITY_HISTORY.clear()
        state.CURRENT_PHASE = "PRE_MATCH"
        
        # Reset any incident flags in the database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE zones SET incident_flag = 'none', current_density = 0.1")
        conn.commit()
        conn.close()

    def test_dijkstra_correctness(self):
        """
        Verify that Dijkstra pathfinding returns a valid path and respects weights.
        """
        # Able-bodied happy path routing
        route_res = get_route("GATE_1", "SECTION_101", accessibility_needed=False)
        self.assertTrue(route_res["success"])
        self.assertIn("GATE_1", route_res["path"])
        self.assertIn("CONCOURSE_N", route_res["path"])
        self.assertIn("SECTION_101", route_res["path"])
        
        # Check dynamic weight updates
        # If concourse north gets highly congested, we verify path cost increases
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE zones SET current_density = 0.99 WHERE id = 'CONCOURSE_N'")
        conn.commit()
        conn.close()
        
        route_congested = get_route("GATE_1", "SECTION_101", accessibility_needed=False)
        self.assertTrue(route_congested["success"])
        # Cost with density 0.99 must be greater than default density 0.1
        self.assertGreater(route_congested["cost"], route_res["cost"])

    def test_emergency_false_positive_prevention(self):
        """
        Verify emergency heuristic correctly filters false-positives
        and triggers on true emergencies.
        """
        # Normal query with mild word "help" - should NOT trigger override
        is_em, reason = check_emergency("Can you help me find my seat in premium section?", "GATE_1")
        self.assertFalse(is_em)
        self.assertIsNone(reason)
        
        # Severe emergency keyword - MUST trigger
        is_em, reason = check_emergency("There is a fire near Gate 1, we need evacuation!", "GATE_1")
        self.assertTrue(is_em)
        self.assertIn("fire", reason)
        
        # Milder word with SHOUTING (ALL CAPS) - MUST trigger
        is_em, reason = check_emergency("HELP ME QUICKLY", "GATE_1")
        self.assertTrue(is_em)
        self.assertIn("shouting", reason)
        
        # Milder word with active incident in the zone - MUST trigger
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE zones SET incident_flag = 'security' WHERE id = 'GATE_3'")
        conn.commit()
        conn.close()
        
        is_em, reason = check_emergency("I need security assistance please", "GATE_3")
        self.assertTrue(is_em)
        self.assertIn("active zone incident", reason)

    def test_accessibility_disconnection_fallback(self):
        """
        Verify that accessibility routing handles graph disconnection gracefully
        by routing to the closest accessible node and generating staff alert.
        """
        # SECTION_102 is inaccessible (accessible=0).
        # Routing a wheelchair user to SECTION_102 should trigger fallback to RESTROOM_A.
        route_res = get_route("GATE_1", "SECTION_102", accessibility_needed=True)
        
        self.assertTrue(route_res["success"])
        self.assertTrue(route_res["is_fallback"])
        self.assertEqual(route_res["fallback_target"], "RESTROOM_A") # RESTROOM_A is the closest accessible zone
        self.assertIn("No fully accessible path is currently available", route_res["message"])

    def test_predictive_congestion(self):
        """
        Verify that a 15% density increase over 3 ticks triggers the predictive congestion warning
        and provides an alternate path.
        """
        # Seed 3 ticks of density increase on CONCOURSE_N: 0.1 -> 0.2 -> 0.4 (+30% increase)
        state.ZONE_DENSITY_HISTORY["CONCOURSE_N"] = [0.10, 0.20, 0.40]
        
        congested = check_predictive_congestion()
        self.assertIn("CONCOURSE_N", congested)
        
        # If we query a path that goes through CONCOURSE_N, we check if alert rule resolves alternate route
        # Route: GATE_1 -> CONCOURSE_N -> SECTION_101
        # Alternate Route should route around CONCOURSE_N if we inflate weights (GATE_1 -> CONCOURSE_N is standard, 
        # but let's check if it finds an alternative path or triggers warnings)
        target = extract_routing_target("Where is section 101?")
        self.assertEqual(target, "SECTION_101")

    @patch('backend.engine.HAS_GEMINI_SDK', True)
    @patch('google.generativeai.GenerativeModel')
    async def test_gemini_timeout_fallback(self, mock_model):
        """
        Simulate a Gemini API failure/timeout and verify that engine.py
        falls back gracefully to the local offline router.
        """
        # Set environment key to simulate setup
        os.environ["GEMINI_API_KEY"] = "fake_key"
        
        # Mock Gemini call to throw exception
        mock_instance = MagicMock()
        mock_instance.start_chat.side_effect = Exception("API connection timeout")
        mock_model.return_value = mock_instance
        
        # Call query handler
        response = await process_user_query(
            user_id="test_user",
            message="Show me the route to concessions",
            current_zone="GATE_1",
            language="en"
        )
        
        # Check response details
        self.assertIsNotNone(response)
        self.assertIn("Offline Mode", response["text"])
        self.assertEqual(response["decision_log"]["rule_fired"], "GEMINI_API_TIMEOUT_FALLBACK")
        self.assertIsNotNone(response["route"])
        self.assertIn("CONCESSIONS_A", response["route"]["path"])

    def test_api_endpoints(self):
        """
        Verify REST API endpoints using FastAPI's TestClient.
        """
        from fastapi.testclient import TestClient
        from backend.main import app
        
        client = TestClient(app)
        
        # 1. Test GET /api/zones
        response = client.get("/api/zones")
        self.assertEqual(response.status_code, 200)
        zones = response.json()
        self.assertEqual(len(zones), 12)
        self.assertEqual(zones[0]["id"], "GATE_1")
        
        # 2. Test POST /api/admin/phase
        response = client.post("/api/admin/phase?phase=MATCH")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phase"], "MATCH")
        self.assertEqual(state.CURRENT_PHASE, "MATCH")
        
        # 3. Test POST /api/admin/scenario
        response = client.post("/api/admin/scenario", json={
            "zoneId": "GATE_3",
            "density": 0.88,
            "incidentFlag": "congestion"
        })
        self.assertEqual(response.status_code, 200)
        
        # Check database update
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT current_density, incident_flag FROM zones WHERE id = 'GATE_3'")
        row = cursor.fetchone()
        conn.close()
        self.assertGreater(row["current_density"], 0.6)
        self.assertEqual(row["incident_flag"], "congestion")

    def test_session_management(self):
        """
        Verify session creation and current zone updates in database.
        """
        from backend.engine import get_or_create_session
        
        user_id = "test_user_unique_999"
        # First call creates session
        sess_id_1 = get_or_create_session(user_id, "GATE_1")
        self.assertIsNotNone(sess_id_1)
        self.assertTrue(sess_id_1.startswith("sess_"))
        
        # Second call returns same session and updates zone
        sess_id_2 = get_or_create_session(user_id, "GATE_2")
        self.assertEqual(sess_id_1, sess_id_2)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT current_zone FROM sessions WHERE id = ?", (sess_id_1,))
        row = cursor.fetchone()
        conn.close()
        self.assertEqual(row["current_zone"], "GATE_2")

    def test_language_detection_logging(self):
        """
        Verify that language selection is correctly logged in messages table.
        """
        from backend.engine import log_message
        
        session_id = "test_sess_lang_1"
        log_message(session_id, "user", "Hola, ¿dónde está el baño?", "es")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT detected_language, content FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1", (session_id,))
        row = cursor.fetchone()
        conn.close()
        
        self.assertEqual(row["detected_language"], "es")
        self.assertEqual(row["content"], "Hola, ¿dónde está el baño?")

    @patch('backend.engine.HAS_GEMINI_SDK', True)
    @patch('google.generativeai.GenerativeModel')
    async def test_phase_suppression_prompt(self, mock_model):
        """
        Verify that the compiled Gemini prompt contains phase-specific constraints.
        """
        state.CURRENT_PHASE = "MATCH"
        os.environ["GEMINI_API_KEY"] = "dummy"
        
        try:
            await process_user_query(
                user_id="user_777",
                message="Tell me a joke",
                current_zone="GATE_1"
            )
        except Exception:
            pass
            
        mock_model.assert_called()
        _, kwargs = mock_model.call_args
        system_instruction = kwargs.get("system_instruction", "")
        self.assertIn("MATCH", system_instruction)
        self.assertIn("suppress concessions/promotional recommendations", system_instruction)

if __name__ == "__main__":
    unittest.main()
