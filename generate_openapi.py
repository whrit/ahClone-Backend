#!/usr/bin/env python3
"""
Script to generate OpenAPI JSON schema from FastAPI application.
This will output the schema to the frontend directory.
"""

import json
import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from app.main import app

if __name__ == "__main__":
    # Get the OpenAPI schema
    openapi_schema = app.openapi()

    # Define output path (frontend directory)
    backend_dir = Path(__file__).parent
    frontend_dir = backend_dir.parent / "frontend"
    output_path = frontend_dir / "openapi.json"

    # Write the schema to file
    with open(output_path, "w") as f:
        json.dump(openapi_schema, f, indent=2)

    print(f"OpenAPI schema generated successfully at: {output_path}")
    print(f"Schema contains {len(openapi_schema.get('paths', {}))} paths")
