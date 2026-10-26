"""Build plugin-scoped Qt catalogs from the shared message resource.

Usage: python scripts/build_translations.py --lrelease /path/to/lrelease
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


def build(lrelease=None):
    root = Path(__file__).resolve().parents[1]
    messages = json.loads((root / "i18n/messages.json").read_text(encoding="utf-8"))
    for language in ("en", "zh"):
        tree = ET.Element("TS", version="2.1", language="zh_CN" if language == "zh" else "en_US", sourcelanguage="en_US")
        for name in ("QGISAIMapper", "qgis_aiDockWidgetBase", "qgis_ai"):
            context = ET.SubElement(tree, "context")
            ET.SubElement(context, "name").text = name
            for english, chinese in sorted(messages.items()):
                message = ET.SubElement(context, "message")
                ET.SubElement(message, "source").text = english
                ET.SubElement(message, "translation").text = chinese if language == "zh" else english
        ET.indent(tree, space="  ")
        path = root / "i18n" / f"qgis_ai_{language}.ts"
        ET.ElementTree(tree).write(path, encoding="utf-8", xml_declaration=True)
        if lrelease:
            subprocess.run([lrelease, str(path), "-qm", str(path.with_suffix(".qm"))], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lrelease", default=shutil.which("lrelease"))
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args()
    if not args.lrelease and not args.source_only:
        parser.error("lrelease was not found; supply --lrelease")
    build(None if args.source_only else args.lrelease)
