import json
import os
from pathlib import Path

from openai import AsyncOpenAI
from pypdf import PdfReader

from tools import record_unknown_question, record_user_details, tools

TOOL_REGISTRY = {
    "record_user_details": record_user_details,
    "record_unknown_question": record_unknown_question,
}


class Me:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(timeout=12.0)
        self.name = os.getenv("YOUR_NAME", "the professional")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.max_tokens = int(os.getenv("MAX_RESPONSE_TOKENS", "400"))

        base = Path(__file__).parent / "me"
        self.linkedin = self._load_linkedin(base / "linkedin.pdf")
        self.summary = (base / "summary.txt").read_text(encoding="utf-8")

    @staticmethod
    def _load_linkedin(path: Path) -> str:
        reader = PdfReader(str(path))
        out = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                out.append(text)
        return "".join(out)

    def _handle_tool_calls(self, tool_calls) -> list[dict]:
        results = []
        for call in tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            fn = TOOL_REGISTRY.get(name)
            result = fn(**args) if fn else {"error": "unknown_tool"}
            results.append(
                {
                    "role": "tool",
                    "content": json.dumps(result),
                    "tool_call_id": call.id,
                }
            )
        return results

    def system_prompt(self) -> str:
        prompt = f"""
You are {self.name}, your official digital representative.

SCOPE - WHAT YOU CAN ANSWER:
Only questions DIRECTLY about {self.name}'s professional background:
- Career, experience, projects, skills, certifications
- Technical background and expertise
- Basic identity (name, age, current role and employer, location, spoken languages)

REFUSE everything else: general knowledge, definitions, how-to guides, science, history.

LANGUAGE: Always respond in the user's language.

MANDATORY TOOL USAGE FOR OUT-OF-SCOPE QUESTIONS:
When refusing an out-of-scope question:
1. Call record_unknown_question tool (REQUIRED - not optional)
2. Then give brief polite refusal

Example refusals (use these exact phrases):
- Turkish: "Kusura bakmayın, bu soru profesyonel geçmişimle ilgili olmadığı için yanıt veremem."
- English: "I apologize, but that question is outside my professional scope."

LEAD CAPTURE:
When user expresses hiring interest, collaboration, or provides contact info:
- Use record_user_details tool to save their email and name
- Guide conversation toward direct contact professionally

CRITICAL RULES:
- NEVER mention tools to the user
- NEVER say "recording", "logged", "saved"
- NEVER answer general knowledge questions
- NEVER invent professional details not provided
- ALWAYS use record_unknown_question for refused questions
- ALWAYS use record_user_details when user provides contact info

You exist ONLY to represent {self.name}'s professional background accurately.
"""
        prompt += (
            f"\n\n## Summary:\n{self.summary}\n\n"
            f"## LinkedIn Profile:\n{self.linkedin}\n\n"
        )
        prompt += (
            f"With this context, please chat with the user, always staying in "
            f"character as {self.name}."
        )
        return prompt

    async def chat_async(
        self, message: str, history: list[dict]
    ) -> tuple[str, int, str]:
        messages: list[dict] = [{"role": "system", "content": self.system_prompt()}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        total_tokens = 0
        for _ in range(5):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=self.max_tokens,
            )
            if response.usage:
                total_tokens += response.usage.total_tokens

            choice = response.choices[0]
            llm_message = choice.message

            if choice.finish_reason == "tool_calls" and llm_message.tool_calls:
                messages.append(llm_message)
                messages.extend(self._handle_tool_calls(llm_message.tool_calls))
                continue

            return (llm_message.content or "", total_tokens, self.model)

        return ("", total_tokens, self.model)
