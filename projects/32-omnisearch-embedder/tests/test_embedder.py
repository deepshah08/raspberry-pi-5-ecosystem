import pytest
import asyncio
import numpy as np
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from embedder import OmniSearchEmbedder

@pytest.fixture
def embedder():
    return OmniSearchEmbedder(model_name="MobileCLIP", batch_size=2, max_queue_size=10)

@pytest.fixture
def embedder_siglip():
    return OmniSearchEmbedder(model_name="SigLIP", batch_size=2, max_queue_size=10)

@pytest.mark.asyncio
async def test_vector_dimensionality(embedder, embedder_siglip):
    # Start the processing task
    task = asyncio.create_task(embedder.process_batches())
    task_siglip = asyncio.create_task(embedder_siglip.process_batches())

    # Test MobileCLIP dim
    res = await embedder.embed_image("mock_tensor")
    assert res.shape == (512,)

    # Test SigLIP dim
    res_siglip = await embedder_siglip.embed_image("mock_tensor")
    assert res_siglip.shape == (768,)

    # Clean up
    task.cancel()
    task_siglip.cancel()

@pytest.mark.asyncio
async def test_queue_batching(embedder):
    task = asyncio.create_task(embedder.process_batches())

    # Submit 3 requests simultaneously
    results = await asyncio.gather(
        embedder.embed_image("mock_tensor_1"),
        embedder.embed_text("mock_text_2"),
        embedder.embed_image("mock_tensor_3")
    )

    assert len(results) == 3
    for res in results:
        assert res.shape == (512,)

    task.cancel()

def test_normalization(embedder):
    # Create vectors not normalized
    vectors = np.array([
        [1.0, 1.0, 1.0],
        [3.0, 4.0, 0.0]
    ])

    norm_vectors = embedder.normalize_vectors(vectors)

    # Check norms
    norms = np.linalg.norm(norm_vectors, axis=1)
    np.testing.assert_allclose(norms, [1.0, 1.0], rtol=1e-5)

def test_error_handling():
    with pytest.raises(ValueError):
        OmniSearchEmbedder(model_name="InvalidModel")

@pytest.mark.asyncio
async def test_queue_full():
    embedder = OmniSearchEmbedder(model_name="MobileCLIP", max_queue_size=1)

    # Fill the queue
    future1 = asyncio.ensure_future(embedder.embed_image("mock_tensor_1"))

    # Yield control to let it enter the queue
    await asyncio.sleep(0.01)

    # Second should block or we can just try to see if queue is full
    assert embedder.queue.full() == True

    future1.cancel()
