import asyncio
import numpy as np
from typing import List, Dict, Any, Optional

class OmniSearchEmbedder:
    def __init__(self, model_name: str = "MobileCLIP", batch_size: int = 32, max_queue_size: int = 100):
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_queue_size = max_queue_size
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.semaphore = asyncio.Semaphore(1)  # Throttling
        self._load_model()

    def _load_model(self):
        # Mocking model load
        if self.model_name not in ["MobileCLIP", "CLIP", "SigLIP"]:
            raise ValueError(f"Unsupported model: {self.model_name}")
        self.dim = 512 if self.model_name == "MobileCLIP" else 768
        print(f"Loading {self.model_name}...")

    async def embed_image(self, image_tensor: Any) -> np.ndarray:
        future = asyncio.Future()
        await self.queue.put(("image", image_tensor, future))
        return await future

    async def embed_text(self, text: str) -> np.ndarray:
        future = asyncio.Future()
        await self.queue.put(("text", text, future))
        return await future

    def normalize_vectors(self, vectors: np.ndarray) -> np.ndarray:
        # Normalizes vectors to unit sphere for cosine similarity
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        # Avoid division by zero
        norms = np.where(norms == 0, 1e-10, norms)
        return vectors / norms

    async def process_batches(self):
        while True:
            batch = []
            try:
                # Wait for the first item
                item = await self.queue.get()
                batch.append(item)

                # Try to fill the rest of the batch
                while len(batch) < self.batch_size and not self.queue.empty():
                    batch.append(self.queue.get_nowait())

                async with self.semaphore:
                    # Mock processing step
                    # In reality, this would involve the deep learning model inference
                    # using the batch inputs
                    vectors = np.random.randn(len(batch), self.dim)
                    normalized_vectors = self.normalize_vectors(vectors)

                    for i, (item_type, data, future) in enumerate(batch):
                        if not future.cancelled():
                            future.set_result(normalized_vectors[i])
                        self.queue.task_done()
            except Exception as e:
                # Handle error and fail futures
                for item_type, data, future in batch:
                    if not future.done():
                        future.set_exception(e)
                for _ in range(len(batch)):
                    self.queue.task_done()

async def main():
    embedder = OmniSearchEmbedder()
    # Run indefinitely
    await embedder.process_batches()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down gracefully.")
