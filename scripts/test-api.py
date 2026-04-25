#!/usr/bin/env python3
"""Test script to verify the API can be imported and started."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_imports():
    """Test that all API modules can be imported."""
    print("Testing API imports...")
    
    try:
        from youtube_scrape.api.server import app, get_job_store, get_websocket_manager
        print("✓ Server imports OK")
    except Exception as e:
        print(f"✗ Server import failed: {e}")
        return False
    
    try:
        from youtube_scrape.api.routes import scrape, download, config, batch
        print("✓ Route imports OK")
    except Exception as e:
        print(f"✗ Route import failed: {e}")
        return False
    
    try:
        from youtube_scrape.api.connection_manager import ConnectionManager
        print("✓ WebSocket imports OK")
    except Exception as e:
        print(f"✗ WebSocket import failed: {e}")
        return False
    
    return True

def test_fastapi_app():
    """Test that the FastAPI app is properly configured."""
    print("\nTesting FastAPI app...")
    
    from youtube_scrape.api.server import app
    
    # Check routes
    routes = [route.path for route in app.routes]
    print(f"Registered routes: {routes}")
    
    required_routes = ['/health', '/scrape/video', '/download/video', '/config']
    for route in required_routes:
        if any(route in r for r in routes):
            print(f"✓ Route {route} found")
        else:
            print(f"✗ Route {route} NOT found")
    
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("YouTube Scrape API - Import Test")
    print("=" * 60)
    
    success = test_imports()
    if success:
        test_fastapi_app()
        print("\n✓ All tests passed!")
    else:
        print("\n✗ Some tests failed!")
        sys.exit(1)
