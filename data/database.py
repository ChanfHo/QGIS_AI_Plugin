"""Separate local maintenance settings from intentionally public read-only access."""

import json
import os
from pathlib import Path
from typing import Dict

import psycopg2

_FIELDS = {
    "host": ("QGIS_AI_DB_HOST", ""),
    "port": ("QGIS_AI_DB_PORT", "5432"),
    "dbname": ("QGIS_AI_DB_NAME", "qgis_ai_plugin_db"),
    "user": ("QGIS_AI_DB_USER", ""),
    "password": ("QGIS_AI_DB_PASSWORD", ""),
    "connect_timeout": ("QGIS_AI_DB_CONNECT_TIMEOUT", "5"),
}
_PUBLIC_CONFIGURATION = Path(__file__).resolve().parents[1] / "config" / "database_public.json"
_PRIVATE_CONFIGURATION = Path(__file__).resolve().parents[1] / "config" / "database_private.json"


class DatabaseConfigurationError(ValueError):
    """Classify missing deployment settings as a database failure, not GIS parameters."""
    error_code = "DATABASE_FAILED"


def database_is_read_only() -> bool:
    """A bundled public profile selects the read-only distribution."""
    return _PUBLIC_CONFIGURATION.is_file()


def database_configuration_path() -> Path:
    """Store private maintenance credentials outside Git and plugin packages."""
    if os.name == "nt":
        directory = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        directory = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return directory / "QGIS-AI-Mapper" / "database.private.json"


def _read_config(path) -> Dict[str, object]:
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict) or set(values) - set(_FIELDS) - {"read_only"}:
            raise ValueError()
        if path == _PUBLIC_CONFIGURATION and values.get("read_only") is not True:
            raise ValueError()
        return values
    except (OSError, ValueError, TypeError):
        raise DatabaseConfigurationError("Database configuration could not be read; check its format and permissions.") from None


def _normalize_config(values) -> Dict[str, object]:
    config = {key: values.get(key, default) for key, (_, default) in _FIELDS.items()}
    if any(not isinstance(config[key], str) for key in ("host", "dbname", "user", "password")):
        raise DatabaseConfigurationError("Database connection text fields must be strings")
    if not all(config[key].strip() for key in ("host", "dbname", "user")):
        raise DatabaseConfigurationError("Configure a database host, database name and user before using remote services.")
    try:
        config["port"] = int(config["port"])
        config["connect_timeout"] = int(config["connect_timeout"])
        if not 1 <= config["port"] <= 65535 or config["connect_timeout"] < 1:
            raise ValueError()
    except (ValueError, TypeError):
        raise DatabaseConfigurationError("Database port or connection timeout is invalid") from None
    return config


def get_database_config() -> Dict[str, object]:
    """Public builds never inherit private local settings or private environment overrides."""
    public = database_is_read_only()
    if public:
        local = _read_config(_PUBLIC_CONFIGURATION)
    else:
        path = database_configuration_path()
        complete_environment = all(os.environ.get(environment, "").strip() for environment, _ in _FIELDS.values())
        local = _read_config(_PRIVATE_CONFIGURATION) if _PRIVATE_CONFIGURATION.exists() else {}
        if path.exists() and not complete_environment:
            local.update(_read_config(path))
    values = {}
    for key, (environment, default) in _FIELDS.items():
        if public:
            environment = environment.replace("QGIS_AI_DB_", "QGIS_AI_PUBLIC_DB_")
        override = os.environ.get(environment)
        values[key] = override if override is not None and override.strip() else local.get(key, default)
    return _normalize_config(values)


def save_database_config(values) -> None:
    """Keep unencrypted maintenance settings local; public builds expose no maintenance setup."""
    if database_is_read_only():
        raise ValueError("Maintenance settings are unavailable in the public read-only distribution.")
    config = _normalize_config(values)
    path = database_configuration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def connect_database():
    """Keep connection call sites unchanged and add a read-only session for public builds."""
    connection = psycopg2.connect(**get_database_config())
    if database_is_read_only():
        try:
            connection.set_session(readonly=True)
        except Exception:
            connection.close()
            raise
    return connection


def configure_qgis_uri(uri) -> None:
    """Use the same selected profile for QGIS/PostGIS and psycopg2 connections."""
    config = get_database_config()
    uri.setConnection(
        str(config["host"]), str(config["port"]), str(config["dbname"]),
        str(config["user"]), str(config["password"]),
    )


def _configure_database() -> None:
    """Collect private settings without printing saved values or echoing passwords."""
    from getpass import getpass
    if database_is_read_only():
        raise ValueError("Database maintenance is available in the private distribution only.")
    path = database_configuration_path()
    saved = _read_config(path) if path.exists() else {}
    values = {}
    for key, label in (("host", "Database host"), ("port", "Database port"),
                       ("dbname", "Database name"), ("user", "Database user"),
                       ("connect_timeout", "Connection timeout in seconds")):
        entered = input(label + " (blank keeps the saved/default value): ").strip()
        values[key] = entered or saved.get(key, _FIELDS[key][1])
    values["password"] = getpass("Database password (blank keeps the saved value): ") or saved.get("password", "")
    save_database_config(values)
    print("Maintenance database settings saved outside the plugin source.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Configure local maintenance database access.")
    parser.add_argument("--configure", action="store_true")
    arguments = parser.parse_args()
    if arguments.configure:
        try:
            _configure_database()
        except (OSError, ValueError) as exc:
            parser.exit(1, str(exc) + "\n")
    else:
        parser.print_help()
