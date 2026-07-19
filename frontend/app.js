// ArenaMind AI Frontend Logic

const isFileProtocol = window.location.protocol === 'file:';
const backendUrl = (isFileProtocol || window.location.hostname === 'localhost' || window.location.hostname === '') ? 'localhost:8000' : window.location.host;
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const httpProtocol = isFileProtocol ? 'http:' : window.location.protocol;

// Global state variables
let zonesData = [];
let activeRoutePath = [];
let currentUserId = "fan_user_99";
let activePhase = "PRE_MATCH";

// Localization Dictionary
const localizations = {
    en: {
        greeting: "Welcome to ArenaMind AI! Ask me anything about routes, restrooms, or current stadium crowd conditions.",
        inputPlaceholder: "Type your stadium inquiry...",
        accessibilityAssist: "ACCESSIBILITY ASSIST REQUIRED",
        emergencyDetected: "EMERGENCY DETECTED",
        loading: "ArenaMind is thinking...",
        routeFound: "Route loaded on map."
    },
    es: {
        greeting: "¡Bienvenido a ArenaMind AI! Pregúnteme cualquier cosa sobre rutas, baños o condiciones de multitud en el estadio.",
        inputPlaceholder: "Escriba su consulta sobre el estadio...",
        accessibilityAssist: "ASISTENCIA DE ACCESIBILIDAD REQUERIDA",
        emergencyDetected: "EMERGENCIA DETECTADA",
        loading: "ArenaMind está pensando...",
        routeFound: "Ruta cargada en el mapa."
    },
    fr: {
        greeting: "Bienvenue sur ArenaMind AI ! Posez-moi des questions sur les itinéraires, les toilettes ou l'affluence dans le stade.",
        inputPlaceholder: "Saisissez votre demande...",
        accessibilityAssist: "ASSISTANCE ACCESSIBILITÉ REQUISE",
        emergencyDetected: "URGENCE DÉTECTÉE",
        loading: "ArenaMind réfléchit...",
        routeFound: "Itinéraire affiché sur la carte."
    },
    ar: {
        greeting: "مرحبًا بك في ArenaMind AI! اسألني عن أي شيء يخص الطرق، دورات المياه، أو حالة الازدحام الحالية في الملعب.",
        inputPlaceholder: "اكتب استفسارك هنا...",
        accessibilityAssist: "مطلوب مساعدة ذوي الاحتياجات الخاصة",
        emergencyDetected: "تم اكتشاف حالة طوارئ",
        loading: "ArenaMind يفكر...",
        routeFound: "تم تحميل المسار على الخريطة."
    }
};

// Connect to WebSockets
const telemetryWs = new WebSocket(`${wsProtocol}//${backendUrl}/ws/telemetry`);
const staffWs = new WebSocket(`${wsProtocol}//${backendUrl}/ws/staff`);

// Listen to Telemetry Channel (Public)
telemetryWs.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "telemetry") {
        zonesData = data.zones;
        activePhase = data.phase;
        
        // Update header phase status
        document.getElementById("current-phase-text").innerText = activePhase;
        
        // Redraw stadium SVG
        drawStadiumMap();
    }
};

// Listen to Staff Channel (Private)
staffWs.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "initial_alerts" || data.type === "alert") {
        updateAlertsFeed(data);
    } else if (data.type === "decision_log") {
        addDecisionTrace(data.log);
    }
};

// REST Admin calls
async function setPhase(phase) {
    try {
        const response = await fetch(`${httpProtocol}//${backendUrl}/api/admin/phase?phase=${phase}`, {
            method: 'POST'
        });
        const res = await response.json();
        console.log("Phase set:", res);
    } catch (err) {
        console.error("Error setting phase:", err);
    }
}

async function injectScenario(zoneId, density, incidentFlag) {
    try {
        const response = await fetch(`${httpProtocol}//${backendUrl}/api/admin/scenario`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ zoneId, density, incidentFlag })
        });
        const res = await response.json();
        console.log("Scenario injected:", res);
    } catch (err) {
        console.error("Error injecting scenario:", err);
    }
}

