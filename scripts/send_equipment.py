"""Independent synthetic sender. Stable event JSON is reused on every retry.
Usage: python scripts/send_equipment.py --run RUN --event event.json
Token is read from TERMINAL_FEED_TOKEN, never a command-line argument.
"""

import argparse
import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8790")
    parser.add_argument("--run", required=True)
    parser.add_argument("--event", required=True)
    args = parser.parse_args()
    token = os.environ["TERMINAL_FEED_TOKEN"]
    with open(args.event) as f:
        data = json.dumps(json.load(f)).encode()
    url = (
        args.url.rstrip("/")
        + "/api/integrations/equipment?"
        + urllib.parse.urlencode({"run": args.run})
    )
    for attempt in range(4):
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.load(response)
            print(json.dumps(result))
            return 0 if result["status"] in ("applied", "duplicate") else 2
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 3:
                print("Delivery rejected with HTTP", e.code)
                return 1
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                print(
                    "Delivery unconfirmed; retry the SAME event ID after checking the receiver"
                )
                return 1
        time.sleep(2**attempt)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
