import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()


class AIConfigError(Exception):
    pass


class AIServiceError(Exception):
    pass


class AIService:

    def __init__(self):

        self.base = os.getenv(
            "AI_BASE_URL",
            "http://127.0.0.1:11434/v1"
        ).rstrip("/")

        self.key = os.getenv(
            "AI_API_KEY",
            "ollama"
        )

        self.model = os.getenv(
            "AI_MODEL",
            "llama3.2:3b"
        )

        self.vision_model = os.getenv(
            "AI_VISION_MODEL",
            "gemma3:4b"
        )

        self.configured = bool(
            self.base and
            self.key and
            self.model
        )

    # =========================================================
    # COMMON AI CALL
    # =========================================================

    def _call(
        self,
        messages,
        temperature=0.2,
        timeout=300,
        model=None
    ):

        if not self.configured:
            raise AIConfigError(
                "AI provider is not configured. "
                "Check backend/.env."
            )

        selected_model = model or self.model

        payload = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature
        }

        try:

            print("\n==============================")
            print("AI REQUEST")
            print("==============================")
            print("Model:", selected_model)
            print("Base URL:", self.base)
            print("Timeout:", timeout)

            response = requests.post(
                self.base + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=timeout
            )

            print("Ollama status:", response.status_code)

            if not response.ok:
                print("Ollama response:")
                print(response.text[:3000])

            response.raise_for_status()

            data = response.json()

            if "choices" not in data or not data["choices"]:
                raise AIServiceError(
                    "Ollama returned no choices."
                )

            content = data["choices"][0]["message"]["content"]

            if not content or not content.strip():
                raise AIServiceError(
                    "Ollama returned an empty response."
                )

            print("AI response received successfully.")
            print("==============================\n")

            return content

        except requests.exceptions.Timeout:

            print("\nAI TIMEOUT ERROR")

            raise AIServiceError(
                "Ollama took too long to generate the response."
            )

        except requests.exceptions.ConnectionError as e:

            print("\nOLLAMA CONNECTION ERROR")
            print(str(e))

            raise AIServiceError(
                "Could not connect to Ollama."
            )

        except requests.exceptions.HTTPError as e:

            print("\nOLLAMA HTTP ERROR")
            print(str(e))

            raise AIServiceError(
                f"Ollama HTTP error: {str(e)}"
            )

        except Exception as e:

            print("\nAI ERROR")
            print(str(e))

            raise AIServiceError(str(e))

    # =========================================================
    # TEXT GENERATION
    # =========================================================

    def generate(
        self,
        text,
        generation_type,
        language,
        style,
        custom=None
    ):

        if not text or not text.strip():
            raise AIServiceError(
                "No source content was supplied."
            )

        source = text[:30000]

        task = custom or generation_type.replace(
            "_",
            " "
        )

        system = f"""
You are Study With Me AI.

Help students understand study material.

Language: {language}
Response style: {style}

Requested task:
{task}

Rules:

1. Use the supplied source material.
2. Do not invent document facts.
3. Keep the answer clear.
4. Preserve technical terms.
5. Clearly mention uncertainty.
6. Use headings and bullet points when useful.
"""

        user = f"""
SOURCE DOCUMENT:

{source}

END SOURCE DOCUMENT.

Perform this task:

{task}
"""

        return self._call(
            [
                {
                    "role": "system",
                    "content": system
                },
                {
                    "role": "user",
                    "content": user
                }
            ],
            temperature=0.2,
            timeout=300,
            model=self.model
        )

    # =========================================================
    # CHAT + IMAGE ANALYSIS
    # =========================================================

    def chat(
        self,
        message,
        source,
        language,
        style,
        image_data_url=None
    ):

        # -----------------------------------------------------
        # NORMAL TEXT CHAT
        # -----------------------------------------------------

        if not image_data_url:

            system = f"""
You are Study With Me AI,
a friendly learning assistant.

Language: {language}
Style: {style}

If source material is supplied:

- Prioritize the source.
- Do not invent document facts.
- Explain difficult concepts simply.
"""

            content = []

            if source:

                content.append(
                    {
                        "type": "text",
                        "text": (
                            "SOURCE/CONTEXT:\n"
                            + source[:30000]
                        )
                    }
                )

            content.append(
                {
                    "type": "text",
                    "text": message
                }
            )

            return self._call(
                [
                    {
                        "role": "system",
                        "content": system
                    },
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                temperature=0.2,
                timeout=300,
                model=self.model
            )

        # -----------------------------------------------------
        # IMAGE CHAT / IMAGE ANALYZER
        # -----------------------------------------------------

        print("\n==============================")
        print("VISION REQUEST")
        print("==============================")
        print("Vision model:", self.vision_model)

        vision_system = f"""
You are Study With Me Image Analyzer.

Analyze the supplied image carefully.

Language: {language}
Response style: {style}

Your job is to:

1. Describe what is visible.
2. Identify important text, objects, diagrams,
   charts, equations or study content.
3. Explain the educational meaning when possible.
4. If text is unclear, say that it is unclear.
5. Never invent information that cannot be seen.
6. Give a useful student-friendly explanation.
"""

        vision_content = [
            {
                "type": "text",
                "text": message
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": image_data_url
                }
            }
        ]

        try:

            result = self._call(
                [
                    {
                        "role": "system",
                        "content": vision_system
                    },
                    {
                        "role": "user",
                        "content": vision_content
                    }
                ],
                temperature=0.2,
                timeout=300,
                model=self.vision_model
            )

            print("VISION ANALYSIS SUCCESS")

            return result

        except AIServiceError as e:

            print(
                "VISION ANALYSIS ERROR:",
                str(e)
            )

            raise
