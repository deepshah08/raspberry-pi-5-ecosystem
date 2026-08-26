import logging
from config import LLM_MODEL, LLM_URL

logger = logging.getLogger(__name__)

class SocraticAgent:
    def __init__(self):
        try:
            import ollama
            self.client = ollama.Client(host=LLM_URL)
        except Exception:
            self.client = None
        
    def generate_response(self, query: str, context: str, direct_answer: bool = False):
        if direct_answer:
            sys_prompt = "You are a direct, highly accurate tutor. Keep your response extremely concise (under 3 sentences). Use the provided context to answer the user's question explicitly and accurately."
        else:
            sys_prompt = """You are a Socratic AI Tutor. Do NOT just give the user the direct answer. 
            Keep your response EXTREMELY concise (under 3 sentences).
            Use the provided context to formulate a single guiding question, hint, or analogy.
            Encourage critical thinking and understanding over rote memorization.
            If the context contains a graph or structural path, use it to guide the user to the next logical step."""
            
        full_prompt = f"Context from offline database:\n{context}\n\nUser Question: {query}"
        
        if self.client is None:
            return f"[Socratic Guidance]: Consider how the fundamental principles of {query} connect to your prior knowledge."
            
        try:
            response = self.client.chat(model=LLM_MODEL, messages=[
                {'role': 'system', 'content': sys_prompt},
                {'role': 'user', 'content': full_prompt}
            ])
            return response['message']['content']
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return f"[Offline Mode] Review the prerequisites for: {query}"
