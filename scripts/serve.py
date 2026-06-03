#!/usr/bin/env python3
"""Start the FastAPI web server."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import uvicorn

if __name__ == '__main__':
    uvicorn.run(
        'web.app:app',
        host='0.0.0.0',
        port=8000,
        reload=True,
        reload_dirs=[os.path.join(os.path.dirname(__file__), '..', 'src')],
    )
