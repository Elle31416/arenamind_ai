import heapq
from backend.database import get_db_connection

def build_graph(accessibility_needed=False):
    """
    Builds an adjacency list representation of the stadium zones and edges from SQLite.
    If accessibility_needed is True, excludes non-accessible zones from the graph.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch all zones and their accessibility status
    cursor.execute("SELECT id, name, accessible, current_density FROM zones")
    zones = {row["id"]: dict(row) for row in cursor.fetchall()}
    
    # Fetch edges
    cursor.execute("SELECT from_zone, to_zone, base_distance FROM zone_edges")
    edges = cursor.fetchall()
    
    conn.close()
    
    # Adjacency list
    graph = {zone_id: [] for zone_id in zones}
    
    for edge in edges:
        u = edge["from_zone"]
        v = edge["to_zone"]
        dist = edge["base_distance"]
        
        # If accessibility is needed, skip edges connected to non-accessible zones
        if accessibility_needed:
            if not zones[u]["accessible"] or not zones[v]["accessible"]:
                continue
                
        # Calculate dynamic weight based on crowd density of destination zone
        # weight = base_distance * (1 + destination_crowd_density * 5)
        dest_density = zones[v]["current_density"]
        weight = dist * (1.0 + dest_density * 5.0)
        
        graph[u].append((v, weight))
        
    return graph, zones

def dijkstra(graph, start, end):
    """
    Standard Dijkstra's algorithm.
    Returns (path_list, total_weight) or (None, infinity) if no path exists.
    """
    if start not in graph or end not in graph:
        return None, float('inf')
        
    queue = [(0, start, [])]
    visited = set()
    
    while queue:
        (cost, node, path) = heapq.heappop(queue)
        
        if node in visited:
            continue
            
        visited.add(node)
        path = path + [node]
        
        if node == end:
            return path, cost
            
        for next_node, weight in graph[node]:
            if next_node not in visited:
                heapq.heappush(queue, (cost + weight, next_node, path))
                
    return None, float('inf')

def get_route(start, end, accessibility_needed=False):
    """
    Calculates the shortest route between start and end.
    Applies dynamic weights and accessibility rules.
    If accessibility is needed and no path exists, falls back to routing
    to the nearest accessible zone to the destination and flags a staff warning.
    
    Returns a dict with:
      - success: bool
      - path: list of zone IDs
      - cost: float
      - is_fallback: bool
      - fallback_target: str or None
      - message: str
    """
    # 1. Build normal or accessible graph
    graph, zones = build_graph(accessibility_needed=accessibility_needed)
    
    # Check if start or end exists
    if start not in zones or end not in zones:
        return {
            "success": False,
            "path": [],
            "cost": float('inf'),
            "is_fallback": False,
            "fallback_target": None,
            "message": "Start or destination zone does not exist."
        }
        
    # Check if target is same as start
    if start == end:
        return {
            "success": True,
            "path": [start],
            "cost": 0.0,
            "is_fallback": False,
            "fallback_target": None,
            "message": f"You are already at {zones[start]['name']}."
        }
        
    # Try finding path
    path, cost = dijkstra(graph, start, end)
    
    if path is not None:
        return {
            "success": True,
            "path": path,
            "cost": cost,
            "is_fallback": False,
            "fallback_target": None,
            "message": f"Route found from {zones[start]['name']} to {zones[end]['name']}."
        }
        
    # 2. Fallback logic for accessibility disconnection
    if accessibility_needed:
        # Build full graph to compute physical proximity (base distance only to reflect true proximity)
        full_graph, _ = build_graph(accessibility_needed=False)
        
        # Find all accessible zones
        accessible_zones = [z_id for z_id, z_data in zones.items() if z_data["accessible"]]
        
        # Sort accessible zones by proximity to the intended destination `end` on the full graph
        candidates = []
        for ac_zone in accessible_zones:
            if ac_zone == start:
                continue
            # Find distance from ac_zone to end on full graph
            _, dist_to_end = dijkstra(full_graph, ac_zone, end)
            if dist_to_end != float('inf'):
                candidates.append((dist_to_end, ac_zone))
                
        candidates.sort() # Closest to end first
        
        # Try routing from start to the candidate accessible zones
        for _, fallback_target in candidates:
            # Try finding path to fallback_target on the accessible-only graph
            fallback_path, fallback_cost = dijkstra(graph, start, fallback_target)
            if fallback_path is not None:
                orig_name = zones[end]["name"]
                fallback_name = zones[fallback_target]["name"]
                return {
                    "success": True,
                    "path": fallback_path,
                    "cost": fallback_cost,
                    "is_fallback": True,
                    "fallback_target": fallback_target,
                    "message": f"No fully accessible path is currently available to {orig_name}. We have routed you to the nearest accessible zone {fallback_name} instead, and a staff member has been notified to assist you with physical transfer."
                }
                
    # 3. Complete failure fallback (no path at all, even on full graph or no accessible paths found)
    return {
        "success": False,
        "path": [],
        "cost": float('inf'),
        "is_fallback": False,
        "fallback_target": None,
        "message": "No route could be found. Please wait where you are, and emergency staff will contact you."
    }

if __name__ == "__main__":
    # Quick debug run
    print("Testing get_route:")
    # Able-bodied route
    r1 = get_route("GATE_1", "SECTION_102", accessibility_needed=False)
    print("Normal Route:", r1["path"], "Cost:", r1["cost"])
    
    # Accessible route (SECTION_102 is inaccessible)
    r2 = get_route("GATE_1", "SECTION_102", accessibility_needed=True)
    print("Accessible Route:", r2["path"], "Fallback Target:", r2["fallback_target"], "Message:", r2["message"])
