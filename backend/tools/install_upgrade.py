"""Apply a prepared source bundle with a private backup and code rollback.

Default is read-only validation. Run with the deployment's virtualenv Python.
The sibling manifest.json and payload.zip are produced by the bundle builder.
"""
import argparse
import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from urllib.request import urlopen
import zipfile


def digest(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def destination(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise ValueError("Unsafe bundle path")
    target = root.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Bundle path escapes project")
    return target


def validate(root, manifest, archive):
    files = manifest["files"]
    if set(archive.namelist()) != set(files):
        raise RuntimeError("Bundle contents do not match manifest")
    for name, metadata in files.items():
        target = destination(root, name)
        data = archive.read(name)
        if digest(data) != metadata["new_sha256"]:
            raise RuntimeError("Bundle checksum mismatch: " + name)
        if name.endswith(".py"):
            ast.parse(data.decode("utf-8"), filename=name)
        current = digest(target.read_bytes()) if target.is_file() else None
        if current not in {metadata["old_sha256"], metadata["new_sha256"]}:
            raise RuntimeError("Server file differs from reviewed baseline: " + name)
    env = root / "backend/.env"
    if not env.is_file():
        raise RuntimeError("Existing deployment .env not found")


def merged_env(text, settings):
    # Keep unrelated settings and credentials; do not log the resulting text.
    remaining = dict(settings)
    output = []
    for line in text.splitlines():
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=", line)
        key = match.group(1) if match else None
        if key in settings:
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(output) + "\n"


def atomic_write(target, data, mode=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    original = target.stat() if target.exists() else None
    if mode is None:
        mode = (target.stat().st_mode & 0o777) if target.exists() else 0o644
    descriptor, temporary = tempfile.mkstemp(prefix=".finance-upgrade-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if original is not None and hasattr(os, "geteuid") and os.geteuid() == 0:
            os.chown(temporary, original.st_uid, original.st_gid)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def backup(root, names, backup_root):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = backup_root / stamp
    folder.mkdir(parents=True, mode=0o700)
    os.chmod(folder, 0o700)
    index = {}
    for name in list(names) + ["backend/.env"]:
        source = destination(root, name)
        index[name] = source.is_file()
        if source.is_file():
            target = destination(folder, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    # An online SQLite backup captures a consistent snapshot, including WAL data.
    from dotenv import dotenv_values
    cfg = dotenv_values(root / "backend/.env")
    db_url = cfg.get("DATABASE_URL") or "sqlite:///./data/database.db"
    if not db_url.startswith("sqlite:///"):
        raise RuntimeError("This deployment bundle requires an explicit external-database backup plan")
    db_name = db_url[len("sqlite:///"):]
    db_path = Path(db_name)
    if not db_path.is_absolute():
        db_path = root / "backend" / db_path
    if not db_path.is_file():
        raise RuntimeError("App database is missing; source upgrade has not been applied")
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(folder / "database.snapshot.db")) as target:
            source.backup(target)
    (folder / "restore-index.json").write_text(json.dumps(index), encoding="utf-8")
    return folder


def restore_code(root, folder):
    index = json.loads((folder / "restore-index.json").read_text(encoding="utf-8"))
    for name, existed in index.items():
        target = destination(root, name)
        if existed:
            original = destination(folder, name)
            atomic_write(target, original.read_bytes(), original.stat().st_mode & 0o777)
        elif target.is_file():
            # Only files recorded as newly introduced by this bundle are removed.
            target.unlink()
    # No schema migration is performed. Never overwrite a live database during code rollback.


def systemctl(action):
    subprocess.run(["systemctl", action, "finance-daily"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def require_managed_service():
    result = subprocess.run(
        ["systemctl", "show", "finance-daily", "-p", "ActiveState", "-p", "MainPID"],
        capture_output=True, text=True, check=True)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    pid = int(values.get("MainPID", "0"))
    if values.get("ActiveState") != "active" or pid <= 0:
        raise RuntimeError("finance-daily不是当前有效的托管服务，不能用--restart接管其他进程")
    return pid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path("/var/www/finance-daily"))
    parser.add_argument("--backup-root", type=Path, default=Path("/var/backups/finance-daily"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    root = args.project.resolve()
    bundle = Path(__file__).resolve().parent
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(bundle / "payload.zip") as archive:
        validate(root, manifest, archive)
        print("Source validation passed:", len(manifest["files"]), "files")
        print("Runtime profile: Ofox mirror, Claude Sonnet 5.5, Anthropic Messages")
        if not args.apply:
            print("Validation only. No files or service state changed.")
            return
        if args.restart:
            # A healthy port alone can belong to a manually launched old server.
            require_managed_service()
        folder = backup(root, manifest["files"], args.backup_root.resolve())
        print("Private backup:", folder)
        stopped = False
        try:
            if args.restart:
                systemctl("stop")
                stopped = True
            for name in manifest["files"]:
                atomic_write(destination(root, name), archive.read(name))
            env_file = root / "backend/.env"
            updated = merged_env(env_file.read_text(encoding="utf-8"), manifest["settings"])
            # Preserve the existing service account's access; backups are private.
            atomic_write(env_file, updated.encode("utf-8"))
            if args.restart:
                systemctl("start")
                for attempt in range(30):
                    try:
                        pid = require_managed_service()
                        with urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
                            health = json.load(response)
                        if (require_managed_service() == pid and health.get("status") == "healthy"
                                and health.get("database") == "connected"):
                            print("Service health and database connection verified")
                            break
                    except Exception:
                        pass
                    time.sleep(1)
                else:
                    raise RuntimeError("Upgraded service did not become healthy")
            print("Upgrade applied. Real news collection and podcast acceptance remain to be run.")
        except Exception:
            if stopped:
                try:
                    systemctl("stop")
                except Exception:
                    pass
            restore_code(root, folder)
            if stopped:
                systemctl("start")
            raise RuntimeError("Upgrade failed; original code and configuration restored") from None


if __name__ == "__main__":
    main()
