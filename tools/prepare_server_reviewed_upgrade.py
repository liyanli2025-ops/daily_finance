"""Package source against an actual reviewed server snapshot, without installing.

This alternate entry accepts the user's reviewed server file snapshot instead of
guessing production from a Git ref or requiring the unavailable original v20 zip.
It never executes the application, tests, network calls or dependency installers.
"""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

BASE = "57e4f0a922a0293a6886726a8f0c2ef548308bcf"
FEATURE = "bd4e599d05f66861665a4902d41b869212d86ec5"
# These four matched the GitHub baseline in the user's server comparison.
CONFIRMED_BASE = {
    "backend/app/primary_discovery_check.py",
    "backend/app/services/model_usage.py",
    "backend/app/services/search_primary_collection.py",
    "tools/run_primary_collection_once.py",
}
EXTRAS = {
    "backend/app/services/search_objectives.py",
    "backend/requirements-extraction.txt",
    "docs/server_reviewed_upgrade_20261101.md",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalized_sha(data):
    return sha(data.replace(b"\r\n", b"\n"))


def child(root, name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Unsafe snapshot path")
    target = root.joinpath(*path.parts)
    # Do not consume symlinks from an uploaded archive.
    for count in range(1, len(path.parts) + 1):
        if root.joinpath(*path.parts[:count]).is_symlink():
            raise ValueError("Snapshot symlink: " + name)
    return target


def missing_imports(repo, files, installed):
    """Inspect local app imports; do not import or execute any app module."""
    missing = set()
    for name, data in files.items():
        if not name.startswith("backend/app/") or not name.endswith(".py"):
            continue
        package = name[:-3].split("/")[:-1]
        for node in ast.walk(ast.parse(data.decode("utf-8"), filename=name)):
            modules = []
            if isinstance(node, ast.ImportFrom):
                parent = package[:len(package) - node.level + 1] if node.level else []
                parts = parent + (node.module.split(".") if node.module else [])
                modules = [parts] + [parts + [alias.name] for alias in node.names]
            elif isinstance(node, ast.Import):
                modules = [alias.name.split(".") for alias in node.names]
            for parts in modules:
                if parts and parts[0] == "app":
                    parts = ["backend"] + parts
                dep = "/".join(parts) + ".py"
                if (dep.startswith("backend/app/") and child(repo, dep).is_file()
                        and dep not in installed and dep not in files):
                    missing.add(dep)
    return sorted(missing)


def prepare(snapshot, output):
    repo = Path(__file__).absolute().parent.parent
    snapshot = Path(snapshot).absolute()
    if snapshot.is_symlink():
        raise ValueError("Snapshot must be a regular directory")
    receipt_raw = child(snapshot, "SERVER-MANIFEST.json").read_bytes()
    receipt = json.loads(receipt_raw)
    git = lambda *args: subprocess.check_output(["git", "-C", str(repo), *args])
    if git("status", "--porcelain").strip():
        raise ValueError("Commit the reviewed source before packaging")
    revision = git("rev-parse", "HEAD").decode().strip()
    changed = set(git("diff", "--name-only", "-z", BASE, FEATURE).decode().split("\0")) - {""}
    # Tests stay in Git/source backup; production receives runtime and support files.
    names = sorted({n for n in changed if not n.startswith("backend/tests/")} | EXTRAS)
    payload, metadata = {}, {}
    for name, expected in receipt["files"].items():
        if sha(child(snapshot, name).read_bytes()) != expected:
            raise ValueError("Uploaded server file hash mismatch: " + name)
    for name in names:
        data = child(repo, name).read_bytes()
        additional = []
        if name in receipt["files"]:
            old = normalized_sha(child(snapshot, name).read_bytes())
            origin = "uploaded_server_file"
        elif name in CONFIRMED_BASE:
            old = normalized_sha(git("show", BASE + ":" + name))
            origin = "user_confirmed_baseline_match"
        elif name in receipt["missing"]:
            old = None
            origin = "user_confirmed_absent"
        elif name in EXTRAS:
            # New support files: only absent or byte-identical content is accepted.
            # Optional requirements may already equal the reviewed Git baseline.
            old = None
            prior = subprocess.run(["git", "-C", str(repo), "show", BASE + ":" + name],
                                   capture_output=True)
            if name == "backend/requirements-extraction.txt" and prior.returncode == 0:
                additional.append(normalized_sha(prior.stdout))
            origin = "absent_or_identical_only"
        else:
            raise ValueError("No reviewed server baseline: " + name)
        payload[name] = data
        metadata[name] = dict(old_sha256=old, new_sha256=normalized_sha(data),
                              raw_new_sha256=sha(data), baseline_origin=origin,
                              additional_old_sha256=additional)
    unresolved = missing_imports(repo, payload, set(receipt["python_files"]))
    if unresolved:
        raise ValueError("Missing app dependencies: " + ", ".join(unresolved))
    requirements = "backend/requirements.txt"
    plan = dict(settings={}, source_revision=revision, feature_revision=FEATURE,
                github_base_revision=BASE, server_snapshot_sha256=sha(receipt_raw),
                prerequisites={requirements: normalized_sha(child(snapshot, requirements).read_bytes())},
                files=metadata, tests_run=False, server_verified=False,
                dependencies_auto_installed=False, paid_requests=0,
                skill_interface_changed=False)
    output = Path(output)
    if output.exists():
        raise ValueError("Do not overwrite an existing release")
    output.parent.mkdir(parents=True, exist_ok=True)
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
    prefix = output.stem + "/"
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(prefix + "manifest.json", json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
        archive.writestr(prefix + "payload.zip", inner.getvalue())
        archive.writestr(prefix + "install_upgrade.py", child(repo, "tools/install_paused_upgrade.py").read_bytes())
        archive.writestr(prefix + "README.md", child(repo, "docs/server_reviewed_upgrade_20261101.md").read_bytes())
    with zipfile.ZipFile(output) as archive:
        with zipfile.ZipFile(io.BytesIO(archive.read(prefix + "payload.zip"))) as inner_archive:
            if set(inner_archive.namelist()) != set(payload):
                raise ValueError("Release inventory mismatch")
            for name, data in payload.items():
                if sha(inner_archive.read(name)) != sha(data):
                    raise ValueError("Release content mismatch: " + name)
    return dict(file=str(output), bytes=output.stat().st_size, sha256=sha(output.read_bytes()),
                source_revision=revision, files=len(payload), tests_run=False,
                server_deployed=False, model_requests=0, search_requests=0, tts_requests=0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.server_snapshot, args.output), ensure_ascii=False, indent=2))
