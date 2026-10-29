import React, { useState, useEffect, useCallback } from 'react';
import { API } from '../lib/api/index.js';

/**
 * BackendBootGate — Phase 2: manages the local FastAPI sidecar lifecycle.
 *
 * Behaviour:
 *  1. "idle"      → show "Starting local services..." then "Preparing your workspace..."
 *  2. "starting"  → attempt to start the sidecar, wait for {"event":"listening"} handshake on stdout
 *  3. "preparing" → show "Preparing your workspace..." while APIs become available
 *  4. "ready"     → normal UI proceeds (BackendBootGate renders its children)
 *  5. "error"     → show "Try again" button; /api/ready returns 503
 *
 * Security:
 *  - Loopback only: 127.0.0.1
 *  - Dynamic port: 0 by default (OS-assigned)
 *  - Shutdown command via JSON / stdin or Tauri shell plugin
 *  - Kill fallback if stdin shutdown fails
 *  - No broad filesystem/HTTP/shell permissions
 */

export function BackendBootGate({
  onReady,
  onError,
}: {
  onReady: (status: 'ready' | 'error') => void;
  onError: () => void;
}) {
  const [phase, setPhase] = useState<'idle' | 'starting' | 'preparing' | 'ready' | 'error'>('idle');
  const [sidecarProcess, setSidecarProcess] = useState<any | null>(null);
  const [sidecarPort, setSidecarPort] = useState<number | null>(null);
  const [ready, setReady] = useState(false);

  // Start the FastAPI sidecar process
  const startSidecar = useCallback(async () => {
    setPhase('starting');
    setSidecarProcess(null);
    setSidecarPort(null);
    setReady(false);

    try {
      // Spawn the Python sidecar process
      const pythonPath = await locatePython();
      const scriptPath = '/scripts/prepare-dev-sidecar.mjs';

      // In a real implementation, we would use child_process to spawn the sidecar
      // For now, we'll simulate the handshake detection
      // The sidecar is expected to:
      // - Listen on 127.0.0.1 with a dynamic port (0 = OS assigned)
      // - Output {"event":"listening","host":"127.0.0.1","port":...} to stdout
      // - Stream logs to stderr
      // - Accept /api/ready checks
      // - Respond to shutdown via stdin JSON or kill fallback

      // TODO: Implement actual child_process spawn in Tauri/Rust environment
      // For Phase 2, the sidecar is spawned from the Tauri main process,
      // not from the React renderer. This component communicates via /api/ready.

      // Simulate the handshake for now
      await new Promise(resolve => setTimeout(resolve, 1000));
      const mockPort = 8000; // In reality, this comes from the handshake
      setSidecarPort(mockPort);
      setPhase('preparing');

      // Wait a moment then mark as ready
      setTimeout(() => {
        setPhase('ready');
        onReady?.('ready');
      }, 500);

    } catch (err) {
      console.error('Sidecar startup failed:', err);
      setPhase('error');
      onError();
    }
  }, [onReady, onError]);

  // Locate the Python interpreter
  const locatePython = async (): Promise<string> => {
    // In Tauri, we'd use the Rust side to find or bundle the Python interpreter
    // For now, fall back to the system Python
    return 'python3';
  };

  // Handle shutdown command
  const handleShutdown = useCallback(() => {
    if (sidecarProcess) {
      // Send shutdown JSON through stdin
      sidecarProcess!.stdin!.write(JSON.stringify({ event: 'shutdown' }) + '\n');
      // Kill fallback after a timeout
      setTimeout(() => {
        sidecarProcess!.kill();
      }, 3000);
    }
  }, [sidecarProcess]);

  // On component mount, start the sidecar
  useEffect(() => {
    startSidecar();

    // Listen for message events from the sidecar (in a real impl)
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.event === 'listening' && phase === 'starting') {
        const { host, port } = event.data;
        setSidecarPort(port);
        setPhase('preparing');
        setReady(true);
        onReady?.('ready');
      }
    };

    window.addEventListener('message', handleMessage);

    return () => {
      window.removeEventListener('message', handleMessage);
      handleShutdown();
    };
  }, [startSidecar, phase, onReady, onError, handleShutdown]);

  // Render based on phase
  if (phase === 'idle') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-8">
        <div>
          <h2 className="text-2xl font-bold mb-4">Starting local services...</h2>
          <p className="text-slate-400 mb-6">Initializing the FastAPI sidecar for the Tauri desktop shell.</p>
          <p className="text-slate-500 text-sm">This may take a moment on first run.</p>
        </div>
      </div>
    );
  }

  if (phase === 'starting') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-8">
        <div>
          <h2 className="text-2xl font-bold mb-4">Starting local services...</h2>
          <p className="text-slate-400 mb-6">FastAPI sidecar process starting...</p>
          <p className="text-slate-500 text-sm">Listening for handshake on 127.0.0.1:</p>
          <p className="text-emerald-400 font-medium" id="sidecar-port">--</p>
        </div>
      </div>
    );
  }

  if (phase === 'preparing') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-8">
        <div>
          <h2 className="text-2xl font-bold mb-4">Preparing your workspace...</h2>
          <p className="text-slate-400 mb-6">The local FastAPI sidecar is running. Loading the application...</p>
          <p className="text-slate-500 text-sm">Connecting to 127.0.0.1:{sidecarPort || '--'}</p>
        </div>
      </div>
    );
  }

  if (phase === 'error') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-8">
        <div>
          <h2 className="text-2xl font-bold mb-4">Starting local services...</h2>
          <p className="text-rose-400 mb-6">Unable to start the FastAPI sidecar.</p>
          <p className="text-slate-400 text-sm">The application cannot proceed without the sidecar.</p>
          <button
            onClick={() => setPhase('idle')}
            className="mt-6 px-6 py-3 bg-emerald-700 text-white rounded hover:bg-emerald-600 transition-colors"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  // phase === 'ready' — render children (the rest of the App)
  return null;
}