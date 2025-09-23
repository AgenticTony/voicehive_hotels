"""
Simple error handling test
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from error_models import AuthenticationError


def test_basic_error():
    """Test basic error without middleware"""
    app = FastAPI()
    
    @app.get("/test")
    def test_endpoint():
        raise HTTPException(status_code=404, detail="Not found")
    
    client = TestClient(app)
    response = client.get("/test")
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    assert response.status_code == 404


def test_custom_error():
    """Test custom error without middleware"""
    app = FastAPI()
    
    @app.get("/test")
    def test_endpoint():
        raise AuthenticationError("Invalid token")
    
    client = TestClient(app)
    
    try:
        response = client.get("/test")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Exception: {e}")


if __name__ == "__main__":
    test_basic_error()
    test_custom_error()