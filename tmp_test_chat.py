import urllib.request
import urllib.error
import json
import time

def test_chat():
    url = "http://localhost:8000/chat/"
    data = json.dumps({"message": "calculate my FINDRISC. if you need the info, I am 83 kg", "conversation_history": []}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            print("Status:", r.status)
            print("Response:", r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTPError: {e.code}")
        print("Response:", e.read().decode("utf-8"))
    except Exception as e:
        print(f"Exception: {e}")
    finally:
        print(f"Elapsed: {time.time() - start:.2f}s")

if __name__ == "__main__":
    test_chat()