async function resetScenarios() {
    // Clear incident flags on all seeded zones
    const zones = [
        "GATE_1", "GATE_2", "GATE_3", "GATE_4", 
        "CONCOURSE_N", "CONCOURSE_E", "CONCOURSE_S", "CONCOURSE_W",
        "SECTION_101", "SECTION_102", "RESTROOM_A", "CONCESSIONS_A"
    ];
    for (const z of zones) {
        await injectScenario(z, 0.1, 'none');
    }
}

async function resolveAlert(alertId) {
    try {
        await fetch(`${httpProtocol}//${backendUrl}/api/alerts/resolve?alert_id=${alertId}`, {
            method: 'POST'
        });
    } catch (err) {
        console.error("Error resolving alert:", err);
    }
}

// Draw/Update Stadium SVG Floor Plan
function drawStadiumMap() {
    const zonesLayer = document.getElementById("svg-zones-layer");
    const userMarkerLayer = document.getElementById("svg-user-marker-layer");
    const routeLayer = document.getElementById("svg-route-layer");
    
    zonesLayer.innerHTML = "";
    userMarkerLayer.innerHTML = "";
    
    // Draw all stadium zones
    zonesData.forEach(zone => {
        const density = zone.current_density;
        const x = zone.x;
        const y = zone.y;
        
        // Heatmap color calculation (green to yellow to red)
        let color, strokeColor;
        if (zone.incident_flag && zone.incident_flag !== 'none') {
            color = 'rgba(244, 63, 94, 0.55)'; // glowing red for incidents
            strokeColor = '#f43f5e';
        } else if (density <= 0.35) {
            color = 'rgba(16, 185, 129, 0.2)'; // Clear emerald
            strokeColor = '#10b981';
        } else if (density <= 0.70) {
            color = 'rgba(245, 158, 11, 0.3)'; // Mod amber
            strokeColor = '#f59e0b';
        } else {
            color = 'rgba(239, 68, 68, 0.45)'; // Congested red
            strokeColor = '#ef4444';
        }
        
        let shapeHtml = "";
        
        // Draw different shapes for different zone types
        if (zone.type === "GATE") {
            // Draw gates as larger blocks
            shapeHtml = `<rect x="${x-18}" y="${y-18}" width="36" height="36" rx="8" fill="${color}" stroke="${strokeColor}" stroke-width="2" class="cursor-pointer transition-all duration-300 hover:opacity-80" onclick="selectZone('${zone.id}')" onmouseover="showTooltip(event, '${zone.id}')" onmouseout="hideTooltip()" />`;
        } else if (zone.type === "CONCOURSE") {
            // Draw concourses as large circles
            shapeHtml = `<circle cx="${x}" cy="${y}" r="22" fill="${color}" stroke="${strokeColor}" stroke-width="2" class="cursor-pointer transition-all duration-300 hover:opacity-80" onclick="selectZone('${zone.id}')" onmouseover="showTooltip(event, '${zone.id}')" onmouseout="hideTooltip()" />`;
        } else if (zone.type === "SECTION") {
            // Draw sections as seats (rectangles)
            shapeHtml = `<rect x="${x-22}" y="${y-14}" width="44" height="28" rx="6" fill="${color}" stroke="${strokeColor}" stroke-width="2" class="cursor-pointer transition-all duration-300 hover:opacity-80" onclick="selectZone('${zone.id}')" onmouseover="showTooltip(event, '${zone.id}')" onmouseout="hideTooltip()" />`;
        } else {
            // Amenities (Restrooms / concessions) as triangles/polygons
            const pts = `${x},${y-18} ${x+18},${y+14} ${x-18},${y+14}`;
            shapeHtml = `<polygon points="${pts}" fill="${color}" stroke="${strokeColor}" stroke-width="2" class="cursor-pointer transition-all duration-300 hover:opacity-80" onclick="selectZone('${zone.id}')" onmouseover="showTooltip(event, '${zone.id}')" onmouseout="hideTooltip()" />`;
        }
        
        // Add zone labels
        let labelIcon = "";
        if (zone.type === "RESTROOM") labelIcon = "🚻";
        else if (zone.type === "CONCESSIONS") labelIcon = "🍔";
        else labelIcon = zone.id.replace("_", " ");
        
        const labelHtml = `<text x="${x}" y="${y+4}" fill="#e2e8f0" font-size="8" font-weight="bold" text-anchor="middle" pointer-events="none" font-family="Outfit">${labelIcon}</text>`;
        
        zonesLayer.innerHTML += shapeHtml + labelHtml;
    });

    // Draw active user marker
    const selectedZoneId = document.getElementById("user-zone").value;
    const userZone = zonesData.find(z => z.id === selectedZoneId);
    if (userZone) {
        const uMarker = `
            <circle cx="${userZone.x}" cy="${userZone.y}" r="30" fill="none" stroke="#0ea5e9" stroke-width="1.5" class="animate-ping opacity-60 pointer-events-none" />
            <circle cx="${userZone.x}" cy="${userZone.y}" r="6" fill="#0ea5e9" stroke="#ffffff" stroke-width="1.5" class="pointer-events-none" />
        `;
        userMarkerLayer.innerHTML = uMarker;
    }
    
    // Draw path overlays if routing is loaded
    drawRoutePath();
}

