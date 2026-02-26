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


def insert_path(root, parts, value):
    current = root
    parent = None
    parent_key = None

    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        next_part = parts[i + 1] if not is_last else None

        if part.isdigit():
            index = int(part)

            # If current is not list, convert it
            if not isinstance(current, list):
                new_list = []
                if parent is not None:
                    parent[parent_key] = new_list
                else:
                    # root replacement case
                    root.clear()
                    root.update({})
                    new_list = []
                    root = new_list
                current = new_list

            # Expand list
            while len(current) <= index:
                current.append({})

            if is_last:
                current[index] = value
            else:
                parent = current
                parent_key = index

                if not isinstance(current[index], (dict, list)):
                    current[index] = [] if next_part and next_part.isdigit() else {}
                current = current[index]

        else:
            if is_last:
                current[part] = value
            else:
                if part not in current:
                    current[part] = [] if next_part and next_part.isdigit() else {}

                parent = current
                parent_key = part
                current = current[part]


def sort_structure(obj):
    if isinstance(obj, dict):
        return {k: sort_structure(obj[k]) for k in sorted(obj.keys())}
    elif isinstance(obj, list):
        return [sort_structure(v) for v in obj]
    return obj


def export_config(db, output_dir):
    config_dir = os.path.join(output_dir, "config")
    ui_dir = os.path.join(output_dir, "ui")

    ensure_dir(config_dir)
    ensure_dir(ui_dir)

    docs = list(db.config.find())

    # Initialize as None so we can dynamically choose dict or list
    ui_documents = {
        "overview": None,
        "charts": None,
        "filters": None,
        "index": None,
        "device": None,
    }

    for doc in docs:
        key = str(doc.get("_id"))
        value = doc.get("value")

        # -----------------------------
        # Non-UI config
        # -----------------------------
        if not key.startswith("ui."):
            path = os.path.join(config_dir, f"{key}.json")
            write_json(path, {"value": value})
            continue

        parts = key.split(".")

        # -----------------------------
        # ui.overview.groups.*
        # -----------------------------
        if parts[1] == "overview":
            if len(parts) > 3 and parts[2] == "groups":
                if ui_documents["overview"] is None:
                    ui_documents["overview"] = {}
                insert_path(ui_documents["overview"], parts[3:], value)

            elif len(parts) > 3 and parts[2] == "charts":
                if ui_documents["charts"] is None:
                    ui_documents["charts"] = {}
                insert_path(ui_documents["charts"], parts[3:], value)

        # -----------------------------
        # ui.filters.*
        # -----------------------------
        elif parts[1] == "filters":
            if ui_documents["filters"] is None:
                ui_documents["filters"] = [] if parts[2].isdigit() else {}
            insert_path(ui_documents["filters"], parts[2:], value)

        # -----------------------------
        # ui.index.*
        # -----------------------------
        elif parts[1] == "index":
            if ui_documents["index"] is None:
                ui_documents["index"] = [] if parts[2].isdigit() else {}
            insert_path(ui_documents["index"], parts[2:], value)

        # -----------------------------
        # ui.device.*
        # -----------------------------
        elif parts[1] == "device":
            if ui_documents["device"] is None:
                ui_documents["device"] = [] if parts[2].isdigit() else {}
            insert_path(ui_documents["device"], parts[2:], value)

    # -----------------------------
    # Debug Output (optional)
    # -----------------------------
    print("UI document keys and types:")
    for name, content in ui_documents.items():
        print(name, type(content), content)

    # -----------------------------
    # Write YAML Files
    # -----------------------------
    for name, content in ui_documents.items():
        if content is not None:
            path = os.path.join(ui_dir, f"{name}.yaml")

            cleaned = sort_structure(content)

            with open(path, "w", newline="\n") as f:
                yaml.dump(
                    cleaned,
                    f,
                    sort_keys=False,   # we already sorted manually
                    default_flow_style=False
                )


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
