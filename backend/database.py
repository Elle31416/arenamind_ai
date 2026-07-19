import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stadium.db")

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS zones (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL, -- GATE, CONCOURSE, SECTION, RESTROOM, CONCESSIONS
        accessible BOOLEAN NOT NULL,
        x INTEGER NOT NULL,
        y INTEGER NOT NULL,
        current_density REAL DEFAULT 0.0,
        queue_est_min INTEGER DEFAULT 0,
        incident_flag TEXT DEFAULT 'none' -- none, congestion, medical, security
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS zone_edges (
        from_zone TEXT NOT NULL,
        to_zone TEXT NOT NULL,
        base_distance REAL NOT NULL,
        PRIMARY KEY (from_zone, to_zone),
        FOREIGN KEY (from_zone) REFERENCES zones(id),
        FOREIGN KEY (to_zone) REFERENCES zones(id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        language_pref TEXT DEFAULT 'en',
        accessibility_needs TEXT DEFAULT '', -- comma separated e.g. "wheelchair"
        ticket_section TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        current_zone TEXT NOT NULL,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (current_zone) REFERENCES zones(id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL, -- user, assistant
        content TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        detected_language TEXT DEFAULT 'en',
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS decision_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        rule_fired TEXT NOT NULL,
        action_taken TEXT NOT NULL,
        rationale TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        zone_id TEXT NOT NULL,
        severity TEXT NOT NULL, -- info, warning, critical
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved BOOLEAN DEFAULT 0,
        FOREIGN KEY (zone_id) REFERENCES zones(id)
    )
    """)
    
    # Check if zones table has data, if not seed it
    cursor.execute("SELECT COUNT(*) FROM zones")
    if cursor.fetchone()[0] == 0:
        # Seed 12 zones representing a concentric oval stadium layout
        # (x, y) coordinates for mapping out the SVG representation
        zones_data = [
            ("GATE_1", "Gate 1 (North Entrance)", "GATE", 1, 250, 40),
            ("GATE_2", "Gate 2 (East Entrance)", "GATE", 1, 460, 250),
            ("GATE_3", "Gate 3 (South Entrance - Stairs)", "GATE", 0, 250, 460),
            ("GATE_4", "Gate 4 (West Entrance)", "GATE", 1, 40, 250),
            ("CONCOURSE_N", "Concourse North", "CONCOURSE", 1, 250, 110),
            ("CONCOURSE_E", "Concourse East", "CONCOURSE", 1, 390, 250),
            ("CONCOURSE_S", "Concourse South (Stairs Only)", "CONCOURSE", 0, 250, 390),
            ("CONCOURSE_W", "Concourse West", "CONCOURSE", 1, 110, 250),
            ("SECTION_101", "Premium Section 101", "SECTION", 1, 250, 180),
            ("SECTION_102", "Upper Deck 102 (Stairs)", "SECTION", 0, 250, 320),
            ("RESTROOM_A", "Restroom Block A", "RESTROOM", 1, 390, 180),
            ("CONCESSIONS_A", "Concessions/Food Court A", "CONCESSIONS", 1, 110, 180)
        ]
        cursor.executemany("""
        INSERT INTO zones (id, name, type, accessible, x, y, current_density, queue_est_min)
        VALUES (?, ?, ?, ?, ?, ?, 0.1, 2)
        """, zones_data)
        
        # Seed edges (bidirectional connections, stored as two rows)
        edges_data = [
            ("GATE_1", "CONCOURSE_N", 10),
            ("GATE_2", "CONCOURSE_E", 12),
            ("GATE_3", "CONCOURSE_S", 15),
            ("GATE_4", "CONCOURSE_W", 10),
            ("CONCOURSE_N", "CONCOURSE_E", 20),
            ("CONCOURSE_E", "CONCOURSE_S", 22),
            ("CONCOURSE_S", "CONCOURSE_W", 20),
            ("CONCOURSE_W", "CONCOURSE_N", 22),
            ("CONCOURSE_N", "SECTION_101", 8),
            ("CONCOURSE_S", "SECTION_102", 14),
            ("CONCOURSE_E", "RESTROOM_A", 5),
            ("CONCOURSE_W", "CONCESSIONS_A", 6),
            # Seating connections to other zones for alternative route options
            ("SECTION_101", "RESTROOM_A", 12),
            ("SECTION_102", "RESTROOM_A", 18),
            ("SECTION_101", "CONCESSIONS_A", 12)
        ]
        
        bidirectional_edges = []
        for u, v, d in edges_data:
            bidirectional_edges.append((u, v, d))
            bidirectional_edges.append((v, u, d))
            
        cursor.executemany("""
        INSERT INTO zone_edges (from_zone, to_zone, base_distance)
        VALUES (?, ?, ?)
        """, bidirectional_edges)
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