// Plot path on map
function drawRoutePath() {
    const routeLayer = document.getElementById("svg-route-layer");
    routeLayer.innerHTML = "";
    
    if (!activeRoutePath || activeRoutePath.length < 2) {
        return;
    }
    
    let pathPoints = [];
    activeRoutePath.forEach(nodeId => {
        const zone = zonesData.find(z => z.id === nodeId);
        if (zone) {
            pathPoints.push(`${zone.x},${zone.y}`);
        }
    });
    
    if (pathPoints.length >= 2) {
        const pathData = `M ${pathPoints.join(" L ")}`;
        
        // Animate route line
        const routePathHtml = `
            <path d="${pathData}" fill="none" stroke="#4f46e5" stroke-dasharray="8,6" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round" class="route-path pointer-events-none" />
            <path d="${pathData}" fill="none" stroke="#0ea5e9" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="pointer-events-none opacity-80" />
        `;
        routeLayer.innerHTML = routePathHtml;
    }
}

// Dropdown synchronization
function selectZone(zoneId) {
    document.getElementById("user-zone").value = zoneId;
    drawStadiumMap();
}

// Sync current zone marker when dropdown changes
document.getElementById("user-zone").addEventListener("change", () => {
    drawStadiumMap();
});

// Hover tooltip triggers
function showTooltip(event, zoneId) {
    const zone = zonesData.find(z => z.id === zoneId);
    if (!zone) return;
    
    const tooltip = document.getElementById("map-tooltip");
    document.getElementById("tooltip-name").innerText = zone.name;
    document.getElementById("tooltip-density").innerText = Math.round(zone.current_density * 100) + "%";
    document.getElementById("tooltip-queue").innerText = zone.queue_est_min;
    
    const incidentSpan = document.getElementById("tooltip-incident");
    if (zone.incident_flag && zone.incident_flag !== 'none') {
        incidentSpan.innerText = zone.incident_flag;
        incidentSpan.className = "px-2 py-0.5 rounded text-[10px] font-extrabold uppercase bg-rose-950/80 border border-rose-800 text-rose-400";
    } else {
        incidentSpan.innerText = "normal";
        incidentSpan.className = "px-2 py-0.5 rounded text-[10px] font-extrabold uppercase bg-emerald-950/40 border border-emerald-800 text-emerald-400";
    }
    
    tooltip.style.opacity = "1";
    tooltip.style.pointerEvents = "auto";
}

function hideTooltip() {
    const tooltip = document.getElementById("map-tooltip");
    tooltip.style.opacity = "0";
    tooltip.style.pointerEvents = "none";
}

// Chat interface updates
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatMessages = document.getElementById("chat-messages");

chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    
    // Get parameters
    const lang = document.getElementById("user-lang").value;
    const currentZone = document.getElementById("user-zone").value;
    const ticketSec = document.getElementById("user-section").value;
    
    const accessNeeds = [];
    if (document.getElementById("user-accessible-wheelchair").checked) accessNeeds.push("wheelchair");
    if (document.getElementById("user-accessible-visual").checked) accessNeeds.push("visual-impairment");
    
    // Add user bubble
    appendChatBubble("user", message);
    chatInput.value = "";
    
    // Add thinking loader
    const loaderId = appendChatLoader(lang);
    
    try {
        const response = await fetch(`${httpProtocol}//${backendUrl}/api/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                userId: currentUserId,
                message: message,
                currentZone: currentZone,
                language: lang,
                accessibilityNeeds: accessNeeds,
                ticketSection: ticketSec
            })
        });
        
        const data = await response.json();
        
        // Remove loader
        document.getElementById(loaderId).remove();
        
        // Add assistant response
        appendChatBubble("assistant", data.text);
        
        // Set routing route path if exists
        if (data.route && data.route.success) {
            activeRoutePath = data.route.path;
            drawStadiumMap();
        } else {
            // Keep existing route or clear it if not routing
            activeRoutePath = [];
            drawStadiumMap();
        }
        
    } catch (err) {
        console.error("Query API Error:", err);
        document.getElementById(loaderId).remove();
        appendChatBubble("assistant", "Error: Connection lost. Failsafe Offline Mode active.");
    }
});

function appendChatBubble(role, text) {
    const bubble = document.createElement("div");
    bubble.className = "flex space-x-2.5 items-start animate-fade-in";
    
    if (role === "user") {
        bubble.className += " justify-end";
        bubble.innerHTML = `
            <div class="p-3 rounded-2xl rounded-tr-none bg-indigo-600 text-white max-w-[85%]">
                ${text.replace(/\n/g, "<br>")}
            </div>
            <div class="w-8 h-8 rounded-lg bg-indigo-500/20 flex items-center justify-center flex-shrink-0">
                <span class="text-xs font-bold text-indigo-300">U</span>
            </div>
        `;
    } else {
        bubble.innerHTML = `
            <div class="w-8 h-8 rounded-lg bg-indigo-900/40 border border-indigo-500/20 flex items-center justify-center flex-shrink-0">
                <span class="text-xs font-bold text-indigo-400">AM</span>
            </div>
            <div class="p-3 rounded-2xl rounded-tl-none glass-card max-w-[85%] text-slate-300">
                ${text.replace(/\n/g, "<br>")}
            </div>
        `;
    }
    chatMessages.appendChild(bubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendChatLoader(lang) {
    const loaderId = "loader_" + Date.now();
    const loader = document.createElement("div");
    loader.id = loaderId;
    loader.className = "flex space-x-2.5 items-start animate-pulse";
    
    const loadingText = localizations[lang] ? localizations[lang].loading : localizations['en'].loading;
    
    loader.innerHTML = `
        <div class="w-8 h-8 rounded-lg bg-indigo-900/40 border border-indigo-500/20 flex items-center justify-center flex-shrink-0">
            <span class="text-xs font-bold text-indigo-400">AM</span>
        </div>
        <div class="p-3 rounded-2xl rounded-tl-none glass-card text-xs text-slate-500">
            ${loadingText}
        </div>
    `;
    chatMessages.appendChild(loader);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return loaderId;
}

// Update localizations on language dropdown change
document.getElementById("user-lang").addEventListener("change", (e) => {
    const lang = e.target.value;
    const greeting = localizations[lang] ? localizations[lang].greeting : localizations['en'].greeting;
    const placeholder = localizations[lang] ? localizations[lang].inputPlaceholder : localizations['en'].inputPlaceholder;
    
    chatInput.placeholder = placeholder;
    
    // Clear chat and replace default greeting
    chatMessages.innerHTML = "";
    appendChatBubble("assistant", greeting);
});

// Staff Alerts panel updates
function updateAlertsFeed(data) {
    const feed = document.getElementById("alerts-feed");
    const countBadge = document.getElementById("alerts-count");
    
    let alertsList = [];
    if (data.type === "initial_alerts") {
        alertsList = data.alerts;
    } else {
        // Single alert added to top
        // Get current list from DOM
        const currentAlerts = Array.from(feed.querySelectorAll("[data-alert-id]")).map(el => {
            return {
                id: parseInt(el.getAttribute("data-alert-id")),
                zone_id: el.getAttribute("data-zone-id"),
                severity: el.getAttribute("data-severity"),
                message: el.querySelector(".alert-msg").innerText,
                created_at: el.querySelector(".alert-time").innerText
            }
        });
        
        // Avoid duplicate alerts
        if (!currentAlerts.some(a => a.id === data.alert.id)) {
            alertsList = [data.alert, ...currentAlerts];
        } else {
            alertsList = currentAlerts;
        }
    }
    
    countBadge.innerText = alertsList.length;
    
    if (alertsList.length === 0) {
        feed.innerHTML = `
            <div class="p-3 rounded-lg glass-card border-slate-800 text-slate-400 text-center py-6 font-medium">
                No active alerts reported.
            </div>
        `;
        return;
    }
    
    feed.innerHTML = "";
    
    alertsList.forEach(alert => {
        const item = document.createElement("div");
        item.setAttribute("data-alert-id", alert.id);
        item.setAttribute("data-zone-id", alert.zone_id);
        item.setAttribute("data-severity", alert.severity);
        
        let borderClass = "border-slate-800";
        let bgClass = "bg-slate-900/30";
        let severityLabel = alert.severity.toUpperCase();
        let glowClass = "";
        
        if (alert.severity === "critical") {
            borderClass = "border-rose-800/80";
            bgClass = "bg-rose-950/20";
            glowClass = "glow-red";
        } else if (alert.severity === "warning") {
            borderClass = "border-amber-800/60";
            bgClass = "bg-amber-950/10";
            glowClass = "glow-yellow";
        }
        
        item.className = `p-3 rounded-xl glass-card border ${borderClass} ${bgClass} ${glowClass} flex flex-col space-y-2 transition-all duration-300`;
        item.innerHTML = `
            <div class="flex justify-between items-center">
                <span class="text-[10px] font-bold tracking-wider px-2 py-0.5 rounded ${alert.severity === 'critical' ? 'bg-rose-950 border border-rose-800 text-rose-400' : 'bg-amber-950 border border-amber-800 text-amber-400'}">${severityLabel}</span>
                <span class="text-[9px] text-slate-500 alert-time">${alert.created_at}</span>
            </div>
            <p class="text-slate-300 font-semibold leading-relaxed alert-msg">${alert.message}</p>
            <div class="flex justify-end pt-1">
                <button onclick="resolveAlert(${alert.id})" class="px-2 py-1 bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white rounded border border-glassBorder text-[9px] font-bold transition">Resolve Incident</button>
            </div>
        `;
        feed.appendChild(item);
    });
}

// Add Decision trace log
function addDecisionTrace(log) {
    const traceFeed = document.getElementById("decision-trace-feed");
    
    // Clear greeting placeholder if present
    const placeholder = traceFeed.querySelector(".font-sans");
    if (placeholder) {
        traceFeed.innerHTML = "";
    }
    
    const logItem = document.createElement("div");
    logItem.className = "p-3 rounded-lg bg-slate-950 border border-glassBorder space-y-1.5 animate-fade-in";
    
    let badgeColor = "bg-indigo-950 border-indigo-800 text-indigo-400";
    if (log.rule_fired.includes("EMERGENCY")) {
        badgeColor = "bg-rose-950 border-rose-800 text-rose-400";
    } else if (log.rule_fired.includes("ACCESSIBILITY") || log.rule_fired.includes("CONGESTION")) {
        badgeColor = "bg-amber-950 border-amber-800 text-amber-400";
    }
    
    logItem.innerHTML = `
        <div class="flex justify-between items-center text-[9px] border-b border-glassBorder pb-1 mb-1">
            <span class="font-extrabold px-1.5 py-0.5 rounded border ${badgeColor}">${log.rule_fired}</span>
            <span class="text-slate-600">${log.timestamp}</span>
        </div>
        <div class="text-slate-300 font-bold">Action: <span class="text-slate-200 font-normal">${log.action_taken}</span></div>
        <div class="text-slate-400">Trace Rationale: <span class="text-slate-300">${log.rationale}</span></div>
    `;
    
    // Prepend to top of feed
    traceFeed.insertBefore(logItem, traceFeed.firstChild);
    
    // Prune logs if > 15
    if (traceFeed.children.length > 15) {
        traceFeed.lastChild.remove();
    }
}
