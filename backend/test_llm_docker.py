import asyncio
import httpx
import json
import re
import traceback

async def main():
    ollama_url = "http://ollama:11434/api/generate"
    model = "llama3.1:8b"
    
    text = "WBC: 5.4 10^9/L, RBC: 4.8 10^12/L. Date: 2024-05-10"
    prompt = (
        "You are a medical data extraction assistant. "
        "Extract all lab test results from the following text.\n"
        "Return ONLY a valid JSON array. Each item must have exactly these keys:\n"
        '- "raw_name": the test name exactly as it appears in the text\n'
        '- "value": numeric value as a float\n'
        '- "unit": unit of measurement as a string\n'
        '- "ref_range_low": lower bound of reference range as float or null\n'
        '- "ref_range_high": upper bound of reference range as float or null\n'
        '- "test_date": date in ISO format YYYY-MM-DD or null if not found\n\n'
        f"Text to parse:\n{text}\n\n"
        "Return ONLY the JSON array, no explanation, no markdown."
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }

    print(f"Connecting to {ollama_url} with model {model}...")
    try:
        # Increase timeout significantly
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(ollama_url, json=payload)
            print(f"Status Code: {resp.status_code}")
            if resp.status_code != 200:
                print(f"Response Body: {resp.text}")
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            print(f"RAW RESPONSE: {raw}")
            
            # Simulate the parser cleaning
            cleaned = re.sub(r"```(?:json)?", "", raw).strip()
            cleaned = cleaned.rstrip("`").strip()
            
            try:
                data = json.loads(cleaned)
                print(f"PARSED SUCCESS: {data}")
            except Exception:
                match = re.search(r"\[.*\]", cleaned, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(0))
                        print(f"PARSED FALLBACK SUCCESS: {data}")
                    except Exception as e:
                        print(f"PARSED FAIL: {e}")
                else:
                    print("NO JSON ARRAY FOUND")
                    
    except Exception as e:
        print(f"EXECUTION FAILED: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
