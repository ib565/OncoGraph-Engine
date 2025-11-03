"""Model adapters for different LLM backends (Gemini, Qwen, etc.)."""

import re
import time
from typing import Protocol, runtime_checkable

import tiktoken


@runtime_checkable
class ModelAdapter(Protocol):
    """Protocol for model adapters that generate Cypher queries."""

    def generate_cypher(self, question: str) -> str:
        """Generate a Cypher query from a natural language question.

        Args:
            question: The natural language question to convert to Cypher.

        Returns:
            The generated Cypher query string.
        """
        ...

    def count_tokens(self, text: str) -> int:
        """Count the number of tokens in the given text.

        Args:
            text: The text to count tokens for.

        Returns:
            The number of tokens.
        """
        ...

    def get_model_id(self) -> str:
        """Get a unique identifier for this model.

        Returns:
            A string identifier (e.g., "gemini-2.0-flash", "qwen3-4b-base").
        """
        ...

    def get_full_prompt(self, question: str) -> str:
        """Get the full prompt text that would be sent to the model.

        This is used for token counting and debugging.

        Args:
            question: The natural language question.

        Returns:
            The full prompt text.
        """
        ...


class GeminiModelAdapter:
    """Adapter for Gemini models using the 2-step pipeline (instruction expansion + Cypher generation)."""

    def __init__(
        self,
        model: str,
        api_key: str,
        temperature: float = 0.1,
        rate_limit_rpm: int = 15,
    ):
        """Initialize the Gemini model adapter.

        Args:
            model: Gemini model name (e.g., "gemini-2.0-flash", "gemini-2.5-flash-lite").
            api_key: Google API key for Gemini.
            temperature: Sampling temperature.
            rate_limit_rpm: Rate limit in requests per minute.
        """
        from src.pipeline.gemini import (
            GeminiConfig,
            GeminiCypherGenerator,
            GeminiInstructionExpander,
        )

        self.model = model
        self.config = GeminiConfig(model=model, temperature=temperature, api_key=api_key)
        self.expander = GeminiInstructionExpander(config=self.config)
        self.generator = GeminiCypherGenerator(config=self.config)
        self.rate_limit_rpm = rate_limit_rpm
        self.rate_limit_timestamps: list[float] = []
        self.token_encoder = tiktoken.get_encoding("o200k_base")  # Compatible with Gemini

    def get_model_id(self) -> str:
        """Return the model identifier."""
        return self.model

    def _extract_retry_delay(self, error_str: str) -> float | None:
        """Extract retry delay from Gemini API error message."""
        # Look for "Please retry in X.XXXs" pattern
        match = re.search(r"Please retry in ([\d.]+)s", error_str, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        # Look for RetryInfo retryDelay in details
        match = re.search(r"'retryDelay':\s*['\"]?(\d+)s", error_str, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None

    def _call_with_retry(self, func, max_attempts: int = 7, base_delay: float = 2.0):
        """Call function with exponential backoff, respecting API RetryInfo if available."""
        import random

        random.seed(42)  # For jitter consistency
        last_exception = None

        for attempt in range(max_attempts):
            try:
                return func()
            except Exception as e:
                last_exception = e
                error_str = str(e)

                # Check for rate limit (429)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    # Extract retry delay from API response
                    retry_delay = self._extract_retry_delay(error_str)
                    if retry_delay:
                        delay = retry_delay + 1.0  # Add buffer
                        print(f"\nRate limit hit. API recommends retry in {retry_delay:.1f}s. Waiting {delay:.1f}s...")
                    else:
                        # Fallback to exponential backoff with jitter
                        delay = base_delay * (2**attempt) + random.uniform(0, 1)
                        print(f"\nRate limit hit (attempt {attempt + 1}/{max_attempts}). Waiting {delay:.1f}s...")

                    if attempt < max_attempts - 1:
                        time.sleep(delay)
                        continue

                # For other errors, use exponential backoff
                if attempt < max_attempts - 1:
                    delay = base_delay * (2**attempt)
                    error_msg = (
                        f"\nError (attempt {attempt + 1}/{max_attempts}): "
                        f"{type(e).__name__}. Retrying in {delay:.1f}s..."
                    )
                    print(error_msg)
                    time.sleep(delay)
                    continue

                # Last attempt failed
                raise last_exception from None

        raise last_exception from None

    def _enforce_rate_limit(self):
        """Enforce rate limiting for Gemini API calls."""
        current_time = time.time()
        # Keep only timestamps from last minute
        self.rate_limit_timestamps = [ts for ts in self.rate_limit_timestamps if current_time - ts < 60]

        if len(self.rate_limit_timestamps) >= self.rate_limit_rpm:
            sleep_time = 60 - (current_time - self.rate_limit_timestamps[0]) + 1
            if sleep_time > 0:
                print(f"\nRate limit approaching, sleeping {sleep_time:.1f}s...")
                time.sleep(sleep_time)
                current_time = time.time()
                self.rate_limit_timestamps = []

        self.rate_limit_timestamps.append(current_time)

    def generate_cypher(self, question: str) -> str:
        """Generate Cypher using the 2-step Gemini pipeline."""
        self._enforce_rate_limit()

        def _generate_instructions():
            return self.expander.expand_instructions(question)

        def _generate_cypher(inst):
            return self.generator.generate_cypher(inst)

        instructions = self._call_with_retry(_generate_instructions, max_attempts=5, base_delay=2.0)
        generated_cypher = self._call_with_retry(lambda: _generate_cypher(instructions), max_attempts=5, base_delay=2.0)

        return generated_cypher

    def get_full_prompt(self, question: str) -> str:
        """Get the full prompt text for token counting."""
        from src.pipeline.prompts import CYPHER_PROMPT_TEMPLATE, INSTRUCTION_PROMPT_TEMPLATE, SCHEMA_SNIPPET

        # Reconstruct the prompts (instructions are generated, so we can't get exact, but this is close)
        instruction_prompt = INSTRUCTION_PROMPT_TEMPLATE.format(schema=SCHEMA_SNIPPET, question=question.strip())
        # For Cypher prompt, we'd need the instructions, but for token counting purposes,
        # we'll use the question as a placeholder estimate
        cypher_prompt_estimate = CYPHER_PROMPT_TEMPLATE.format(
            schema=SCHEMA_SNIPPET, instructions="[generated instructions]"
        )
        return instruction_prompt + "\n\n" + cypher_prompt_estimate

    def count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken encoder."""
        return len(self.token_encoder.encode(text))


class QwenModelAdapter:
    """Adapter for Qwen models using Unsloth."""

    def __init__(
        self,
        model_name: str = "unsloth/Qwen3-4B-Instruct-2507",
        model_id: str = "qwen3-4b-it-2507-base",
        max_seq_length: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        top_k: int = 20,
        max_new_tokens: int = 1024,
    ):
        """Initialize the Qwen model adapter.

        Args:
            model_name: HuggingFace model name or path.
            model_id: Unique identifier for this model (used in checkpoints).
            max_seq_length: Maximum sequence length.
            temperature: Sampling temperature.
            top_p: Top-p sampling.
            top_k: Top-k sampling.
            max_new_tokens: Maximum new tokens to generate.
        """
        from unsloth import FastLanguageModel

        self.model_name = model_name
        self.model_id = model_id
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.max_new_tokens = max_new_tokens

        print(f"Loading Qwen model: {model_name}...")
        self.model, self.tokenizer = FastLanguageModel.from_pretrained(
            model_name=model_name,
            max_seq_length=max_seq_length,
            load_in_4bit=True,
        )
        FastLanguageModel.for_inference(self.model)  # Enable inference optimizations
        # Cache device once to avoid querying per-call
        self.device = next(self.model.parameters()).device
        # Ensure the tokenizer uses the correct Qwen3 instruct chat template
        try:
            from unsloth.chat_templates import get_chat_template

            self.tokenizer = get_chat_template(self.tokenizer, chat_template="qwen3-instruct")
        except Exception:
            # Fall back silently if chat template helper isn't available
            pass
        print("Qwen model loaded successfully")

        # Qwen prompt template
        self.minimal_schema = """Graph schema:
            - Nodes: Gene(symbol), Variant(name), Therapy(name), Disease(name), Biomarker
            - Relationships: (Variant)-[:VARIANT_OF]->(Gene), (Therapy)-[:TARGETS]->(Gene),
            (Biomarker)-[:AFFECTS_RESPONSE_TO]->(Therapy)
            - Properties: effect, disease_name, pmids, moa, ref_sources, ref_ids, ref_urls
            - Return: Always include LIMIT, no parameters ($variables), use coalesce for arrays
            """

        self.system_prompt = f"""You are an expert Cypher query translator for oncology data.

            {self.minimal_schema}

            Rules:
            - Return only Cypher query (no markdown, no explanation)
            - Include RETURN clause and LIMIT
            - Use toLower() for case-insensitive matching
            - Wrap arrays with coalesce(..., []) before any()/all()
            - For disease filters, use token-based CONTAINS matching
        """

    def get_model_id(self) -> str:
        """Return the model identifier."""
        return self.model_id

    def _format_prompt(self, question: str) -> str:
        """Format question using Qwen chat template."""
        # Try to use tokenizer's apply_chat_template if available (recommended)
        if hasattr(self.tokenizer, "apply_chat_template"):
            messages = [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": question}]
            return self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        else:
            # Fallback to manual formatting
            return f"""<|im_start|>system
{self.system_prompt}
<|im_end|>
<|im_start|>user
{question}
<|im_end|>
<|im_start|>assistant
"""

    def get_full_prompt(self, question: str) -> str:
        """Get the full prompt text that would be sent to the model."""
        return self._format_prompt(question)

    def generate_cypher(self, question: str) -> str:
        """Generate Cypher query using Qwen model."""
        prompt_text = self._format_prompt(question)

        # Tokenize once and move to model's device (matches Unsloth docs)
        tokenized_inputs = self.tokenizer(prompt_text, return_tensors="pt").to(self.device)

        # Generate using the pre-tokenized inputs
        outputs = self.model.generate(
            **tokenized_inputs,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
        )

        # Decode only the newly generated tokens (skip input tokens)
        input_length = tokenized_inputs["input_ids"].shape[1]
        generated_tokens = outputs[0][input_length:]
        # Store precise generated token count for downstream metrics
        try:
            self._last_gen_output_tokens = int(len(generated_tokens))  # type: ignore[attr-defined]
        except Exception:
            self._last_gen_output_tokens = None  # type: ignore[attr-defined]
        generated_text = self.tokenizer.decode(generated_tokens, skip_special_tokens=True)

        # Clean up markdown code fences if present
        if "```" in generated_text:
            lines = generated_text.split("\n")
            # Remove code fence lines
            cleaned = [line for line in lines if not line.strip().startswith("```")]
            generated_text = "\n".join(cleaned).strip()

        return generated_text.strip()

    def count_tokens(self, text: str) -> int:
        """Count tokens using Qwen's tokenizer."""
        try:
            return len(self.tokenizer.encode(text, add_special_tokens=False))
        except TypeError:
            # Fallback if add_special_tokens not supported
            return len(self.tokenizer.encode(text))
