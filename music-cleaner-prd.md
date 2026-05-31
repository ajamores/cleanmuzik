# Music Cleaner — PRD & Ticket Decomposition

**Version:** 0.1  
**Author:** Armand Jamores  
**Status:** Draft  
**Date:** 2026-05-30

---

## 1. Overview

Music Cleaner is a self-hosted web application that allows users to clean up their music library by identifying tracks via audio fingerprinting and writing correct metadata (title, artist, album, album art) back to the original files. It is designed to run on a home server or VPS and be accessible from any device on the network or internet.

Users select a batch of music files through the browser UI, the server processes each file sequentially through the Shazam fingerprinting service, and the cleaned files are returned for download. Nothing is stored permanently — files are processed in a temporary directory and deleted after the session.

---

## 2. Goals

- Allow users to identify and tag music files in bulk with correct metadata
- Provide a clean, real-time UI showing per-track progress, success, and errors
- Run self-hosted with no external dependencies beyond ShazamIO
- Be accessible from any device (phone, tablet, desktop) via browser
- Handle failures gracefully — a bad track should not stop the batch

## 2.1 Non-Goals (MVP)

- No user accounts or authentication (MVP is single-user / trusted network)
- No permanent file storage or library management
- No support for streaming services or playlist import
- No music player or playback
- No automatic file renaming (metadata only, not file names)
- No support for formats beyond MP3 in MVP
- No VPS hosting in MVP (local/home server first)

---

## 3. User Stories

- As a user, I want to select multiple MP3 files from my device so that I can clean a batch at once
- As a user, I want to see real-time progress per track so that I know what's happening
- As a user, I want to be notified when a track fails identification so that I can handle it manually
- As a user, I want to download the cleaned files after processing so that I can replace my originals
- As a user, I want the app to keep going even if one track fails so that the whole batch isn't blocked
- As a user, I want to access the app from my phone so that I don't need to be at my computer

---

## 4. Technical Requirements

### 4.1 Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite |
| Backend | Node.js, Express |
| Fingerprinting | Python 3.8+, ShazamIO |
| Tag Writing | Python, Mutagen |
| File Handling | Node.js `fs`, `multer` (upload), `child_process` (Python bridge) |
| Containerisation | Docker, Docker Compose |
| Tunnel (optional) | Cloudflare Tunnel |

### 4.2 Architecture

```
Browser (React + TS)
    │
    │  multipart/form-data upload
    ▼
Node/Express API
    │
    │  writes to /tmp/session-{id}/
    │  calls child_process.exec
    ▼
Python Script (shazam_tag.py)
    │
    │  ShazamIO.recognize()
    │  Mutagen tag write
    ▼
Tagged file in /tmp/session-{id}/
    │
    ▼
Node streams file back to browser for download
    │
    ▼
/tmp/session-{id}/ deleted after session
```

### 4.3 Constraints

- Files are processed **sequentially**, not in parallel, to avoid ShazamIO rate limiting
- A configurable delay (default 1s) is added between requests
- Temp directories are cleaned up on session completion or server restart
- Max file size: 50MB per file (configurable via env var)
- MVP supports MP3 only; unsupported formats return a clear error, they do not crash the server
- No auth in MVP — intended for trusted local network or behind Cloudflare Access

### 4.4 Environment Variables

```
MAX_FILE_SIZE_MB=50
REQUEST_DELAY_MS=1000
TEMP_DIR=/tmp/music-cleaner
PORT=3000
```

---

## 5. System Design

### 5.1 API Endpoints

| Method | Route | Description |
|---|---|---|
| POST | `/api/upload` | Accept one or more MP3 files, return session ID |
| GET | `/api/process/:sessionId` | SSE stream — emits per-track status events |
| GET | `/api/download/:sessionId/:filename` | Download a single cleaned file |
| DELETE | `/api/session/:sessionId` | Clean up temp files for a session |

### 5.2 SSE Event Schema

```json
{
  "track": "filename.mp3",
  "status": "processing" | "success" | "error",
  "metadata": {
    "title": "Song Title",
    "artist": "Artist Name",
    "album": "Album Name",
    "art_url": "https://..."
  },
  "error": "Error message if status is error"
}
```

### 5.3 Python Script Interface

```
python shazam_tag.py <filepath>

stdout: JSON { title, artist, album, art_url, success, error }
exit code: 0 on success, 1 on failure
```

---

## 6. Epics & Tickets

---

### Epic 1 — Project Setup & Infrastructure

**Goal:** Establish the project scaffold, tooling, and Docker environment so development can begin.

---

#### Ticket 1.1 — Initialise monorepo structure

**Type:** `chore`  
**Estimate:** S

