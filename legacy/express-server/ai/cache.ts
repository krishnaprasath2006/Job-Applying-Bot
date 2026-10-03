import crypto from 'crypto';
import type { ModelCacheFingerprint } from '../types/index.js';

export class ModelEmbeddingCache {
  private cache: Map<string, { vector: number[]; timestamp: string }> = new Map();

  computeFingerprint(
    provider: string,
    modelId: string,
    modelRevision: string,
    dimension: number,
    text: string
  ): ModelCacheFingerprint {
    const inputHash = crypto.createHash('sha256').update(text.trim()).digest('hex');
    return {
      provider,
      modelId,
      modelRevision,
      dimension,
      inputHash,
      createdAt: new Date().toISOString()
    };
  }

  getCacheKey(fingerprint: ModelCacheFingerprint): string {
    return `${fingerprint.provider}::${fingerprint.modelId}::${fingerprint.modelRevision}::${fingerprint.dimension}::${fingerprint.inputHash}`;
  }

  get(fingerprint: ModelCacheFingerprint): number[] | null {
    const key = this.getCacheKey(fingerprint);
    const entry = this.cache.get(key);
    return entry ? entry.vector : null;
  }

  set(fingerprint: ModelCacheFingerprint, vector: number[]): void {
    const key = this.getCacheKey(fingerprint);
    this.cache.set(key, { vector, timestamp: new Date().toISOString() });
  }

  size(): number {
    return this.cache.size;
  }

  clear(): void {
    this.cache.clear();
  }
}

export const globalEmbeddingCache = new ModelEmbeddingCache();
