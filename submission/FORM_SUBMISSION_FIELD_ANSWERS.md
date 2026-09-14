# Sentinel - Hackathon Submission Form Answers

Use this guide to copy-paste exact, professional responses into each field of the Google Form.

---

## 1. Project & Team Information

### Team Name *
KodeMatrix

### Proposed Solution *
Sentinel is an integrated Statewide CCTV Management & ANPR Surveillance Platform. It ingests live RTSP camera feeds across Gujarat, maps 30 camera nodes on an interactive GIS map, performs continuous license plate detection using YOLOv9 & fast-alpr with Indian plate-grammar correction, enforces real-time watchlist alert notifications via WebSockets, reconstructs vehicle travel routes across camera locations, and provides audited XLSX/PDF evidence exports.

### Key Features * (One per line)
- Live GIS Camera Map with department, status layers & location provenance
- Real-Time ANPR Pipeline with track-level voting & Indian plate grammar correction
- Low-Resolution Partial Read Guard preventing false-positive alerts
- Watchlist Matching with instant WebSocket alert toasts & acknowledge workflow
- Vehicle Route Reconstruction with speed estimation & impossible transition flagging
- Contract-First VAHAN Vehicle Adapter for registration particulars enrichment
- Audited Output Report Exports (XLSX & PDF) with audit trail logging

### Expected Impact *
- Eliminates false-positive alerts by enforcing Indian plate grammar and resolution thresholds before alert dispatch.
- Enables automated statewide tracking of stolen and wanted vehicles across multi-camera corridors.
- Provides actionable optics insights proving where ANPR is viable (toll plazas/checkposts) vs wide-area overview cameras.
- Establishes end-to-end security compliance with role-based access control (RBAC) and complete audit logging for every citizen search.

---

## 2. Technical Stack

### Frontend
- [x] **React**

### Backend
- [x] **FastAPI**

### Database
- [x] **PostgreSQL**

### AI Models
YOLOv9 (License Plate End-to-End Detection), fast-alpr (CCT-S-v2 Global OCR), RF-DETR (Vehicle & Pedestrian Object Detection)

### APIs Used
Sentinel Sandbox RTSP Ingest API, VAHAN Vehicle Registry Adapter API, Leaflet GIS & OSRM Routing API, WebSocket Alerting API

### Cloud Platform
- [x] **On-Premise** (or select **Other**: Local Edge Stack with Cloudflare Tunnel)

### Programming Languages
Python, TypeScript, JavaScript, SQL, HTML, CSS

### Frameworks
FastAPI, React, PyTorch, OpenCV, ONNX Runtime, Leaflet.js, SQLAlchemy, Pydantic

### Other Tools
Docker, GitHub, Uvicorn, Vite, PostgreSQL / Supabase, Pydantic-Settings

---

## 3. Documents & Drive Links

### Solution Presentation Link *
https://drive.google.com/drive/folders/1dfKs9nYNW_KThp3rWlwQcQxe7_c-eQca?usp=drive_link

### High-Level Design / Architecture Document Link *
https://drive.google.com/drive/folders/1dfKs9nYNW_KThp3rWlwQcQxe7_c-eQca?usp=drive_link

### Workflow / Integration Diagram Link *
https://drive.google.com/drive/folders/1dfKs9nYNW_KThp3rWlwQcQxe7_c-eQca?usp=drive_link
(Or Direct PDF Link: https://raw.githubusercontent.com/DevamShah1211/Sentinel-Hackathone/main/submission/Sentinel-WORKFLOW-DIAGRAM.pdf)

### Screenshots Folder Link
https://drive.google.com/drive/folders/1dfKs9nYNW_KThp3rWlwQcQxe7_c-eQca?usp=drive_link

### Submit your solution (Video) and paste the Google Drive link
https://drive.google.com/drive/folders/1dfKs9nYNW_KThp3rWlwQcQxe7_c-eQca?usp=drive_link

### Any other document or video submission
https://github.com/DevamShah1211/Sentinel-Hackathone
