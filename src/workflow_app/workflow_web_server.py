from __future__ import annotations

# Compatibility facade:
# keep import path and startup command unchanged while runtime implementation
# lives in layered modules.
from .server.bootstrap.web_server_runtime import *  # noqa: F401,F403
from .server.bootstrap.web_server_runtime import main


if __name__ == "__main__":
    main()
