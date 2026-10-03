import type { ModelCapability, ModelMetadata } from '../types/index.js';

// -------------------------------------------------------------
// Typed Model Error Hierarchy
// -------------------------------------------------------------
export class AIModelError extends Error {
  constructor(message: string, public readonly code: string) {
    super(message);
    this.name = 'AIModelError';
  }
}

export class ModelUnavailableError extends AIModelError {
  constructor(provider: string, reason: string) {
    super(`Model provider '${provider}' is unavailable: ${reason}`, 'MODEL_UNAVAILABLE');
    this.name = 'ModelUnavailableError';
  }
}

export class ModelLoadError extends AIModelError {
  constructor(modelId: string, cause: unknown) {
    super(`Failed to load model '${modelId}': ${cause instanceof Error ? cause.message : String(cause)}`, 'MODEL_LOAD_FAILED');
    this.name = 'ModelLoadError';
  }
}

export class EmbeddingGenerationError extends AIModelError {
  constructor(modelId: string, message: string) {
    super(`Embedding generation failed for model '${modelId}': ${message}`, 'EMBEDDING_GENERATION_FAILED');
    this.name = 'EmbeddingGenerationError';
  }
}

export class DimensionMismatchError extends AIModelError {
  constructor(expected: number, received: number) {
    super(`Embedding vector dimension mismatch: expected ${expected}, got ${received}`, 'DIMENSION_MISMATCH');
    this.name = 'DimensionMismatchError';
  }
}

// -------------------------------------------------------------
// Core AIProvider Protocol Interface
// -------------------------------------------------------------
export interface AIProvider {
  readonly id: string;
  readonly name: string;

  supports(capability: ModelCapability): boolean;
  getEmbeddings(texts: string[]): Promise<number[][]>;
  getMetadata(): ModelMetadata;
  unload?(): Promise<void>;
}