**Description:**  
Set up the project directory structure with separate `client/` and `server/` directories, root-level `docker-compose.yml`, `.gitignore`, and `README.md`.

**Subtasks:**
- [ ] Create root directory with `client/` and `server/` folders
- [ ] Initialise `client/` with Vite + React + TypeScript template
- [ ] Initialise `server/` with `npm init`, install Express, TypeScript, ts-node
- [ ] Add root `.gitignore` (node_modules, dist, .env, __pycache__, /tmp)
- [ ] Add placeholder `README.md`
- [ ] Create GitHub repo and push initial commit

**Acceptance Criteria:**
- `client/` runs with `npm run dev` and shows default Vite page
- `server/` runs with `ts-node index.ts` without errors
- Both are committed to GitHub

**Test Cases:**
- Run `npm run dev` in `client/` — expect Vite dev server starts on port 5173
- Run `ts-node index.ts` in `server/` — expect "Server running on port 3000" log
- Confirm `.env` is not committed to GitHub

---

#### Ticket 1.2 — Docker Compose setup

**Type:** `chore`  
**Estimate:** S

**Description:**  
Create Dockerfiles for both client and server, and a root `docker-compose.yml` that runs the full stack.

**Subtasks:**
- [ ] Write `server/Dockerfile` (Node + Python in same image)
- [ ] Write `client/Dockerfile` (Vite build served via nginx or dev mode)
- [ ] Write root `docker-compose.yml` with both services
- [ ] Add `TEMP_DIR`, `PORT`, `MAX_FILE_SIZE_MB`, `REQUEST_DELAY_MS` as env vars
- [ ] Confirm hot reload works in dev mode

**Acceptance Criteria:**
- `docker-compose up --build` starts both services
- Frontend is accessible at `http://localhost:5173`
- Backend is accessible at `http://localhost:3000`

**Test Cases:**
- Run `docker-compose up --build` from root — expect both containers start without errors
- Hit `http://localhost:3000/health` — expect `{ status: "ok" }`
- Kill and restart containers — expect temp directory is clean on restart

---

#### Ticket 1.3 — Python environment & ShazamIO validation

**Type:** `chore`  
**Estimate:** S

**Description:**  
Set up the Python environment inside the server Docker image and validate that ShazamIO can successfully identify a test MP3 file.

**Subtasks:**
- [ ] Add Python 3.8+ and pip to server Dockerfile
- [ ] Install `shazamio` and `mutagen` via pip
- [ ] Write `shazam_tag.py` stub that accepts a file path argument
- [ ] Test recognition against a known MP3 file
- [ ] Confirm JSON output schema matches spec

**Acceptance Criteria:**
- `python shazam_tag.py test.mp3` returns valid JSON with title, artist, album, art_url
- Script exits with code 0 on success, code 1 on failure
- Output is valid JSON parseable by Node

**Test Cases:**
- Run script against a known popular song — expect correct metadata returned
- Run script against a silent/invalid file — expect `{ success: false, error: "..." }` with exit code 1
- Run script against an unsupported format — expect graceful error, no crash

---

### Epic 2 — File Upload & Session Management

**Goal:** Allow users to upload MP3 files and manage processing sessions on the server.

---

#### Ticket 2.1 — File upload endpoint

**Type:** `feature`  
**Estimate:** M

**Description:**  
Implement `POST /api/upload` that accepts multiple MP3 files, validates them, writes them to a temp session directory, and returns a session ID.

**Subtasks:**
- [ ] Install and configure `multer` for multipart file handling
- [ ] Validate file type (MP3 only) and file size (max `MAX_FILE_SIZE_MB`)
- [ ] Generate unique session ID (uuid)
- [ ] Write uploaded files to `TEMP_DIR/session-{id}/input/`
- [ ] Return `{ sessionId, files: [filenames] }` response
- [ ] Return clear error messages for invalid files

**Acceptance Criteria:**
- Valid MP3 files are accepted and written to temp directory
- Non-MP3 files are rejected with a 400 and descriptive error message
- Files exceeding size limit are rejected with a 413
- Session ID is returned in response

**Test Cases:**
- Upload 3 valid MP3s — expect 200, sessionId, filenames in response
- Upload a .flac file — expect 400 `{ error: "Unsupported format. MP3 only in this version." }`
- Upload a file exceeding 50MB — expect 413
- Upload 0 files — expect 400 `{ error: "No files provided" }`
- Upload a file with .mp3 extension but invalid content — expect graceful error during processing, not on upload

---

#### Ticket 2.2 — Session cleanup

**Type:** `chore`  
**Estimate:** S

**Description:**  
Implement `DELETE /api/session/:sessionId` and automatic cleanup of temp files on server restart.

