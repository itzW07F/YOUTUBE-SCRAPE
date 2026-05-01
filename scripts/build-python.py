#!/usr/bin/env python3
"""
Build script to bundle Python backend with PyInstaller for Electron distribution.

This creates a standalone executable that can be bundled with the Electron app.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def build_python_backend():
    """Build the Python backend using PyInstaller."""
    
    print("Building Python backend with PyInstaller...")
    
    # Ensure we're in the project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # Output directory
    dist_dir = project_root / "gui" / "resources" / "python"
    dist_dir.mkdir(parents=True, exist_ok=True)
    
    # PyInstaller command
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--name", "youtube-scrape-api",
        "--onefile",
        "--distpath", str(dist_dir),
        "--workpath", str(project_root / "build" / "pyinstaller"),
        "--specpath", str(project_root / "build"),
        "--clean",
        "--noconfirm",
        # Add hidden imports
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "fastapi",
        "--hidden-import", "starlette",
        "--hidden-import", "pydantic",
        "--hidden-import", "yaml",
        "--hidden-import", "websockets",
        "--hidden-import", "api.routes.analytics",
        "--hidden-import", "youtube_scrape.application.analytics_snapshot",
        "--hidden-import", "youtube_scrape.application.analytics_ollama_report",
        "--hidden-import", "youtube_scrape.application.analytics_gui_llm_resolve",
        "--hidden-import", "youtube_scrape.domain.analytics_models",
        "--hidden-import", "youtube_scrape.domain.analytics_aggregate",
        "--hidden-import", "youtube_scrape.adapters.analytics_artifacts",
        "--hidden-import", "youtube_scrape.adapters.ollama_client",
        "--hidden-import", "youtube_scrape.adapters.llm_errors",
        "--hidden-import", "youtube_scrape.adapters.llm_providers",
        # Data files
        "--add-data", f"src{os.pathsep}src",
        # Entry point
        str(project_root / "src" / "youtube_scrape" / "api" / "server.py"),
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed!")
        return False
    
    print(f"Build complete: {dist_dir / 'youtube-scrape-api'}")
    return True


def copy_camoufox_files():
    """Copy Camoufox browser files to resources."""
    
    print("Copying Camoufox files...")
    
    project_root = Path(__file__).parent.parent
    resources_dir = project_root / "gui" / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    
    # Find Camoufox installation
    try:
        import camoufox
        camoufox_path = Path(camoufox.__file__).parent
        
        # Copy browser files
        browser_dir = camoufox_path / "browser"
        if browser_dir.exists():
            dest = resources_dir / "camoufox"
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(browser_dir, dest)
            print(f"Copied Camoufox to {dest}")
        else:
            print("WARNING: Camoufox browser files not found")
            print("Run: python -m camoufox fetch")
            
    except ImportError:
        print("WARNING: camoufox module not installed")
        print("Run: pip install camoufox")


def main():
    """Main build function."""
    
    print("=" * 60)
    print("YouTube Scrape - Python Backend Builder")
    print("=" * 60)
    
    # Check PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("ERROR: PyInstaller not installed")
        print("Run: pip install pyinstaller")
        sys.exit(1)
    
    # Build
    if not build_python_backend():
        sys.exit(1)
    
    # Copy additional files
    copy_camoufox_files()
    
    print("=" * 60)
    print("Build complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
