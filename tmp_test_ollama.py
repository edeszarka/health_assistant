import urllib.request
import urllib.error
import json
import time

def test_ollama():
    url = "http://localhost:11434/api/chat"
    
    payload = {
        "model": "llama3.1:8b", # or deepseek-r1 if they use it
        "messages": [{"role": "user", "content": "calculate my FINDRISC. if you need the info, I am 83 kg"}],
        "stream": False,
        "options": {
            "num_predict": 1024
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            print("Status:", r.status)
            print("Response:", r.read().decode("utf-8")[:500])
    except Exception as e:
        print(f"Exception: {e}")
    finally:
        print(f"Elapsed: {time.time() - start:.2f}s")

if __name__ == "__main__":
    test_ollama()
