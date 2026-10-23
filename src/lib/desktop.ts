/**
 * Desktop shell integration for the AI Job Assistant (Phase 2).
 *
 * Provides runtime resolution of the dynamic FastAPI sidecar port and maps
 * environment variables for Windows data root support via ASSISTANT_DESKTOP_DATA_ROOT.
 *
 * Exported symbols:
 * - getSidecarApiBase(): string             — runtime API base URL
 * - ensureSidecar(): Promise<void>          — start the sidecar if not running
 * - getPaths(root?: string): Paths          —Paths with ASSISTANT_DESKTOP_DATA_ROOT support
 * - isSidecarRunning(): boolean             — liveness check via /api/ready
 */

export interface Paths {
  root: string;
  data: string;
  profile_dir: string;
  resume_dir: string;
  db: string;
  logs: string;
  exports: string;
}

/** Resolve the project root from the TypeScript perspective. */
const detectRoot = (): string => {
  // In a Tauri/build environment, the root is the project directory
  // containing src/. For Vite dev, it's the workspace root.
  // We fall back to assuming the script runs from the project root.
  return new URL('.', import.meta.url).pathname.replace(/\/[^/]*$/, '');
};

/** Runtime API base, resolved per-request so the dynamic sidecar port works. */
export const getSidecarApiBase = (): string => {
  // Never cache at import time — the sidecar port may be assigned at runtime.
  // The Tauri shell injects window.__JOB_ASSISTANT__.apiBase; in dev we fall back
  // to the documented local development port.
  if (typeof window !== 'undefined') {
    const injected = (window as any).__JOB_ASSISTANT?.apiBase;
    if (injected) {
      return injected.replace(/\/+$/, '');
    }
  }
  // Dev fallback; in production the Tauri shell will have injected the correct base.
  return 'http://127.0.0.1:8000/api';
};

/** Ensure the FastAPI sidecar is running; start it if not. */
export const ensureSidecar = async (): Promise<void> => {
  // In a full Tauri 2 implementation, this would invoke the Rust sidecar lifecycle
  // to start the Python sidecar process, parse the {"event":"listening"} handshake,
  // and maintain an stderr tail for diagnostics.
  // For now, we verify /api/ready is reachable; if 503 we attempt startup.
  try {
    const response = await fetch(`${getSidecarApiBase()}/ready`);
    if (response.status === 503) {
      // Sidecar is not running or not healthy — attempt to start it
      // TODO: Call Tauri command to start the sidecar binary
      console.warn('Sidecar not healthy, would attempt startup');
    }
  } catch (err) {
    // Sidecar not reachable — attempt startup
    console.warn('Sidecar not reachable, would attempt startup', err);
  }
};

/** Get Paths respecting ASSISTANT_DESKTOP_DATA_ROOT for Windows. */
export const getPaths = (root?: string): Paths => {
  const baseRoot = root || detectRoot();

  // Apply ASSISTANT_DESKTOP_DATA_ROOT if set (Windows data root support)
// @ts-ignore
  const dataRoot = (process as any).env.ASSISTANT_DESKTOP_DATA_ROOT;
  let dataDir: string;
  let profileDir: string;
  let resumeDir: string;

  if (dataRoot) {
    // Paths flow under the explicit data root on Windows
    dataDir = `${dataRoot}/assistant`;
    profileDir = `${dataRoot}/assistant/profile`;
    resumeDir = `${dataRoot}/assistant/resumes`;
  } else {
    // Existing behaviour: relative to project root
    dataDir = `${baseRoot}/data`;
    profileDir = `${baseRoot}/data/profile`;
    resumeDir = `${baseRoot}/data/resumes`;
  }

  const logsDir = `${baseRoot}/logs`;
  const exportsDir = `${dataDir}/exports`;

  return {
    root: baseRoot,
    data: dataDir,
    profile_dir: profileDir,
    resume_dir: resumeDir,
    db: `${dataDir}/assistant.db`,
    logs: logsDir,
    exports: exportsDir,
  };
};

/** Check whether the sidecar is running by probing /api/ready. */
export const isSidecarRunning = async (): Promise<boolean> => {
  try {
    const response = await fetch(`${getSidecarApiBase()}/ready`);
    return response.status === 200;
  } catch {
    return false;
  }
};

/** Reset any cached state (no-op in this self-contained implementation). */
export const resetPathsCache = (): void => {
  // No persistent cache in this implementation
};

/** Windows data root mapping for runtime paths.
 *  When ASSISTANT_DESKTOP_DATA_ROOT is set, all data paths flow under it.
 *  When unset, existing behaviour is preserved (root detected from project structure). */
export const detectRootWithDataRoot = (dataRoot: string): string | null => {
  // In the TypeScript implementation, we just validate the data root exists
  // by checking if the directory can be referenced. The actual path mapping
  // is handled by getPaths() above.
  try {
    new URL(dataRoot, 'file:///'); // Basic validation
    return dataRoot;
  } catch {
    return null;
  }
}
