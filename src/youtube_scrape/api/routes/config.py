"""Config endpoints for the API."""

import logging
import os
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class ConfigUpdate(BaseModel):
    """Configuration update request."""
    output_directory: Optional[str] = None
    browser_headless: Optional[bool] = None
    browser_timeout: Optional[int] = None
    max_concurrent_jobs: Optional[int] = None
    proxy: Optional[str] = None


class ConfigResponse(BaseModel):
    """Current configuration."""
    output_directory: str
    browser_headless: bool
    browser_timeout: int
    max_concurrent_jobs: int
    proxy: Optional[str]
    schema_version: str


class Preset(BaseModel):
    """Scrape preset."""
    name: str
    description: str
    options: Dict[str, Any]


# Default presets
DEFAULT_PRESETS: List[Preset] = [
    Preset(
        name="Quick Metadata",
        description="Fast video metadata extraction only",
        options={
            "include_video": True,
            "include_comments": False,
            "include_transcript": False,
            "include_thumbnails": False,
            "include_download": False,
        }
    ),
    Preset(
        name="Full Scrape",
        description="Get everything: metadata, comments, transcript, thumbnails",
        options={
            "include_video": True,
            "include_comments": True,
            "include_transcript": True,
            "include_thumbnails": True,
            "include_download": False,
            "max_comments": 0,
            "max_replies_per_thread": None,
        }
    ),
    Preset(
        name="Download Video",
        description="Download video in best quality",
        options={
            "include_video": True,
            "include_comments": False,
            "include_transcript": False,
            "include_thumbnails": False,
            "include_download": True,
            "video_quality": "best",
        }
    ),
    Preset(
        name="Audio Only",
        description="Download audio in MP3 format",
        options={
            "include_video": True,
            "include_comments": False,
            "include_transcript": False,
            "include_thumbnails": False,
            "include_download": True,
            "video_quality": "audio",
        }
    ),
]


def get_config_path() -> str:
    """Get the path to the config file."""
    # Check environment variable first
    if config_path := os.environ.get("CONFIG_PATH"):
        return config_path
    
    # Use default location
    return os.path.join(os.getcwd(), "config.yaml")


def load_config_from_file() -> Dict[str, Any]:
    """Load configuration from file."""
    import yaml
    
    config_path = get_config_path()
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    
    return {}


def save_config_to_file(config: Dict[str, Any]) -> None:
    """Save configuration to file."""
    import yaml
    
    config_path = get_config_path()
    
    try:
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")


@router.get("/", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """Get current configuration."""
    file_config = load_config_from_file()
    
    return ConfigResponse(
        output_directory=file_config.get("output", {}).get("directory", os.path.join(os.getcwd(), "output")),
        browser_headless=file_config.get("browser", {}).get("headless", True),
        browser_timeout=file_config.get("browser", {}).get("timeout", 30000),
        max_concurrent_jobs=file_config.get("max_concurrent_jobs", 2),
        proxy=file_config.get("browser", {}).get("proxy"),
        schema_version="1.0.0",
    )


@router.put("/")
async def update_config(update: ConfigUpdate) -> Dict[str, Any]:
    """Update configuration."""
    config = load_config_from_file()
    
    if update.output_directory is not None:
        if "output" not in config:
            config["output"] = {}
        config["output"]["directory"] = update.output_directory
        os.makedirs(update.output_directory, exist_ok=True)
    
    if update.browser_headless is not None:
        if "browser" not in config:
            config["browser"] = {}
        config["browser"]["headless"] = update.browser_headless
    
    if update.browser_timeout is not None:
        if "browser" not in config:
            config["browser"] = {}
        config["browser"]["timeout"] = update.browser_timeout
    
    if update.max_concurrent_jobs is not None:
        config["max_concurrent_jobs"] = update.max_concurrent_jobs
    
    if update.proxy is not None:
        if "browser" not in config:
            config["browser"] = {}
        config["browser"]["proxy"] = update.proxy
    
    save_config_to_file(config)
    
    return {"status": "updated", "message": "Configuration saved successfully"}


@router.get("/presets", response_model=List[Preset])
async def get_presets() -> List[Preset]:
    """Get available scrape presets."""
    return DEFAULT_PRESETS


@router.get("/presets/{name}")
async def get_preset(name: str) -> Preset:
    """Get a specific preset by name."""
    for preset in DEFAULT_PRESETS:
        if preset.name.lower().replace(" ", "-") == name.lower():
            return preset
    
    raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")


@router.get("/output-dir")
async def get_output_directory() -> Dict[str, str]:
    """Get the current output directory."""
    config = load_config_from_file()
    output_dir = config.get("output", {}).get("directory", os.path.join(os.getcwd(), "output"))
    
    return {
        "path": output_dir,
        "exists": os.path.exists(output_dir),
    }


@router.post("/output-dir")
async def set_output_directory(path: str) -> Dict[str, Any]:
    """Set the output directory."""
    try:
        os.makedirs(path, exist_ok=True)
        
        config = load_config_from_file()
        if "output" not in config:
            config["output"] = {}
        config["output"]["directory"] = path
        save_config_to_file(config)
        
        return {"status": "success", "path": path}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}")


@router.get("/schema")
async def get_config_schema() -> Dict[str, Any]:
    """Get the configuration schema."""
    return {
        "output": {
            "directory": {"type": "string", "default": "./output", "description": "Output directory for scraped data"},
            "schema_version": {"type": "string", "default": "1.0.0"},
        },
        "browser": {
            "headless": {"type": "boolean", "default": True, "description": "Run browser in headless mode"},
            "timeout": {"type": "integer", "default": 30000, "description": "Request timeout in milliseconds"},
            "proxy": {"type": "string", "nullable": True, "description": "Proxy URL (e.g., http://proxy:8080)"},
        },
        "max_concurrent_jobs": {"type": "integer", "default": 2, "description": "Maximum concurrent scraping jobs"},
    }
