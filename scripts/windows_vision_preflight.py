"""Check the Windows vision driver's local prerequisites without inference or input."""

import http.client
import os
import sys

from driver_core import osal
from driver_core.config import ConfigError, load_settings


def main():
    if osal.platform_name() != "windows":
        print("Windows is required.", file=sys.stderr)
        return 1

    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        print("The trusted child needs TYPESAFE_API_KEY.", file=sys.stderr)
        return 1

    try:
        settings = load_settings(env={**os.environ, "DRIVER_JEV_API_KEY": key})
    except ConfigError:
        print("Driver settings could not be loaded.", file=sys.stderr)
        return 1
    print(f"Driver keyed: {settings.keyed}")
    backend = osal.native_input_backend(full=True)
    if backend is None:
        print("The Windows input backend is unavailable.", file=sys.stderr)
        return 1
    print(f"Windows input kinds: {', '.join(backend.supported_kinds)}")

    connection = http.client.HTTPSConnection("api.typesafe.ai", timeout=8)
    try:
        connection.request(
            "GET", "/v1/models",
            headers={"Authorization": f"Bearer {settings.jev_api_key}"},
        )
        with connection.getresponse() as response:
            print(f"Authenticated model list: HTTP {response.status}")
            return 0 if response.status == 200 else 1
    except (OSError, ValueError, http.client.HTTPException) as error:
        print(f"Model list request failed: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
