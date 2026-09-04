"""
verify_gemini.py
================
REAL end-to-end Gemini connectivity proof.

Sends a genuine request to the Gemini API using GEMINI_API_KEY / GEMINI_MODEL
from the environment (or .env) and prints the exact raw model-generated text.

This is a DIAGNOSTIC script: it never simulates, never caches, never falls back.
If the request fails, the real exception is printed and the exit code is 1.

Run:  python verify_gemini.py
"""
import os
import sys
import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("verify_gemini")


def main() -> int:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    print("=" * 64)
    print("GEMINI LIVE VERIFICATION")
    print("=" * 64)
    print(f"Gemini API configured: {'YES' if api_key else 'NO'}")
    print(f"Gemini model: {model}")
    if not api_key:
        print("FATAL: no GEMINI_API_KEY in environment/.env")
        return 1

    from google import genai
    from google.genai import types

    # 60s per attempt; the loop below retries transient 429/5xx conditions.
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=60000),
    )

    user_input = (
        "You are a warehouse loading-quality inspector. A truck contains 3 crates "
        "(2 heavy 120kg on the floor, 1 fragile 20kg stacked on top). "
        "In 2-3 sentences, assess the stacking safety and name the main risk. "
        "Answer in plain prose (no JSON)."
    )

    print("-" * 64)
    print("GEMINI REQUEST")
    print(f"Model: {model}")
    print(f"Text prompt length: {len(user_input)} chars")
    print(f"CCTV image: ABSENT   Depth image: ABSENT   (pure-text probe)")
    print("Request started...")

    response = None
    last_err: Exception = None
    for attempt in range(1, 4):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[user_input],
                config=types.GenerateContentConfig(temperature=0.7),
            )
            break
        except Exception as e:
            last_err = e
            msg = str(e).upper()
            transient = any(s in msg for s in (
                "UNAVAILABLE", "RESOURCE_EXHAUSTED", "OVERLOADED",
                " 503", " 429", " 504", "HIGH DEMAND", "TRY AGAIN LATER",
                "DEADLINE_EXCEEDED",
            ))
            print(f"  attempt {attempt}/3 failed: {type(e).__name__}: {e}")
            if transient and attempt < 3:
                wait = 5 * attempt
                print(f"  transient -> retrying in {wait}s ...")
                import time as _t
                _t.sleep(wait)
                continue
            break

    if response is None:
        print("GEMINI RESPONSE")
        print(f"Model: {model}")
        print(f"Status: FAILED")
        print(f"Exception type: {type(last_err).__name__}")
        print(f"Exception details: {last_err}")
        return 1

    raw = getattr(response, "text", None)
    finish = None
    try:
        finish = response.candidates[0].finish_reason
    except Exception:
        pass

    print("-" * 64)
    print("GEMINI RESPONSE")
    print(f"Model: {model}")
    print(f"Status: {'SUCCESS' if raw else 'EMPTY'}")
    print(f"Response length: {len(raw) if raw else 0} chars")
    print(f"Finish reason: {finish}")
    print("-" * 64)
    print("RAW GEMINI RESPONSE (exact model output):")
    print(raw)
    print("-" * 64)

    if not raw:
        print("Result: request completed but the model returned no text.")
        return 1
    print("Result: REAL Gemini response received and displayed above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
