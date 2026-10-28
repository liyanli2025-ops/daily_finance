from contextlib import closing
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('runtime_bundle',Path(__file__).resolve().parents[2]/'tools/prepare_editorial_runtime.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class RuntimeBundleTests(unittest.TestCase):
    def fixture(self,folder):
        import hashlib
        source=Path(folder)/'source.zip';payload=BytesIO()
        files={'backend/app/a.py':b'pass\n','backend/tests/existing.py':b'test version\n'}
        manifest=dict(settings={},files={key:dict(old_sha256='old',new_sha256='new') for key in files})
        with zipfile.ZipFile(payload,'w') as archive:
            for key,value in files.items():archive.writestr(key,value)
        with zipfile.ZipFile(source,'w') as archive:
            archive.writestr(module.PREFIX+'payload.zip',payload.getvalue())
            archive.writestr(module.PREFIX+'manifest.json',json.dumps(manifest))
            archive.writestr(module.PREFIX+'install_upgrade.py',b'pass\n')
        return source,hashlib.sha256(source.read_bytes()).hexdigest(),manifest

    def test_only_tests_are_omitted_and_runtime_hashes_installer_source_are_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            source,digest,original_manifest=self.fixture(folder);original=source.read_bytes()
            output=module.prepare(source,Path(folder)/'runtime',digest)
            manifest=json.loads((output/'manifest.json').read_text())
            self.assertEqual(manifest['files'],{'backend/app/a.py':original_manifest['files']['backend/app/a.py']})
            with zipfile.ZipFile(output/'payload.zip') as archive:
                self.assertEqual(archive.namelist(),['backend/app/a.py'])
                self.assertEqual(archive.read('backend/app/a.py'),b'pass\n')
            self.assertEqual((output/'install_upgrade.py').read_bytes(),b'pass\n')
            self.assertEqual(source.read_bytes(),original)

    def test_wrong_source_or_nonempty_output_cannot_be_overridden(self):
        with tempfile.TemporaryDirectory() as folder:
            source,digest,_=self.fixture(folder)
            with self.assertRaises(RuntimeError):module.prepare(source,Path(folder)/'not_created','wrong')
            self.assertFalse((Path(folder)/'not_created').exists())
            output=Path(folder)/'occupied';output.mkdir();(output/'keep').write_text('keep')
            with self.assertRaises(RuntimeError):module.prepare(source,output,digest)
            self.assertEqual((output/'keep').read_text(),'keep')