**Subtasks:**
- [ ] Implement DELETE endpoint that removes session directory
- [ ] On server startup, clear all contents of `TEMP_DIR`
- [ ] Add cleanup call after successful download in client flow

**Acceptance Criteria:**
- DELETE endpoint removes temp directory for the given session
- Server restart clears all temp files
- No orphaned files remain after a complete user session

**Test Cases:**
- Upload files, call DELETE — expect session directory is removed
- Restart server — expect TEMP_DIR is empty
- Call DELETE with non-existent sessionId — expect 404

---

### Epic 3 — Audio Fingerprinting & Tag Writing

**Goal:** Process each uploaded file through ShazamIO and write metadata back to the file.

---

#### Ticket 3.1 — ShazamIO Python script

**Type:** `feature`  
**Estimate:** M

**Description:**  
Write the full `shazam_tag.py` script that recognises a track, fetches album art, and writes ID3 tags using Mutagen.

**Subtasks:**
- [ ] Implement `recognize()` call via ShazamIO
- [ ] Parse response for title, artist, album, art URL
- [ ] Download album art image to temp directory
- [ ] Write ID3 tags to file using Mutagen (title, artist, album, cover art)
- [ ] Return JSON result to stdout
- [ ] Handle all failure modes with descriptive error messages

**Acceptance Criteria:**
- Script correctly tags a known MP3 with title, artist, album, and cover art
- Script returns JSON to stdout in all cases (success or failure)
- Original file is modified in place with correct tags
- Album art is embedded in the file, not just linked

**Test Cases:**
- Run against a well-known song — expect all 4 metadata fields populated and written
- Run against an obscure/unrecognised track — expect `{ success: false, error: "Track not recognised" }`
- Simulate network failure — expect `{ success: false, error: "Network error" }`, exit code 1
- Verify tags with a tag reader after script runs — expect correct values

---

#### Ticket 3.2 — Node bridge to Python script

**Type:** `feature`  
**Estimate:** S

**Description:**  
Implement the Node.js function that calls `shazam_tag.py` via `child_process` and parses the result.

**Subtasks:**
- [ ] Write `runShazam(filePath: string): Promise<ShazamResult>` function
- [ ] Spawn Python script with file path argument
- [ ] Parse stdout as JSON
- [ ] Handle non-zero exit codes as errors
- [ ] Add configurable delay between calls (`REQUEST_DELAY_MS`)

**Acceptance Criteria:**
- Function resolves with metadata on success
- Function rejects with error message on failure
- Delay is applied between sequential calls

**Test Cases:**
- Call function with valid MP3 — expect resolved promise with metadata
- Call function with invalid file — expect rejected promise with error string
- Call function twice in sequence — expect minimum `REQUEST_DELAY_MS` between Python invocations

---

#### Ticket 3.3 — Sequential batch processing with SSE

**Type:** `feature`  
**Estimate:** M

**Description:**  
Implement `GET /api/process/:sessionId` as a Server-Sent Events stream that processes files one by one and emits status events to the client.

**Subtasks:**
- [ ] Set SSE headers on the response
- [ ] Read file list from session directory
- [ ] Process files sequentially, emitting an event per file
- [ ] Emit `processing`, `success`, or `error` events per track
- [ ] Continue processing remaining files on individual track failure
- [ ] Emit a final `done` event when batch is complete
- [ ] Close the SSE connection cleanly

**Acceptance Criteria:**
- Client receives a real-time event for each track as it is processed
- A failed track emits an error event but does not stop the batch
- `done` event is emitted after all tracks are processed
- SSE connection closes cleanly after `done`

**Test Cases:**
- Process 3 valid files — expect 3 success events then done
- Process a batch where 1 file fails — expect 2 success + 1 error + done
- Process an empty session — expect immediate done event
- Disconnect client mid-batch — expect server cleans up gracefully (no hanging processes)

---

### Epic 4 — Frontend UI

**Goal:** Build a clean React + TypeScript UI for file selection, real-time progress tracking, and file download.

---

#### Ticket 4.1 — File selection & upload UI

**Type:** `feature`  
**Estimate:** M

**Description:**  
Build the file picker component that allows users to select multiple MP3 files and upload them to the server.

**Subtasks:**
- [ ] Build drag-and-drop file picker component
- [ ] Show selected file list with names and sizes before upload
- [ ] Validate file types client-side before upload (MP3 only)
- [ ] Show upload progress indicator
- [ ] Call `POST /api/upload` on submit
- [ ] Handle and display upload errors

**Acceptance Criteria:**
- User can select multiple MP3 files via drag-and-drop or file picker dialog
- Non-MP3 files are highlighted as invalid before upload
- Upload progress is visible
- On success, app transitions to processing view with session ID

