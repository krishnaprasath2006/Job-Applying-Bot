// Tauri's build script: reads tauri.conf.json, validates the configuration and
// capabilities, and generates the code `tauri::generate_context!` expands into.
//
// It runs on every Cargo build, so a malformed configuration fails the build
// rather than the packaged application.
fn main() {
    tauri_build::build()
}
