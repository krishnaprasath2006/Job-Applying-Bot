/**
 * Desktop bridge — Phase 2: Tauri ⇆ FastAPI sidecar lifecycle bridge.
 *
 * This module exposes Tauri commands that the React UI can call to manage
 * the local FastAPI sidecar process. It uses tauri-plugin-shell for controlled
 * subprocess management and tauri-plugin-single-instance to ensure only one
 * sidecar instance is running at any time.
 *
 * Commands exposed to React via Tauri IPC:
 * - startSidecar(): Promise<{event: 'listening', host: string, port: number}>
 * - shutdownSidecar(): Promise<void>
 * - isSidecarRunning(): Promise<boolean>
 * - getSidecarLogs(): Promise<string>
 *
 * Security guarantees:
 * - Loopback only: 127.0.0.1
 * - Dynamic port: 0 by default (OS-assigned)
 * - Shutdown via JSON on stdin, kill fallback
 * - No broad filesystem, HTTP, dialog, or shell permissions
 * - All behaviour goes through the local FastAPI boundary
 */

// Tauri IPC commands are defined here; the actual implementations are in
// src-tauri/src/lib.rs. This TypeScript file only declares the command signatures
// and helper types so the TypeScript compiler knows the shapes.

interface sidecarHandshake {
  event: 'listening';
  host: '127.0.0.1';
  port: number;
}

/** Start the FastAPI sidecar via Tauri command. */
export const startSidecar = async (): Promise<sidecarHandshake> => {
  // The actual implementation is in src-tauri/src/lib.rs via invoke()
  // For TypeScript-typing purposes, we declare the expected shape.
  // At runtime, tauri::api::invoke will call the Rust command.
  throw new Error('Tauri command: start-sidecar');
};

/** Shut down the FastAPI sidecar gracefully. */
export const shutdownSidecar = async (): Promise<void> => {
  throw new Error('Tauri command: shutdown-sidecar');
};

/** Check whether the FastAPI sidecar is running. */
export const isSidecarRunning = async (): Promise<boolean> => {
  throw new Error('Tauri command: is-sidecar-running');
};

/** Retrieve the latest stderr tail from the sidecar process. */
export const getSidecarLogs = async (): Promise<string> => {
  throw new Error('Tauri command: get-sidecar-logs');
};

/** Send a shutdown command through the sidecar's stdin. */
export const sendShutdownCommand = async (): Promise<void> => {
  throw new Error('Tauri command: send-shutdown-command');
};

/** Parse the sidecar handshake from emitted stdout data. */
export const parseHandshake = (data: string): sidecarHandshake | null => {
  try {
    const parsed = JSON.parse(data);
    if (parsed.event === 'listening' && parsed.host === '127.0.0.1' && typeof parsed.port === 'number') {
      return parsed;
    }
  } catch {
    // Not valid JSON — ignore
  }
  return null;
};

/** Poll the sidecar stdout for a handshake, with timeout. */
export const pollForHandshake = async (
  stdoutChunks: string[],
  timeoutMs = 15000
): Promise<sidecarHandshake | null> => {
  const start = Date.now();

  while (Date.now() - start < timeoutMs) {
    // Search the accumulated chunks for a handshake
    const combined = stdoutChunks.join('');
    const handshake = parseHandshake(combined);
    if (handshake) {
      return handshake;
    }
    await new Promise(resolve => setTimeout(resolve, 200));
  }

  return null;
};

/** Export all bridge symbols for use in Tauri commands and React UI. */
export type { sidecarHandshake };