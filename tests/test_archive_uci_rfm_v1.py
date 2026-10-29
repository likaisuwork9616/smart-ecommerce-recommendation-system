"""Synthetic archive safety/integrity checks; all scratch files remain in shop."""
import hashlib
import json
import struct
from pathlib import Path
import unittest
import uuid
import zipfile

from scripts import archive_uci_rfm_v1 as a


class ArchiveTests(unittest.TestCase):
    def scratch(self):
        p=a.inside(a.ROOT,a.VERIFY+'/synthetic/'+uuid.uuid4().hex);p.mkdir(parents=True);return p

    def fixture(self):
        root=self.scratch();(root/'docs').mkdir();(root/'docs/test.md').write_text('合成研究資料\n',encoding='utf-8')
        d=dict(a.descriptor(root,'docs/test.md'),live_role='frozen_research_source')
        return root,{'release_id':'synthetic','files':[d]}

    def test_archive_all_members_CRC_SHA_readback(self):
        root,manifest=self.fixture();path=root/'test.zip';a.pack(root,path,manifest)
        restored,receipt=a.inspect_archive(path,hashlib.sha256(a.encoded(manifest)).hexdigest())
        self.assertEqual(restored,manifest);self.assertEqual(receipt['payload_files'],1)
        self.assertTrue(receipt['all_payload_CRC_and_SHA256_passed'])

    def test_archive_has_original_utf8_bytes(self):
        root,m=self.fixture();path=root/'test.zip';a.pack(root,path,m)
        with zipfile.ZipFile(path) as z:self.assertEqual(z.read('docs/test.md'),(root/'docs/test.md').read_bytes())

    def test_source_mutation_rejected(self):
        root,m=self.fixture();(root/'docs/test.md').write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError):a.pack(root,root/'test.zip',m)

    def test_no_overwrite_archive(self):
        root,m=self.fixture();path=root/'test.zip';a.pack(root,path,m);before=path.read_bytes()
        with self.assertRaises(FileExistsError):a.pack(root,path,m)
        self.assertEqual(path.read_bytes(),before)

    def test_unsafe_member_paths_rejected(self):
        for name in ['../outside','/absolute','C:/outside','folder\\outside','a/../b','a//b','./file']:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):a.safe_name(name)

    def test_archive_member_manifest_mismatch_rejected(self):
        root,m=self.fixture();path=root/'bad.zip'
        with zipfile.ZipFile(path,'x') as z:z.writestr(a.MANIFEST_MEMBER,a.encoded(m));z.writestr('wrong.txt','x')
        with self.assertRaises(ValueError):a.inspect_archive(path)

    def test_valid_CRC_but_wrong_payload_hash_rejected(self):
        root,m=self.fixture();path=root/'bad.zip'
        with zipfile.ZipFile(path,'x') as z:z.writestr(a.MANIFEST_MEMBER,a.encoded(m));z.writestr('docs/test.md','different')
        with self.assertRaises(ValueError):a.inspect_archive(path)

    def test_manifest_hash_change_rejected(self):
        root,m=self.fixture();path=root/'test.zip';a.pack(root,path,m)
        with self.assertRaises(ValueError):a.inspect_archive(path,'0'*64)

    def test_corrupt_payload_CRC_rejected(self):
        root,m=self.fixture();path=root/'bad_crc.zip'
        with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_STORED) as z:
            z.writestr(a.MANIFEST_MEMBER,a.encoded(m));z.writestr('docs/test.md',(root/'docs/test.md').read_bytes())
            offset=z.getinfo('docs/test.md').header_offset
        raw=bytearray(path.read_bytes());name_len,extra_len=struct.unpack_from('<HH',raw,offset+26)
        raw[offset+30+name_len+extra_len]^=1;path.write_bytes(raw)
        with self.assertRaises(zipfile.BadZipFile):a.inspect_archive(path)

    def test_source_hash_or_size_change_rejected(self):
        root,m=self.fixture();bad=dict(m['files'][0],bytes=0)
        with self.assertRaises(ValueError):a.assert_descriptor(root,bad)

    def test_conflicting_descriptors_rejected(self):
        root,m=self.fixture();d=m['files'][0]
        with self.assertRaises(ValueError):a.normalize([d,dict(d,sha256='0'*64)])

    def test_identical_source_descriptors_deduplicated(self):
        root,m=self.fixture();d=m['files'][0]
        self.assertEqual(len(a.normalize([d,d])),1)

    def test_partial_release_preserved_not_replayed(self):
        root=self.scratch();a.inside(root,a.PRIVATE).mkdir(parents=True)
        with self.assertRaises(FileExistsError):a.archive_release(root)
        self.assertFalse(a.inside(root,a.REPORT).exists())


if __name__=='__main__':unittest.main()
