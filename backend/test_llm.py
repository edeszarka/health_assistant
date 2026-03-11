import asyncio
import io
import json
import re
import traceback

import httpx
import pdfplumber

async def main():
    try:
        # We need a small text
        text = "White blood cells: 5.4 10^9/L (ref 4.0-10.0)\nTest date: 2026-03-01\n"
        prompt = (
            "You are a medical data extraction assistant. "
            "Extract all lab test results from the following text.\n"
            "The text may be in Hungarian, Latin medical terminology, or English — handle all three.\n"
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
            "model": "llama3.2", # we need to check config.py for model name, I will just use llama3.2
            "prompt": prompt,
            "stream": False,
        }
        
        url = "http://localhost:11434/api/generate"
        async with httpx.AsyncClient(timeout=1000.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            
            print("RAW RESPONSE:")
            print(raw)
            print("---")
            
            raw = re.sub(r"```(?:json)?", "", raw).strip()
            raw = raw.rstrip("`").strip()
            
            print("CLEANED RESPONSE:")
            print(raw)
            
            try:
                data = json.loads(raw)
                print("parsed data type:", type(data))
                if not isinstance(data, list):
                    print("Returned dict, not list!")
                else:
                    print("Success!", data)
            except json.JSONDecodeError as e:
                print("JSON Decode error!")
    except Exception as e:
        print("err", e)

if __name__ == "__main__":
    asyncio.run(main())
