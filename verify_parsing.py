import sys
import os

# Add backend to path for imports
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from ingestion.zepp_parser import ZeppParser
from ingestion.samsung_parser import SamsungHealthParser

def test_zepp():
    print("Testing Zepp parsing...")
    zp = ZeppParser()
    path = os.path.join(os.getcwd(), 'zipped', '7048156920_1773219636757.zip')
    try:
        report = zp.parse(path, password='TIHFqBtV')
        print(f"Zepp parsed! Files found: {report.files_found}")
        summaries = report.daily_summaries()
        print(f"Zepp parsed! Found {len(summaries)} daily summaries.")
        # Find a day with weight
        weight_days = [s for s in summaries if s.get("weight_kg")]
        if weight_days:
            print(f"Sample Zepp day with weight: {weight_days[0]}")
        else:
            print("No weight data found in Zepp summaries.")
    except Exception as e:
        print(f"Zepp parsing failed: {e}")

def test_samsung():
    print("Testing Samsung parsing...")
    sp = SamsungHealthParser()
    path = os.path.join(os.getcwd(), 'zipped', 'samsunghealth_szarkaede_20260226101817.zip')
    try:
        report = sp.parse(path)
        print(f"Samsung parsed! Files found: {report.files_found}")
        summaries = report.daily_summaries()
        print(f"Samsung parsed! Found {len(summaries)} daily summaries.")
        weight_days = [s for s in summaries if s.get("weight_kg")]
        if weight_days:
            print(f"Sample Samsung day with weight: {weight_days[0]}")
    except Exception as e:
        print(f"Samsung parsing failed: {e}")

if __name__ == "__main__":
    test_zepp()
    test_samsung()
