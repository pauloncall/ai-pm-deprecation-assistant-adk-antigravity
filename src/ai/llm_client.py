# src/ai/llm_client.py
from abc import ABC, abstractmethod
import os
import requests
import json
try:
    import google.generativeai as genai
except ImportError:
    genai = None

class LLMClient(ABC):
    @abstractmethod
    def generate_response(self, prompt: str, system_instruction: str = None) -> str:
        pass

class OllamaClient(LLMClient):
    def __init__(self, model: str = "gemma3:1b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def generate_response(self, prompt: str, system_instruction: str = None) -> str:
        url = f"{self.base_url}/api/generate"
        
        full_prompt = prompt
        if system_instruction:
            full_prompt = f"System: {system_instruction}\n\nUser: {prompt}"

        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            return f"Error calling Ollama: {e}"

class GeminiClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gemini-pro"):
        if not genai:
            raise ImportError("google-generativeai package is not installed.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)

    def generate_response(self, prompt: str, system_instruction: str = None) -> str:
        # Note: 'system_instruction' support depends on the specific Gemini model version/library support.
        # For simplicity in this 'pro' version, we prepend it if not natively supported by the simple generate_content
        full_prompt = prompt
        if system_instruction:
             # Basic prepending for models that don't support system_instruction arg directly in generate_content yet
            full_prompt = f"{system_instruction}\n\n{prompt}"
            
        try:
            response = self.model.generate_content(full_prompt)
            return response.text
        except Exception as e:
            return f"Error calling Gemini: {e}"

class MockLLMClient(LLMClient):
    def generate_response(self, prompt: str, system_instruction: str = None) -> str:
        # Simple mock for testing without live LLMs
        if "INTENT:" in prompt or "Classify" in prompt:
            return "GENERAL"
        return "I am a mock LLM response."

def create_llm_client(provider: str, model: str = None, **kwargs) -> LLMClient:
    if provider == "ollama":
        return OllamaClient(model=model or "llama3", base_url=kwargs.get("url", "http://localhost:11434"))
    elif provider == "gemini":
        api_key = kwargs.get("api_key") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is required for Gemini provider")
        return GeminiClient(api_key=api_key, model=model or "gemini-pro")
    elif provider == "mock":
        return MockLLMClient()
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
