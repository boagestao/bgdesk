#!/usr/bin/env python3
"""Record macOS packaging checkpoints and decide how a later run resumes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

STAGES = ("compiled", "signed", "notarized", "stapled", "validated")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(directory):
    path = Path(directory) / "checkpoint.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def save(directory, checkpoint):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "checkpoint.json.tmp"
    temporary.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n")
    temporary.replace(directory / "checkpoint.json")


def advance(checkpoint, stage):
    if stage not in STAGES:
        raise ValueError(f"Unknown checkpoint stage: {stage}")
    current = checkpoint.get("stage")
    if current not in STAGES or STAGES.index(stage) >= STAGES.index(current):
        checkpoint["stage"] = stage


def ensure(directory, version, edition, arch, origin):
    checkpoint = load(directory)
    for key, value in (("version", version), ("edition", edition), ("arch", arch), ("origin", origin)):
        if value:
            checkpoint[key] = value
    save(directory, checkpoint)
    return checkpoint


def add_file(directory, name, stage):
    path = Path(directory) / name
    if not path.is_file():
        raise ValueError(f"Checkpoint file is missing: {name}")
    checkpoint = load(directory)
    checkpoint.setdefault("files", {})[name] = {"sha256": sha256(path), "size": path.stat().st_size}
    advance(checkpoint, stage)
    save(directory, checkpoint)
    return checkpoint


def record_notarization(directory, submission_id, status, stage):
    checkpoint = load(directory)
    checkpoint["notarization"] = {"id": submission_id, "status": status}
    advance(checkpoint, stage)
    save(directory, checkpoint)
    return checkpoint


def verify_file(directory, name):
    directory = Path(directory)
    checkpoint = load(directory)
    meta = checkpoint.get("files", {}).get(name)
    path = directory / name
    if not meta or not path.is_file():
        raise ValueError(f"Checkpoint is missing {name}")
    if sha256(path) != meta["sha256"] or path.stat().st_size != meta["size"]:
        raise ValueError(f"Checkpoint hash mismatch: {name}")
    return path


def notarization_action(checkpoint):
    """Return submit, wait, or staple. An accepted submission is never uploaded again."""
    record = checkpoint.get("notarization") or {}
    status = record.get("status")
    if record.get("id") and status == "Accepted":
        return "staple"
    if record.get("id") and status == "In Progress":
        return "wait"
    return "submit"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    ensure_cmd = sub.add_parser("ensure")
    ensure_cmd.add_argument("--version", default="")
    ensure_cmd.add_argument("--edition", default="")
    ensure_cmd.add_argument("--arch", default="")
    ensure_cmd.add_argument("--origin", default="")
    add = sub.add_parser("add-file")
    add.add_argument("--name", required=True)
    add.add_argument("--stage", required=True)
    notarized = sub.add_parser("notarization")
    notarized.add_argument("--id", required=True)
    notarized.add_argument("--status", required=True)
    notarized.add_argument("--stage", default="notarized")
    verify = sub.add_parser("verify")
    verify.add_argument("--name", required=True)
    sub.add_parser("action")
    field = sub.add_parser("field")
    field.add_argument("--key", required=True)
    args = parser.parse_args()
    if args.command == "ensure":
        ensure(args.dir, args.version, args.edition, args.arch, args.origin)
    elif args.command == "add-file":
        add_file(args.dir, args.name, args.stage)
    elif args.command == "notarization":
        record_notarization(args.dir, args.id, args.status, args.stage)
    elif args.command == "verify":
        verify_file(args.dir, args.name)
    elif args.command == "action":
        print(notarization_action(load(args.dir)))
    elif args.command == "field":
        value = load(args.dir)
        for part in args.key.split("."):
            value = value.get(part, "") if isinstance(value, dict) else ""
        if not value:
            raise SystemExit(f"Checkpoint has no {args.key}")
        print(value)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
