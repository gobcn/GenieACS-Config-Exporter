#!/usr/bin/env python3

import argparse
import os
import json
import yaml
from pymongo import MongoClient
from gridfs import GridFS


EXPORT_COLLECTIONS = [
    "config",
    "presets",
    "provisions",
    "virtualParameters",
    "permissions",
    "users",
    "files",
]


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def write_json(path, data):
    with open(path, "w", newline="\n") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def write_js(path, script):
    with open(path, "w", newline="\n") as f:
        f.write(script.strip() + "\n")


def extract_id(doc):
    _id = doc.get("_id")
    if _id is not None:
        return str(_id)
    return None


def clean_document(doc):
    doc.pop("_id", None)
    return doc


def insert_path(root, path_parts, value):
    current = root

    for i, part in enumerate(path_parts):
        is_last = i == len(path_parts) - 1

        # If numeric -> list index
        if part.isdigit():
            index = int(part)

            if not isinstance(current, list):
                # Convert dict placeholder to list if needed
                current_keys = list(current.keys())
                current.clear()
                current = []
                for _ in current_keys:
                    current.append({})

            # Expand list if necessary
            while len(current) <= index:
                current.append({})

            if is_last:
                current[index] = parse_value(value)
            else:
                if not isinstance(current[index], (dict, list)):
                    current[index] = {}
                current = current[index]

        else:
            if is_last:
                current[part] = parse_value(value)
            else:
                if part not in current:
                    # Decide next container type by looking ahead
                    next_part = path_parts[i + 1]
                    current[part] = [] if next_part.isdigit() else {}
                current = current[part]


def parse_value(value):
    # Values are stored like "'tags'" (quoted strings)
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1]
    return value


def export_config(db, output_dir):
    config_dir = os.path.join(output_dir, "config")
    ui_dir = os.path.join(output_dir, "ui")

    ensure_dir(config_dir)
    ensure_dir(ui_dir)

    docs = list(db.config.find())

    ui_data = {}

    for doc in docs:
        key = str(doc.get("_id"))
        value = doc.get("value")

        if key.startswith("ui."):
            parts = key.split(".")
            section = parts[1]
            path_parts = parts[2:]

            ui_data.setdefault(section, {})

            insert_path(ui_data[section], path_parts, value)
            continue

        # Non-UI config
        path = os.path.join(config_dir, f"{key}.json")
        write_json(path, {"value": value})

    # Dump YAML exactly as GenieACS expects
    for section, content in ui_data.items():
        path = os.path.join(ui_dir, f"{section}.yaml")

        with open(path, "w", newline="\n") as f:
            yaml.dump(content, f, sort_keys=False)


def export_standard_collection(db, collection_name, output_dir):
    out_dir = os.path.join(output_dir, collection_name)
    ensure_dir(out_dir)

    docs = list(db[collection_name].find())

    for doc in docs:
        doc_id = extract_id(doc)
        clean_document(doc)

        name = doc.get("name") or doc.get("username") or doc_id or "unnamed"
        path = os.path.join(out_dir, f"{name}.json")
        write_json(path, doc)


def export_users(db, output_dir):
    out_dir = os.path.join(output_dir, "users")
    ensure_dir(out_dir)

    docs = list(db.users.find())

    for doc in docs:
        doc_id = extract_id(doc)
        clean_document(doc)

        # Remove sensitive fields
        doc.pop("password", None)
        doc.pop("passwordHash", None)
        doc.pop("salt", None)

        username = doc.get("username") or doc_id or "unknown"
        path = os.path.join(out_dir, f"{username}.json")
        write_json(path, doc)


def export_provisions(db, output_dir):
    out_dir = os.path.join(output_dir, "provisions")
    ensure_dir(out_dir)

    docs = list(db.provisions.find())

    for doc in docs:
        doc_id = extract_id(doc)
        clean_document(doc)

        name = doc.get("name") or doc_id or "unnamed"
        script = doc.pop("script", "")

        js_path = os.path.join(out_dir, f"{name}.js")
        write_js(js_path, script)

        # Only write metadata if something remains
        if doc:
            meta_path = os.path.join(out_dir, f"{name}.meta.json")
            write_json(meta_path, doc)


def export_virtual_parameters(db, output_dir):
    out_dir = os.path.join(output_dir, "virtualParameters")
    ensure_dir(out_dir)

    docs = list(db.virtualParameters.find())

    for doc in docs:
        doc_id = extract_id(doc)
        clean_document(doc)

        name = doc.get("name") or doc_id or "unnamed"
        script = doc.pop("script", "")

        js_path = os.path.join(out_dir, f"{name}.js")
        write_js(js_path, script)

        # Only write metadata if something remains
        if doc:
            meta_path = os.path.join(out_dir, f"{name}.meta.json")
            write_json(meta_path, doc)


def export_files(db, output_dir):
    out_dir = os.path.join(output_dir, "files")
    ensure_dir(out_dir)

    fs = GridFS(db)

    docs = list(db["fs.files"].find())

    for doc in docs:
        doc_id = extract_id(doc)

        filename = doc.get("filename") or doc_id or "unnamed"

        # --- Export File Content ---
        grid_file = fs.find_one({"_id": doc["_id"]})
        if grid_file:
            file_path = os.path.join(out_dir, filename)

            with open(file_path, "wb") as f:
                f.write(grid_file.read())

        # --- Export Metadata ---
        metadata = doc.copy()
        clean_document(metadata)

        # Remove internal GridFS fields you likely don't need
        metadata.pop("chunkSize", None)
        metadata.pop("length", None)
        metadata.pop("uploadDate", None)

        meta_path = os.path.join(out_dir, f"{filename}.meta.json")
        write_json(meta_path, metadata)


def main():
    parser = argparse.ArgumentParser(description="GenieACS Config Exporter")
    parser.add_argument("--mongo-uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--database", default="genieacs", help="Database name")
    parser.add_argument("--output-dir", default="./genieacs-backup", help="Output directory")

    args = parser.parse_args()

    print("Connecting to MongoDB...")
    client = MongoClient(args.mongo_uri)
    db = client[args.database]

    print("Exporting GenieACS configuration...")

    export_config(db, args.output_dir)
    export_standard_collection(db, "presets", args.output_dir)
    export_provisions(db, args.output_dir)
    export_virtual_parameters(db, args.output_dir)
    export_standard_collection(db, "permissions", args.output_dir)
    export_users(db, args.output_dir)
    export_files(db, args.output_dir)

    print(f"Export complete → {args.output_dir}")


if __name__ == "__main__":
    main()
