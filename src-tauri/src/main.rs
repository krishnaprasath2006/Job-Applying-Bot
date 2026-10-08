//! AI Job Assistant — desktop shell entry point.
//!
//! Phase 1 of the desktop migration is deliberately empty of behaviour: this
//! binary opens the window that loads the React bundle and nothing else.
//!
//! Where the behaviour actually lives:
//!
//! * presentation and interaction — the React application under `src/`;
//! * every business rule, safety guard, database statement and AI call — the
//!   canonical Python core under `src/`, reached over the local FastAPI
//!   boundary.
//!
//! Nothing in this crate may become a second backend: no domain logic, no
//! direct database access, no browser automation, and no import of the
//! quarantined legacy bot.
//!
//! Development today: start the backend yourself on 127.0.0.1:8000
//! (`uvicorn api.app:app --host 127.0.0.1 --port 8000` from the repository root
//! with `src` on `PYTHONPATH`), then run `npm run tauri dev`. The window loads
//! the Vite dev server, which proxies `/api` to that backend. Managing the
//! backend's lifecycle is a later phase, not this one.

// Release builds are GUI applications: without this attribute Windows would
// also open a console window behind the app.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running the AI Job Assistant desktop shell");
}
