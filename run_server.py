import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "jarvix.app:app",
        host=os.getenv("JARVIX_HOST", "127.0.0.1"),
        port=int(os.getenv("JARVIX_PORT", "8765")),
        reload=False,
    )
