"""Tests for utility functions and caching."""

from __future__ import annotations

import time
from unittest.mock import patch

from pipeline.utils import TTLCache, get_cache_ttl, get_llm_cache_ttl, stable_hash


class TestTTLCache:
    """Test the TTLCache class."""

    def test_cache_basic_operations(self):
        """Test basic cache set/get operations."""
        cache = TTLCache(default_ttl_seconds=60)

        # Test setting and getting values
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Test non-existent key
        assert cache.get("nonexistent") is None

        # Test overwriting
        cache.set("key1", "value2")
        assert cache.get("key1") == "value2"

    def test_cache_ttl_expiration(self):
        """Test that cached values expire after TTL."""
        cache = TTLCache(default_ttl_seconds=0.1)  # Very short TTL for testing

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(0.2)
        assert cache.get("key1") is None

    def test_cache_custom_ttl(self):
        """Test setting custom TTL for individual keys."""
        cache = TTLCache(default_ttl_seconds=60)

        # Set with custom TTL
        cache.set("key1", "value1", ttl_seconds=0.1)
        cache.set("key2", "value2", ttl_seconds=60)

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

        # Wait for key1 to expire
        time.sleep(0.2)
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_cache_disabled_ttl(self):
        """Test that TTL=0 disables caching."""
        cache = TTLCache(default_ttl_seconds=60)

        cache.set("key1", "value1", ttl_seconds=0)
        assert cache.get("key1") is None

    def test_cache_clear(self):
        """Test clearing the cache."""
        cache = TTLCache(default_ttl_seconds=60)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cache_deep_copy(self):
        """Test that cached values are deep copied to prevent mutation."""
        cache = TTLCache(default_ttl_seconds=60)

        original_list = [1, 2, 3]
        cache.set("key1", original_list)

        # Modify the original
        original_list.append(4)

        # Cached value should be unchanged
        cached_value = cache.get("key1")
        assert cached_value == [1, 2, 3]
        assert cached_value is not original_list

    def test_cache_pydantic_model(self):
        """Test that Pydantic models are properly cached and retrieved."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            value: int

        cache = TTLCache(default_ttl_seconds=60)

        original_model = TestModel(name="test", value=42)
        cache.set("pydantic_key", original_model)

        # Retrieve from cache
        cached_model = cache.get("pydantic_key")

        # Should be a dictionary (serialized form)
        assert isinstance(cached_model, dict)
        assert cached_model == {"name": "test", "value": 42}

        # Should be able to reconstruct the model
        reconstructed = TestModel(**cached_model)
        assert reconstructed.name == "test"
        assert reconstructed.value == 42

    def test_cache_thread_safety(self):
        """Test that cache operations are thread-safe."""
        import threading

        cache = TTLCache(default_ttl_seconds=60)
        results = []

        def worker(thread_id: int):
            for i in range(10):
                key = f"key_{thread_id}_{i}"
                value = f"value_{thread_id}_{i}"
                cache.set(key, value)
                results.append(cache.get(key))

        # Create multiple threads
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All operations should have succeeded
        assert len(results) == 50
        assert all(result is not None for result in results)


class TestStableHash:
    """Test the stable_hash function."""

    def test_stable_hash_consistency(self):
        """Test that stable_hash produces consistent results."""
        data1 = {"a": 1, "b": 2, "c": [3, 4, 5]}
        data2 = {"b": 2, "a": 1, "c": [3, 4, 5]}  # Different order

        hash1 = stable_hash(data1)
        hash2 = stable_hash(data2)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_stable_hash_different_inputs(self):
        """Test that different inputs produce different hashes."""
        hash1 = stable_hash({"a": 1})
        hash2 = stable_hash({"a": 2})
        hash3 = stable_hash({"b": 1})

        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3

    def test_stable_hash_handles_various_types(self):
        """Test that stable_hash handles various data types."""
        data = {
            "string": "test",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, 2, 3],
            "nested": {"a": 1, "b": [2, 3]},
        }

        hash_result = stable_hash(data)
        assert isinstance(hash_result, str)
        assert len(hash_result) == 64


class TestEnvironmentConfiguration:
    """Test environment variable configuration."""

    @patch.dict("os.environ", {"CACHE_TTL_SECONDS": "3600"})
    def test_get_cache_ttl_from_env(self):
        """Test getting cache TTL from environment variable."""
        assert get_cache_ttl() == 3600

    @patch.dict("os.environ", {"LLM_CACHE_TTL_SECONDS": "7200"})
    def test_get_llm_cache_ttl_from_env(self):
        """Test getting LLM cache TTL from environment variable."""
        assert get_llm_cache_ttl() == 7200

    @patch.dict("os.environ", {"CACHE_TTL_SECONDS": "3600", "LLM_CACHE_TTL_SECONDS": "7200"})
    def test_get_llm_cache_ttl_fallback(self):
        """Test that LLM cache TTL falls back to general cache TTL."""
        assert get_llm_cache_ttl() == 7200

    @patch.dict("os.environ", {}, clear=True)
    def test_get_cache_ttl_default(self):
        """Test default cache TTL when no environment variable is set."""
        assert get_cache_ttl() == 1800  # 30 minutes default

    @patch.dict("os.environ", {}, clear=True)
    def test_get_llm_cache_ttl_default(self):
        """Test default LLM cache TTL when no environment variable is set."""
        assert get_llm_cache_ttl() == 1800  # 30 minutes default
