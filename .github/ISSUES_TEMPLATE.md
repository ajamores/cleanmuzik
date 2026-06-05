# Epic 2 — File Upload & Session Management

**Goal:** Allow users to upload MP3 files and manage processing sessions on the server.

## Ticket 2.1 — File upload endpoint

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

## Ticket 2.2 — Session cleanup

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

# Epic 4 — Frontend UI

**Goal:** Build a clean React + TypeScript UI for file selection, real-time progress tracking, and file download.

## Ticket 4.1 — File selection & upload UI

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

## Ticket 4.2 — Real-time processing progress UI

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

## Ticket 4.3 — Download UI

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

## Ticket 4.4 — Error notification system

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
