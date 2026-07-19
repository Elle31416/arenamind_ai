# ArenaMind AI — Render.com Deployment Guide

Since the FastAPI backend has been updated to serve the static frontend files directly from the root endpoint, you can deploy the entire full-stack application as a **single Web Service** on Render.com in "one go".

---

## Prerequisites

1.  A **GitHub repository** containing your clean project commits.
2.  A **Render.com** account (Free tier is sufficient).
3.  Your new **Gemini API Key** (`AIzaSy...`).

---

## Step-by-Step Deployment on Render

### 1. Push Code to GitHub
Ensure you have force-pushed the clean commit history (which excludes the local database and pycache folders) to your remote GitHub repository:
```bash
git push origin main --force
```

---

### 2. Create a Web Service on Render
1.  Log in to the **[Render Dashboard](https://dashboard.render.com)**.
2.  Click **New +** in the top-right corner and select **Web Service**.
3.  Connect your GitHub repository (Render will prompt you to authorize GitHub if you haven't already).
4.  Select your `arenamind_ai` repository.

---

### 3. Configure the Service Settings
Fill out the configuration form with these exact settings:

*   **Name**: `arenamind-ai` (or any custom name)
*   **Region**: Select the region closest to you (e.g., Oregon, Ohio, Frankfurt, Singapore)
*   **Branch**: `main`
*   **Language**: `Python 3` (Render will auto-detect Python since we have `requirements.txt`)
*   **Build Command**:
    ```bash
    pip install -r requirements.txt
    ```
*   **Start Command**:
    ```bash
    python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
    ```

---

### 4. Inject Environment Variables
Before clicking deploy, scroll down and click **Advanced** to add environment variables:

1.  Click **Add Environment Variable**:
    *   **Key**: `GEMINI_API_KEY`
<<<<<<< HEAD
    *   **Value**: `YOUR_NEW_API_KEY_HERE` (Paste your new API key from Google AI Studio)
=======
    *   **Value**: `AIzaSyDSp1WRaFxkeRS0mK0smxUAiq3JOcWXAQk` (or your newly rotated API key)
>>>>>>> 5f26eac9a0163686a5d45435aa6c5afce7c51093
2.  Click **Add Environment Variable** (Optional: sets production environment config):
    *   **Key**: `PYTHONUNBUFFERED`
    *   **Value**: `1`

---

### 5. Deploy & Verify
1.  Click **Create Web Service**.
2.  Render will pull the code, run the build command (`pip install -r requirements.txt`), and spin up the server.
3.  Once the build logs show `Application startup complete`, click your service's live URL (e.g., `https://arenamind-ai.onrender.com`).

---

## Technical Notes

*   **Single Instance Pinning**: The project requires in-memory state tracking for dynamic crowd densities and phase schedules. By default, Render Free Tier spins up exactly `1` instance, which avoids distributed state issues.
*   **WebSocket Connections**: The frontend is configured to detect `window.location.host` and `window.location.protocol` dynamically. Once deployed on Render under HTTPS, the client will automatically establish secure WebSocket connections (`wss://`) and secure HTTPS API requests to the same domain.
