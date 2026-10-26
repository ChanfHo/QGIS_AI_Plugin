"""Build a deterministic plugin ZIP from an explicit reviewed file list."""
import argparse
import ast
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import zipfile


def build(output):
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "release-files.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    release_date = date.fromisoformat(manifest["release_date"])
    from configparser import ConfigParser
    metadata = ConfigParser()
    metadata.read(root / "metadata.txt", encoding="utf-8")
    if metadata["general"]["version"] != manifest["version"] or manifest["plugin_directory"] != "qgis_ai":
        raise ValueError("Release version or plugin directory mismatch")
    if len(files) != len(set(files)):
        raise ValueError("Duplicate release paths")
    payloads = {}
    for name in files:
        original = root / name
        path = original.resolve()
        if root not in path.parents or not path.is_file() or original.is_symlink():
            raise ValueError(f"Invalid release path: {name}")
        if path.name in {"database.private.json", "database_private.json", "style_knowledge_tools.py", "database_setup.sql", ".pgpass", "pgpass.conf"} or path.suffix == ".dpapi" or path.name.startswith((".env", "database.local.")):
            raise ValueError(f"Private settings or maintenance tooling: {name}")
        if any(part in {".git", "__pycache__", "tests", ".idea", ".vscode"} for part in Path(name).parts):
            raise ValueError(f"Development artifact: {name}")
        data = path.read_bytes()
        if path.suffix in {".py", ".json", ".txt", ".md", ".csv", ".sql", ".geojson", ".ui", ".ts", ".qrc"}:
            if data.startswith(b"\xef\xbb\xbf"):
                raise ValueError(f"UTF-8 BOM: {name}")
            text = data.decode("utf-8")
            if "\ufffd" in text:
                raise ValueError(f"Replacement character: {name}")
            if re.search(r"sk-[A-Za-z0-9]{20,}|[A-Za-z]:[/\\]+Users[/\\]|postgres(?:ql)?://[^\s]+:[^\s]+@", text):
                raise ValueError(f"Possible credential or personal path: {name}")
            if path.suffix == ".py":
                ast.parse(text, filename=name)
        payloads[name] = data
    public = json.loads(payloads["config/database_public.json"].decode("utf-8"))
    if public.get("read_only") is not True or public.get("user") != "qgis_ai_public_reader":
        raise ValueError("The package must use the approved public-reader profile")
    database = ast.parse(payloads["data/database.py"].decode("utf-8"))
    fields = next(node.value for node in database.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "_FIELDS" for target in node.targets))
    defaults = ast.literal_eval(fields)
    if any(defaults[key][1] != "" for key in ("host", "user", "password")):
        raise ValueError("Private connection defaults must not be embedded in source")
    for node in ast.walk(database):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "getenv" and node.args:
            if isinstance(node.args[0], ast.Constant) and node.args[0].value in {"QGIS_AI_DB_HOST", "QGIS_AI_DB_USER", "QGIS_AI_DB_PASSWORD"}:
                if len(node.args) != 2 or not isinstance(node.args[1], ast.Constant) or node.args[1].value != "":
                    raise ValueError("Private database defaults must not be packaged")
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f'qgis_ai-{manifest["version"]}.zip'
    hashes = {}
    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payloads.items()):
            info = zipfile.ZipInfo("qgis_ai/" + name, (release_date.year, release_date.month, release_date.day, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
            hashes[name] = hashlib.sha256(data).hexdigest()
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (output / (artifact.name + ".sha256")).write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
    (output / (artifact.stem + ".manifest.json")).write_text(json.dumps({"version": manifest["version"], "sha256": digest, "files": hashes}, indent=2) + "\n", encoding="utf-8")
    print(f"Built {artifact.name}: {len(files)} files; SHA-256 {digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output.resolve())
