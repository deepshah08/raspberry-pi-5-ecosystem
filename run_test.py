import pytest

if __name__ == "__main__":
    pytest.main(["projects/44-llm-gateway/tests/test_gateway.py::test_chat_completions_non_streaming", "-vv", "--showlocals"])
