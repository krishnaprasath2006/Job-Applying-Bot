import type { AIProvider } from './provider.js';

// -------------------------------------------------------------
// Vector Math Utilities
// -------------------------------------------------------------
export function cosineSimilarity(vecA: number[], vecB: number[]): number {
  if (vecA.length !== vecB.length || vecA.length === 0) {
    return 0.0;
  }
  let dotProduct = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < vecA.length; i++) {
    dotProduct += vecA[i] * vecB[i];
    normA += vecA[i] * vecA[i];
    normB += vecB[i] * vecB[i];
  }
  if (normA === 0 || normB === 0) return 0.0;
  const score = dotProduct / (Math.sqrt(normA) * Math.sqrt(normB));
  // Bound to [0.0, 1.0] for semantic similarity representation
  return Math.max(0.0, Math.min(1.0, score));
}

// -------------------------------------------------------------
// SemanticScorer Interface
// -------------------------------------------------------------
export interface SemanticScorer {
  name: string;
  similarity(text1: string, text2: string): Promise<number>;
  similarityBatch?(pairs: Array<[string, string]>): Promise<number[]>;
}

// -------------------------------------------------------------
// LexicalScorer (Deterministic Standard Fallback)
// -------------------------------------------------------------
export class LexicalScorer implements SemanticScorer {
  public readonly name = 'LexicalScorer (Token Overlap / Jaccard)';

  public async similarity(text1: string, text2: string): Promise<number> {
    const tokensA = this.tokenize(text1);
    const tokensB = this.tokenize(text2);

    if (tokensA.size === 0 || tokensB.size === 0) {
      return 0.0;
    }

    let intersectionCount = 0;
    for (const token of tokensA) {
      if (tokensB.has(token)) {
        intersectionCount++;
      }
    }

    const unionCount = new Set([...tokensA, ...tokensB]).size;
    return unionCount === 0 ? 0.0 : intersectionCount / unionCount;
  }

  public async similarityBatch(pairs: Array<[string, string]>): Promise<number[]> {
    return Promise.all(pairs.map(([t1, t2]) => this.similarity(t1, t2)));
  }

  private tokenize(text: string): Set<string> {
    const cleaned = text.toLowerCase().replace(/[^a-z0-9\s]/g, ' ');
    const rawTokens = cleaned.split(/\s+/).filter((t) => t.length > 2);
    // Filter common stop words
    const stopWords = new Set(['the', 'and', 'for', 'with', 'that', 'this', 'from', 'have', 'are']);
    return new Set(rawTokens.filter((t) => !stopWords.has(t)));
  }
}

// -------------------------------------------------------------
// EmbeddingScorer (Hugging Face Dense Semantic Similarity)
// -------------------------------------------------------------
export class EmbeddingScorer implements SemanticScorer {
  public readonly name = 'EmbeddingScorer (Hugging Face Dense Semantic)';
  private fallbackScorer: LexicalScorer = new LexicalScorer();

  constructor(private provider: AIProvider) {}

  public async similarity(text1: string, text2: string): Promise<number> {
    try {
      const embeddings = await this.provider.getEmbeddings([text1, text2]);
      if (embeddings.length === 2) {
        return cosineSimilarity(embeddings[0], embeddings[1]);
      }
      throw new Error(`Expected 2 embedding vectors, received ${embeddings.length}`);
    } catch (err: any) {
      console.warn(`[EmbeddingScorer] Provider failed (${err.message}). Safely falling back to LexicalScorer.`);
      return this.fallbackScorer.similarity(text1, text2);
    }
  }

  public async similarityBatch(pairs: Array<[string, string]>): Promise<number[]> {
    if (pairs.length === 0) return [];

    try {
      // Deduplicate texts to minimize model inference operations
      const uniqueTexts = Array.from(new Set(pairs.flatMap(([t1, t2]) => [t1, t2])));
      const textToEmbedding = new Map<string, number[]>();

      const vectors = await this.provider.getEmbeddings(uniqueTexts);
      for (let i = 0; i < uniqueTexts.length; i++) {
        textToEmbedding.set(uniqueTexts[i], vectors[i]);
      }

      return pairs.map(([t1, t2]) => {
        const v1 = textToEmbedding.get(t1);
        const v2 = textToEmbedding.get(t2);
        if (v1 && v2) {
          return cosineSimilarity(v1, v2);
        }
        return 0.0;
      });
    } catch (err: any) {
      console.warn(`[EmbeddingScorer] Batch inference failed (${err.message}). Safely falling back to LexicalScorer.`);
      return this.fallbackScorer.similarityBatch(pairs);
    }
  }
}
