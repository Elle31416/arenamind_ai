<div align="center">
  <h1>🏆 ArenaMind AI 🏟️</h1>
  <p><strong>Intelligent, Real-Time Stadium Navigation & Crowd Management</strong></p>

  [![Live Demo](https://img.shields.io/badge/🔴_Live_Demo-ArenaMind_AI-success?style=for-the-badge)](https://arenamind-n7fx.onrender.com/)
  
  <p>
    Powered by <strong>FastAPI</strong>, <strong>WebSockets</strong>, and <strong>Google Gemini 2.5 Flash</strong>.
  </p>
</div>

---

## 🌟 The Vision
Navigating massive stadiums and arenas is often a chaotic, frustrating experience for fans—and a logistical nightmare for staff. **ArenaMind AI** solves this by providing a real-time, AI-driven navigation dashboard that dynamically adapts to crowd congestion, accessibility needs, and active stadium events.

It’s not just a map; it’s a living telemetry engine.

---

## 🚀 Live Demo
Experience the system live in your browser:
### 👉 **[https://arenamind-n7fx.onrender.com/](https://arenamind-n7fx.onrender.com/)**

*(Note: Ensure you allow a few seconds for the Render free-tier instance to wake up on your first visit!)*

---

## 💡 Key Features

*   🗺️ **Dynamic Pathfinding (Dijkstra's Engine):** Calculates optimal routes through a 12-zone stadium graph. Edge weights update dynamically based on live crowd density and congestion.
*   🧠 **Context-Aware AI Assistant:** Natural language routing powered by **Gemini 2.5 Flash**. The AI is aware of stadium phases, wait times, and current user locations.
*   🛡️ **Zero-Latency Emergency Fallbacks:** Built-in heuristic engine instantly overrides LLM processing for emergency keywords, providing immediate routing and alerting staff without waiting for API responses.
*   ♿ **Accessibility-First Routing:** Toggle wheelchair accessibility to automatically filter out paths with stairs. If a path becomes completely disconnected, it routes to the nearest accessible safe zone and flags staff.
*   📊 **Real-Time Telemetry & WebSockets:** A simulated 4-second telemetry tick broadcasts live crowd heatmaps and staff alerts across dedicated, isolated WebSocket channels (`/ws/telemetry` & `/ws/staff`).
*   🎨 **Glassmorphic UI:** A beautiful, responsive, dark-mode SVG dashboard built without bloated frontend frameworks.

---

## 🛠️ Technology Stack

*   **Backend Engine:** Python, FastAPI, Uvicorn
*   **Pathfinding Algorithm:** Custom Dijkstra implementation with dynamic weighting
*   **Real-time Comms:** Native WebSockets (Secure, multi-channel)
*   **Artificial Intelligence:** `google-generativeai` (Gemini 2.5 Flash)
*   **Frontend Design:** Vanilla HTML5/JS, Custom CSS Variables, Glassmorphism, Dynamic SVG rendering
*   **Deployment:** Render.com (Unified Single Web Service)

---

## 🏆 Why this stands out for the Hackathon

1.  **Robust Error Handling:** We don't just rely on the AI. If the Gemini API fails, times out, or hits quota limits, the system seamlessly degrades to an **"Offline Mode"** using deterministic graph routing.
2.  **Privacy & Security:** Fan telemetry and Staff operations are split into entirely separate WebSocket channels.
3.  **Real-World Applicability:** The inclusion of dynamic graph weights (crowd routing) and strict accessibility constraints solves a massive real-world logistical problem for mega-events.

---

## 💻 Local Installation

Want to run it locally?

```bash
# 1. Clone the repository
git clone https://github.com/your-username/arenamind_ai.git
cd arenamind_ai

# 2. Install Dependencies
pip install -r requirements.txt

# 3. Set your Gemini API Key
# Windows (PowerShell):
$env:GEMINI_API_KEY="your_api_key_here"
# Mac/Linux:
export GEMINI_API_KEY="your_api_key_here"

# 4. Start the Application
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
Navigate to `http://127.0.0.1:8000` to view the local instance!

---
<div align="center">
  <i>Built with ❤️ for the Hackathon.</i>
</div>
