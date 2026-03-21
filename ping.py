import requests

try:
    print("Attempting to connect...")
    response = requests.get('https://chat.collegiumacademicum.de/api/v4/system/ping', timeout=5)
    print(f"Success! Server replied: {response.text}")
except Exception as e:
    print(f"Connection Failed: {e}")