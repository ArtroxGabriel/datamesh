# Node-Link Network & Communications Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Build an interactive **Node-Link Communication & Topology** visualizer in the Web Dashboard (`/network`), giving a real-time view of distributed processes and protocol exchanges (UDP Multicast Discovery, UDP Telemetry, UDP Anomaly Alerts, gRPC Actuation, and TCP Framing).

---

## File Structure & Responsibilities

- **`client/static/network.html`** (New): Single-page visualizer with an animated HTML5 Canvas / SVG node-link graph of all nodes (Gateway, Client, AC, Sensors, PDUs), live packet flow particles, discovery handshake indicator, and a real-time protocol packet inspector.
- **`client/app.py`** (Modified): Register `/network` endpoint serving `network.html`.
- **`client/static/index.html` & `client/static/events.html`** (Modified): Update navigation bar to provide seamless links between Dashboard (`/`), Topology (`/network`), and Timeline (`/events`).
- **`tests/test_client_app.py`** (Modified): Add unit and integration tests for `/network` route and template serving.

---

### Task 1: Add `/network` Route to Web Client and Update Navigation

**Files to modify:**
- `client/app.py`
- `client/static/index.html`
- `client/static/events.html`
- `tests/test_client_app.py`

- [ ] **Step 1: Write failing test for `/network` route in `tests/test_client_app.py`**
  Add test checking `GET /network` returns status 200 with HTML containing title and canvas/container elements.
- [ ] **Step 2: Run test to confirm it fails**
  Run `rtk uv run pytest tests/test_client_app.py -k test_network`
- [ ] **Step 3: Implement route in `client/app.py` and create placeholder `client/static/network.html`**
  Add `@app.get("/network", response_class=HTMLResponse)` calling `_serve_static_page("network.html")`.
- [ ] **Step 4: Update header navigation bars**
  Add navigation links (`Dashboard`, `Topologia de Rede`, `Linha do Tempo`) across `index.html` and `events.html`.
- [ ] **Step 5: Verify tests pass**
  Run `rtk uv run pytest tests/test_client_app.py`
- [ ] **Step 6: Commit changes**
  Run `rtk git commit` with message `feat(client): add /network route and update navigation bars`

---

### Task 2: Build the Node-Link Topology Graph in `client/static/network.html`

**Files to modify:**
- `client/static/network.html`

- [ ] **Step 1: Design HTML layout and responsive styling**
  Follow DCIM styling (header branding, dark/light theme accents, status badges, topology container, and packet inspector table).
- [ ] **Step 2: Implement Node-Link Graph engine (HTML5 Canvas / SVG)**
  Render nodes:
  - Central Gateway (`127.0.0.1`, TCP: 9997, UDP: 9998, Multicast: 239.255.0.1:9999).
  - Web Client (`:8080`, TCP: 9997).
  - Dynamic Discovered Sources (AC, Temp Sensors, PDUs) fetched from `/api/devices`.
- [ ] **Step 3: Implement animated packet particle flow along protocol edges**
  - 🟣 UDP Multicast Discovery pulses (Gateway $\to$ Multicast group $\to$ Sources).
  - 🔵 UDP Unicast Telemetry streams (Sources $\to$ Gateway :9998).
  - 🔴 UDP Event Anomaly alerts (highlighted pulses when sensor is in alert).
  - 🟢 gRPC Actuation (Gateway $\leftrightarrow$ AC :50051).
  - 🟠 TCP Framing (Web Client $\leftrightarrow$ Gateway :9997).
- [ ] **Step 4: Add Discovery Handshake Visualizer**
  Provide a visual banner / node highlight when a newly added device appears or status changes:
  `Beacon Received` $\to$ `DeviceInfo Sent` $\to$ `Registered ONLINE`.
- [ ] **Step 5: Add Real-time Protocol Packet Inspector**
  Interactive table below canvas polling `/api/events` and `/api/telemetry/history` with protocol filter pills (`Todos`, `UDP Multicast`, `UDP Unicast`, `gRPC`, `TCP`).
- [ ] **Step 6: Verify page rendering and syntax**
  Check with `rtk uv run pytest` and manual browser check or curl.
- [ ] **Step 7: Commit changes**
  Run `rtk git commit` with message `feat(client): implement interactive node-link network visualizer`

---

### Task 3: Interactive Demo Integration & Verification

**Files to modify:**
- `scripts/run_demo.sh`
- `README.md`
- `tests/test_client_app.py`

- [ ] **Step 1: Update demo console summary in `scripts/run_demo.sh`**
  Include `Topologia: http://localhost:${WEB_PORT}/network` in console banner.
- [ ] **Step 2: Update documentation in `README.md`**
  Document the `/network` page and its interactive node-link features.
- [ ] **Step 3: Run full verification suite**
  - Run `rtk uv run pytest` (coverage $\ge 80\%$)
  - Run `rtk uv run ruff check .` and `rtk uv run ruff format --check .`
  - Run `mise exec -- go test ./sources/pdu/...`
- [ ] **Step 4: Commit changes**
  Run `rtk git commit` with message `docs(demo): document /network visualization page in demo and readme`
