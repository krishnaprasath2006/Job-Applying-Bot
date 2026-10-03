import type { AIProvider } from './provider.js';
import type { ModelCapability } from '../types/index.js';
import { HuggingFaceLocalProvider } from './huggingface.js';

export class ModelRegistry {
  private providers: Map<string, AIProvider> = new Map();
  private defaultEmbeddingProviderId: string = 'huggingface_local';

  constructor() {
    // Automatically register the default Hugging Face local provider
    const hfProvider = new HuggingFaceLocalProvider();
    this.registerProvider(hfProvider);
  }

  public registerProvider(provider: AIProvider): void {
    this.providers.set(provider.id, provider);
  }

  public getProvider(id: string): AIProvider | undefined {
    return this.providers.get(id);
  }

  public listProviders(): AIProvider[] {
    return Array.from(this.providers.values());
  }

  public setDefaultEmbeddingProvider(providerId: string): void {
    if (!this.providers.has(providerId)) {
      throw new Error(`Cannot set default provider '${providerId}': not registered.`);
    }
    this.defaultEmbeddingProviderId = providerId;
  }

  public getEmbeddingProvider(): AIProvider {
    const provider = this.providers.get(this.defaultEmbeddingProviderId);
    if (!provider || !provider.supports('embeddings')) {
      // Fallback to first available provider with embeddings capability
      for (const p of this.providers.values()) {
        if (p.supports('embeddings')) return p;
      }
      throw new Error('No registered provider supports embeddings capability.');
    }
    return provider;
  }

  public getProviderForCapability(capability: ModelCapability): AIProvider | undefined {
    for (const provider of this.providers.values()) {
      if (provider.supports(capability)) {
        return provider;
      }
    }
    return undefined;
  }
}

export const globalModelRegistry = new ModelRegistry();
