"""Groq se JSON jawab, ek Pydantic schema ki shape mein.
Sirf internet ka kaam hai: laptop ka CPU/GPU istemal nahi hota.
Kai Groq keys hon to agli key try hoti hai; rate limit (429) par thora ruk kar dobara."""
import json
import os
import re
import time

from groq import Groq
from pydantic import BaseModel, ValidationError

try:
    from studio.config import GROQ_API_KEYS
except ImportError:
    GROQ_API_KEYS = [os.getenv(k) for k in ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3")]
try:
    from studio.config import GROQ_TEXT_MODEL
except ImportError:
    GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")


class AIError(RuntimeError):
    pass


def wait_seconds(message: str) -> float:
    """Groq ka error batata hai kitna rukna hai: 'try again in 7.5s' ya 'in 1m2s'."""
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", message)
    return int(m.group(1) or 0) * 60 + float(m.group(2)) if m else 10.0


def ask_json(prompt: str, schema: type[BaseModel], log=print, temperature: float = 0.3, tries: int = 4):
    keys = [k for k in GROQ_API_KEYS if k]
    if not keys:
        raise AIError("GROQ_API_KEY nahi mili")
    schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    messages = [
        {"role": "system", "content": "Reply with ONE JSON object that matches the given JSON schema. No other text."},
        {"role": "user", "content": f"{prompt}\n\nJSON schema:\n{schema_text}"},
    ]
    last = ""
    for attempt in range(tries):
        key = keys[attempt % len(keys)]
        try:
            client = Groq(api_key=key, timeout=120, max_retries=0)
            r = client.chat.completions.create(model=GROQ_TEXT_MODEL, messages=messages, temperature=temperature,
                                               response_format={"type": "json_object"})
            return schema.model_validate_json(r.choices[0].message.content or "")
        except (ValidationError, json.JSONDecodeError) as e:
            last = f"ghalat JSON: {str(e)[:120]}"
        except Exception as e:
            last = str(e)
            if "429" in last or "rate" in last.lower():
                if attempt % len(keys) == len(keys) - 1:       # saari keys busy: ruko
                    wait = min(wait_seconds(last) + 1, 60)
                    log(f"     ⏳ Groq limit, {wait:.0f}s ruk rahe hain...")
                    time.sleep(wait)
                continue
            if "timeout" in last.lower() or "connection" in last.lower():
                time.sleep(3)
                continue
            raise AIError(f"Groq error: {last[:200]}") from e
        log(f"     ⚠ Dobara koshish ({attempt + 1}/{tries}): {last}")
    raise AIError(f"Groq se sahi jawab nahi mila: {last[:200]}")
