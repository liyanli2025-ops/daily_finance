import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('pause_installer',Path(__file__).resolve().parents[2]/'tools/pause_finance_automation.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class PauseInstallTests(unittest.TestCase):
    def fixture(self,root):
        old=b'pass\n';new=b'paused = True\npass\n'
        name='backend/app/main.py';target=root/name;target.parent.mkdir(parents=True);target.write_bytes(old)
        info=dict(before=hashlib.sha256(old).hexdigest(),after=hashlib.sha256(new).hexdigest(),edits=[(0,0,'paused = True\n')])
        return name,target,info,new

    def test_backup_atomic_patch_persistent_flag_and_repeat_preserve_env_and_db(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'finance-daily';name,target,info,new=self.fixture(root)
            env=root/'backend/.env';env.write_text('do not read or change secrets')
            db=root/'backend/data/database.db';db.parent.mkdir();db.write_bytes(b'keep app data')
            other=Path(folder)/'other-project';other.mkdir();(other/'keep').write_text('keep')
            first=module.pause(root,Path(folder)/'backups',{name:info})
            self.assertEqual((first/name).read_bytes(),b'pass\n');self.assertEqual(target.read_bytes(),new)
            flag=root/'backend/data/.automation-paused';self.assertTrue(flag.exists())
            module.pause(root,Path(folder)/'backups',{name:info})
            self.assertTrue(flag.exists());self.assertEqual(target.read_bytes(),new)
            self.assertEqual(env.read_text(),'do not read or change secrets');self.assertEqual(db.read_bytes(),b'keep app data')
            self.assertEqual((other/'keep').read_text(),'keep')

    def test_unknown_source_is_not_overwritten_or_partially_applied(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'finance';name,target,info,new=self.fixture(root)
            another=root/'backend/app/unknown.py';another.write_bytes(b'unknown\n')
            with self.assertRaisesRegex(RuntimeError,'Source differs'):
                module.pause(root,Path(folder)/'backups',{name:info,'backend/app/unknown.py':info})
            self.assertEqual(target.read_bytes(),b'pass\n');self.assertEqual(another.read_bytes(),b'unknown\n')
            self.assertFalse((root/'backend/data/.automation-paused').exists())
