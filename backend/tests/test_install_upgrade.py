import io
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from tools.install_upgrade import atomic_write, backup, digest, merged_env, require_managed_service, restore_code, validate


class DeploymentTests(unittest.TestCase):
    def test_failed_systemd_unit_cannot_restart_a_manual_server(self):
        with patch("tools.install_upgrade.subprocess.run", return_value=SimpleNamespace(
                stdout="MainPID=0\nActiveState=failed\n")):
            with self.assertRaisesRegex(RuntimeError, "不是当前有效"):
                require_managed_service()

    def test_active_systemd_unit_requires_positive_pid(self):
        with patch("tools.install_upgrade.subprocess.run", return_value=SimpleNamespace(
                stdout="MainPID=123\nActiveState=active\n")):
            self.assertEqual(require_managed_service(), 123)

    def test_atomic_write_preserves_existing_file_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".env"
            target.write_text("old", encoding="utf-8")
            target.chmod(0o640)
            previous = target.stat().st_mode & 0o777
            atomic_write(target, b"new")
            self.assertEqual(target.stat().st_mode & 0o777, previous)
            self.assertEqual(target.read_bytes(), b"new")

    def test_config_merge_keeps_credentials_and_other_settings(self):
        text = "OPENAI_API_KEY=test-secret\nAI_MODEL=old\nexport AI_MODEL=duplicate\nCUSTOM_SETTING=yes\n"
        result = merged_env(text, {"AI_MODEL": "new", "OPENAI_BASE_URL": "https://api.ofox.io/v1"})
        self.assertIn("OPENAI_API_KEY=test-secret", result)
        self.assertIn("CUSTOM_SETTING=yes", result)
        self.assertEqual(result.count("AI_MODEL="), 1)
        self.assertIn("AI_MODEL=new", result)

    def test_changed_server_file_blocks_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backend").mkdir()
            (root / "backend/.env").write_text("", encoding="utf-8")
            (root / "backend/code.py").write_text("custom = True\n", encoding="utf-8")
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("backend/code.py", "updated = True\n")
            manifest = {"files": {"backend/code.py": {
                "old_sha256": digest(b"original = True\n"),
                "new_sha256": digest(b"updated = True\n")}}}
            with zipfile.ZipFile(stream) as archive, self.assertRaisesRegex(RuntimeError, "differs"):
                validate(root, manifest, archive)
            self.assertEqual((root / "backend/code.py").read_text(), "custom = True\n")

    def test_private_backup_and_code_rollback_preserve_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            (root / "backend/data").mkdir(parents=True)
            (root / "backend/.env").write_text("OPENAI_API_KEY=test-secret\n", encoding="utf-8")
            (root / "backend/code.py").write_text("old = True\n", encoding="utf-8")
            db = root / "backend/data/database.db"
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute("CREATE TABLE stocks(code TEXT)")
                connection.execute("INSERT INTO stocks VALUES ('002714')")
            folder = backup(root, ["backend/code.py", "backend/new.py"], Path(tmp) / "backups")
            (root / "backend/code.py").write_text("new = True\n", encoding="utf-8")
            (root / "backend/new.py").write_text("introduced = True\n", encoding="utf-8")
            (root / "backend/.env").write_text("changed\n", encoding="utf-8")
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute("INSERT INTO stocks VALUES ('600900')")
            restore_code(root, folder)
            self.assertIn("old", (root / "backend/code.py").read_text())
            self.assertFalse((root / "backend/new.py").exists())
            self.assertIn("test-secret", (root / "backend/.env").read_text())
            with closing(sqlite3.connect(folder / "database.snapshot.db")) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM stocks").fetchone()[0], 1)
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM stocks").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