**Test Cases:**
- Drag 3 MP3s onto the drop zone — expect files appear in the list
- Drag a .flac file — expect it is marked invalid and not included in upload
- Click upload with valid files — expect progress bar appears and advances
- Simulate upload failure — expect error message is shown and user can retry

---

#### Ticket 4.2 — Real-time processing progress UI

**Type:** `feature`  
**Estimate:** M

**Description:**  
Build the processing view that connects to the SSE stream and shows per-track status in real time.

**Subtasks:**
- [ ] Connect to `GET /api/process/:sessionId` via EventSource
- [ ] Render a list item per track with status indicator (pending, processing, success, error)
- [ ] Show track metadata (title, artist, album art thumbnail) on success
- [ ] Show error message on failure
- [ ] Show overall progress bar (X of N complete)
- [ ] Show "All done" state when `done` event is received

**Acceptance Criteria:**
- Each track shows its current status in real time
- Successful tracks display recognised metadata and art thumbnail
- Failed tracks show a clear error message
- Progress bar reflects overall batch completion
- UI is usable on mobile (responsive)

**Test Cases:**
- Process a batch of 5 — expect list updates in real time, one by one
- One track fails — expect it shows error state while others continue
- Batch completes — expect "All done" state and download prompt appears
- View on 375px mobile screen — expect layout is usable, no overflow

---

#### Ticket 4.3 — Download UI

**Type:** `feature`  
**Estimate:** S

**Description:**  
Allow users to download successfully tagged files individually or as a zip.

**Subtasks:**
- [ ] Add download button per successfully tagged track
- [ ] Implement `GET /api/download/:sessionId/:filename` on the server
- [ ] (Stretch) Add "Download all as ZIP" button using `archiver` on the server
- [ ] Call `DELETE /api/session/:sessionId` after all downloads complete or user dismisses

**Acceptance Criteria:**
- Each successful track has a working download link
- Downloaded file contains correct embedded metadata and art
- Session is cleaned up after user is done

**Test Cases:**
- Click download on a tagged file — expect file downloads with correct tags
- Verify downloaded file tags with a tag reader — expect correct title, artist, album, art
- After download, confirm session directory is deleted on server

---

#### Ticket 4.4 — Error notification system

**Type:** `feature`  
**Estimate:** S

**Description:**  
Implement a toast/notification system for surface-level errors (upload failures, network errors, unsupported formats).

**Subtasks:**
- [ ] Build reusable toast component (error, warning, info variants)
- [ ] Trigger toasts on upload errors, SSE connection failures, unsupported file types
- [ ] Auto-dismiss after 5 seconds, dismissable manually

**Acceptance Criteria:**
- Upload errors surface as toast notifications
- SSE connection failure shows a persistent error with retry option
- Toasts are visible on mobile

**Test Cases:**
- Trigger an upload error — expect toast appears with descriptive message
- Dismiss toast manually — expect it disappears immediately
- Wait 5 seconds — expect toast auto-dismisses

---

### Epic 5 — Deployment & DevOps

**Goal:** Package and deploy the app so it runs reliably on a home server and is accessible externally.

---

#### Ticket 5.1 — Production Docker Compose

**Type:** `chore`  
**Estimate:** S

**Description:**  
Finalise the production Docker Compose setup with correct volumes, restart policies, and environment variable handling.

**Subtasks:**
- [ ] Add `restart: unless-stopped` to both services
- [ ] Mount TEMP_DIR as a Docker volume
- [ ] Add `.env.example` with all required variables
- [ ] Test full production build end to end

**Acceptance Criteria:**
- `docker-compose up -d` starts both services in the background
- Services restart automatically after a crash
- `.env.example` documents all required variables

---

#### Ticket 5.2 — Cloudflare Tunnel setup

**Type:** `chore`  
**Estimate:** S

**Description:**  
Configure Cloudflare Tunnel to expose the app publicly from the home server.

**Subtasks:**
- [ ] Install `cloudflared` on the MacBook home server
- [ ] Create a tunnel and point it at `localhost:3000`
- [ ] Add tunnel run to Docker Compose or as a systemd service
- [ ] Test access from an external device

**Acceptance Criteria:**
- App is accessible from a phone not on the local network via the tunnel URL
- Tunnel restarts automatically if it drops

---

## 7. Out of Scope / Backlog

- Auth (Cloudflare Access can be added in front of the tunnel for basic protection)
- Support for FLAC, M4A, OGG, WAV formats
- File renaming based on tags
- VPS hosting
- "Download all as ZIP" (noted as stretch in Ticket 4.3)
- Rate limit handling with automatic retry backoff (v2)
- Library management / persistent database
