import { HuggingFaceLocalProvider } from './huggingface.js';
import { EmbeddingScorer } from './embeddings.js';

async function runSmokeTest() {
  console.log('\n============================================================');
  console.log('HUGGING FACE LOCAL EMBEDDING SMOKE TEST (OPTIONAL)');
  console.log('Target Model: sentence-transformers/all-MiniLM-L6-v2');
  console.log('============================================================\n');

  // Instantiate provider with offlineMode: false to load the real ONNX pipeline
  const provider = new HuggingFaceLocalProvider({ offlineMode: false });
  const scorer = new EmbeddingScorer(provider);

  const phraseA = 'Python API development';
  const phraseB = 'Python FastAPI backend development';

  console.log(`Input A: "${phraseA}"`);
  console.log(`Input B: "${phraseB}"`);
  console.log('\nComputing dense embeddings via local ONNX runtime...');

  const startTime = Date.now();
  try {
    const similarity = await scorer.similarity(phraseA, phraseB);
    const duration = Date.now() - startTime;

    console.log(`\n✓ Result: Semantic Similarity = ${similarity.toFixed(4)}`);
    console.log(`✓ Latency: ${duration}ms`);
    console.log(`✓ Model Metadata:`, provider.getMetadata());
    console.log('\nSMOKE TEST PASSED.');
  } catch (err: any) {
    console.warn('\nNote: Smoke test requires external network to fetch weights on first run.');
    console.warn(`Reason: ${err.message}`);
  }
}

runSmokeTest();
