"""Configuration model + resolve(flag, env, fallback) helper with source tracking."""

import logging
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class ConfigSource(StrEnum):
    """Where a config value came from. Surfaced by inkscape_system(diagnostics)."""

    CLI_FLAG = "cli_flag"
    ENV_VAR = "env_var"
    CONFIG_FILE = "config_file"
    AUTO_DETECTED = "auto_detected"
    DEFAULT = "default"


@dataclass(frozen=True)
class Resolved:
    """A resolved config value paired with its provenance."""

    value: Any
    source: ConfigSource
    detail: str = ""


def resolve(
    *,
    flag_value: Any = None,
    env_var: str | None = None,
    file_value: Any = None,
    fallback: Any = None,
) -> Resolved:
    """Pick the highest-priority value among CLI flag > env var > config file > fallback."""
    if flag_value is not None:
        return Resolved(flag_value, ConfigSource.CLI_FLAG, detail="set on command line")
    if env_var:
        env_val = os.environ.get(env_var)
        if env_val is not None:
            return Resolved(env_val, ConfigSource.ENV_VAR, detail=f"${env_var}")
    if file_value is not None:
        return Resolved(file_value, ConfigSource.CONFIG_FILE)
    return Resolved(fallback, ConfigSource.DEFAULT)


class InkscapeConfig(BaseModel):
    """
    Configuration model for Inkscape MCP Server.
    """

    # Without this, the env-override assignments in load_config() bypass every Field
    # bound and validator — process_timeout accepted 999 despite le=300, and assigning
    # temp_directory never ran the mkdir/writable check.
    model_config = ConfigDict(validate_assignment=True)

    # Inkscape Configuration
    inkscape_executable: str | None = Field(
        default=None, description="Path to Inkscape executable (auto-detected if None)"
    )

    # Performance Settings
    max_concurrent_processes: int = Field(
        default=3, ge=1, le=10, description="Maximum number of concurrent Inkscape processes"
    )

    process_timeout: int = Field(default=30, ge=5, le=300, description="Timeout for Inkscape operations in seconds")

    # File Handling
    temp_directory: str = Field(
        default_factory=lambda: tempfile.gettempdir(), description="Directory for temporary files"
    )

    max_file_size_mb: int = Field(default=100, ge=1, le=1000, description="Maximum file size in MB")

    preserve_metadata: bool = Field(default=True, description="Preserve EXIF and other metadata when possible")

    auto_cleanup: bool = Field(default=True, description="Automatically clean up temporary files")

    cleanup_interval: int = Field(default=3600, ge=60, description="Cleanup interval in seconds")

    # Image Processing Defaults
    default_quality: int = Field(default=95, ge=1, le=100, description="Default JPEG quality (1-100)")

    default_interpolation: str = Field(default="lanczos", description="Default interpolation method for resizing")

    supported_formats: list[str] = Field(
        default_factory=lambda: [
            "svg",
            "pdf",
            "png",
            "jpeg",
            "jpg",
            "webp",
            "eps",
            "ps",
            "ai",
            "cdr",
            "wmf",
            "emf",
        ],
        description="List of supported vector and image formats",
    )

    # Batch Processing
    enable_batch_operations: bool = Field(default=True, description="Enable batch processing capabilities")

    # Extension System
    enable_extensions: bool = Field(default=True, description="Enable Inkscape extension system")

    extension_dirs: list[str] = Field(default_factory=list, description="List of directories to search for extensions")

    disabled_extensions: list[str] = Field(default_factory=list, description="List of extension IDs to disable")

    extension_config: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Extension-specific configuration"
    )

    batch_size_limit: int = Field(default=50, ge=1, le=200, description="Maximum number of files in a single batch")

    # Logging and Debug
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)")

    enable_performance_logging: bool = Field(default=False, description="Enable detailed performance logging")

    # Security Settings
    enable_file_validation: bool = Field(default=True, description="Enable file type validation")

    allowed_directories: list[str] = Field(
        default_factory=list, description="List of allowed directories for file operations"
    )

    @field_validator("temp_directory")
    @classmethod
    def validate_temp_directory(cls, v: str) -> str:
        """Validate and create temp directory if needed."""
        path = Path(v)
        try:
            path.mkdir(parents=True, exist_ok=True)
            if not os.access(path, os.W_OK):
                raise ValueError(f"Temp directory not writable: {v}")
        except Exception as e:
            raise ValueError(f"Invalid temp directory: {v} - {e}") from e
        return str(path)

    @field_validator("default_interpolation")
    @classmethod
    def validate_interpolation(cls, v: str) -> str:
        """Validate interpolation method."""
        valid_methods = ["none", "linear", "cubic", "lanczos"]
        if v.lower() not in valid_methods:
            raise ValueError(f"Invalid interpolation method: {v}. Must be one of {valid_methods}")
        return v.lower()

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate logging level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v.upper()

    @classmethod
    def load_from_file(cls, config_path: str | Path) -> "InkscapeConfig":
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to configuration file

        Returns:
            InkscapeConfig: Loaded configuration

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config file is invalid
        """
        path = Path(config_path)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        try:
            with open(path, encoding="utf-8") as f:
                config_data = yaml.safe_load(f)

            if config_data is None:
                config_data = {}

            return cls(**config_data)

        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in config file: {e}") from e
        except Exception as e:
            raise ValueError(f"Failed to load config: {e}") from e

    @classmethod
    def load_default(cls) -> "InkscapeConfig":
        """
        Load default configuration with auto-detection.

        Returns:
            InkscapeConfig: Default configuration
        """
        # Look for config file in common locations
        config_paths = [
            Path.cwd() / "config.yaml",
            Path.cwd() / "inkscape_mcp.yaml",
            Path.home() / ".inkscape_mcp" / "config.yaml",
            Path.home() / ".config" / "inkscape_mcp" / "config.yaml",
        ]

        for config_path in config_paths:
            if config_path.exists():
                logger.info(f"Loading configuration from: {config_path}")
                try:
                    return cls.load_from_file(config_path)
                except Exception as e:
                    logger.warning(f"Failed to load config from {config_path}: {e}")

        logger.info("Using default configuration")
        return cls()

    def save_to_file(self, config_path: str | Path) -> None:
        """
        Save configuration to YAML file.

        Args:
            config_path: Path to save configuration
        """
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # model_dump, not the pydantic-v1 .dict() shim (deprecated, emits a warning).
        config_dict = self.model_dump(exclude_none=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(config_dict, f, default_flow_style=False, sort_keys=True, indent=2)
            logger.info(f"Configuration saved to: {path}")

        except Exception as e:
            logger.error(f"Failed to save config to {path}: {e}")
            raise

    def create_temp_subdirectory(self, name: str) -> Path:
        """
        Create a subdirectory in the temp directory.

        Args:
            name: Subdirectory name

        Returns:
            Path: Path to created subdirectory
        """
        subdir = Path(self.temp_directory) / name
        subdir.mkdir(parents=True, exist_ok=True)
        return subdir

    def is_format_supported(self, format_name: str) -> bool:
        """
        Check if an image format is supported.

        Args:
            format_name: Format name to check

        Returns:
            bool: True if format is supported
        """
        return format_name.lower() in [fmt.lower() for fmt in self.supported_formats]

    def get_temp_file_path(self, suffix: str = "") -> Path:
        """
        Generate a unique temporary file path.

        Args:
            suffix: File suffix/extension

        Returns:
            Path: Unique temporary file path
        """
        import uuid

        filename = f"inkscape_mcp_{uuid.uuid4().hex[:8]}{suffix}"
        return Path(self.temp_directory) / filename

    def validate_file_size(self, file_path: str | Path) -> bool:
        """
        Validate file size against configured limits.

        Args:
            file_path: Path to file to validate

        Returns:
            bool: True if file size is acceptable
        """
        try:
            file_size = Path(file_path).stat().st_size
            max_size = self.max_file_size_mb * 1024 * 1024
            return file_size <= max_size
        except Exception:
            return False


def load_config(config_path: str | Path | None = None) -> InkscapeConfig:
    """Load config (file > env > defaults) and stamp each tracked setting with its source."""
    if config_path is None:
        config_dir = Path.home() / ".config" / "inkscape_mcp"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        logger.info(f"Config file not found at {config_path}, creating default config")
        create_default_config_file(config_path)

    try:
        cfg = InkscapeConfig.load_from_file(config_path)
    except Exception as e:
        logger.error(f"Error loading config from {config_path}: {e}")
        logger.info("Falling back to default configuration")
        cfg = InkscapeConfig.load_default()

    # Layer env-var overrides on top of file values, tracking provenance.
    sources: dict[str, Resolved] = {}

    bin_resolved = resolve(
        env_var="INKSCAPE_BIN",
        file_value=cfg.inkscape_executable,
        fallback=None,
    )
    cfg.inkscape_executable = bin_resolved.value
    sources["inkscape_executable"] = bin_resolved

    tmp_resolved = resolve(
        env_var="INKSCAPE_MCP_TEMP_DIR",
        file_value=cfg.temp_directory,
        fallback=tempfile.gettempdir(),
    )
    cfg.temp_directory = tmp_resolved.value
    sources["temp_directory"] = tmp_resolved

    timeout_resolved = resolve(
        env_var="INKSCAPE_MCP_TIMEOUT",
        file_value=cfg.process_timeout,
        fallback=30,
    )
    # A malformed or out-of-range INKSCAPE_MCP_TIMEOUT used to kill startup with an
    # uncaught ValueError (or, before validate_assignment, be accepted silently).
    # Warn and keep the default instead — a bad env var shouldn't take the server down.
    try:
        cfg.process_timeout = int(timeout_resolved.value) if timeout_resolved.value is not None else 30
    except (TypeError, ValueError) as exc:
        logger.warning(
            f"Ignoring invalid INKSCAPE_MCP_TIMEOUT={timeout_resolved.value!r} ({exc}); keeping {cfg.process_timeout}s"
        )
        timeout_resolved = Resolved(cfg.process_timeout, ConfigSource.DEFAULT, detail="invalid override ignored")
    sources["process_timeout"] = timeout_resolved

    object.__setattr__(cfg, "_sources", sources)
    return cfg


def create_default_config_file(config_path: str | Path) -> None:
    """
    Create a default configuration file with comments.

    Args:
        config_path: Path where to create the config file
    """
    config_content = """
# Inkscape MCP Server Configuration
# This file configures the Inkscape MCP server behavior and settings

# Inkscape Configuration
# inkscape_executable: "/path/to/inkscape"  # Auto-detected if not specified

# Performance Settings
max_concurrent_processes: 3  # Number of concurrent Inkscape processes
process_timeout: 30          # Timeout for operations in seconds

# File Handling
temp_directory: "/tmp"       # Directory for temporary files (auto-detected)
max_file_size_mb: 100       # Maximum file size in MB
preserve_metadata: true     # Preserve metadata when possible
auto_cleanup: true          # Automatically clean up temp files
cleanup_interval: 3600      # Cleanup interval in seconds

# Image Processing Defaults
default_quality: 95         # Default JPEG quality (1-100)
default_interpolation: "lanczos"  # Interpolation method for resizing

# Supported formats (add/remove as needed)
supported_formats:
  - "svg"
  - "pdf"
  - "eps"
  - "png"
  - "ps"
  - "ai"
  - "cdr"
  - "wmf"
  - "emf"
  - "xaml"

# Batch Processing
enable_batch_operations: true
batch_size_limit: 50        # Max files per batch

# Extension System
enable_extensions: true       # Enable/disable extension system
# extension_dirs:             # Additional extension directories
#   - "/path/to/extensions"
# disabled_extensions:        # List of extension IDs to disable
#   - "org.inkscape.example"
# extension_config:           # Extension-specific configuration
#   org.project_ag.batch_trace:
#     default_colors: 4
#     simplify_paths: true

# Logging and Debug
log_level: "INFO"           # DEBUG, INFO, WARNING, ERROR
enable_performance_logging: false

# Security Settings
enable_file_validation: true
# allowed_directories:      # Restrict operations to these directories
#   - "/home/user/images"
#   - "/var/www/uploads"
""".strip()

    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(config_content)

    logger.info(f"Created default configuration file: {path}")
