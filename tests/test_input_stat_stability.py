"""Input access time is not a content mutation; replacement metadata still is."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_private_resume as fixtures

class InputStatStabilityTests(unittest.TestCase):
    def exercise(self, mutate_identity=False):
        helper = fixtures.PrivateResumeTests()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source=helper.source(root);work=root/'exports'
            inode=source.stat().st_ino;original=os.fstat;reads=0
            def observed(fd):
                nonlocal reads
                result=original(fd)
                if result.st_ino != inode:
                    return result
                reads+=1
                fields={k:getattr(result,k) for k in dir(result) if k.startswith('st_')}
                fields['st_atime']=result.st_atime+reads
                fields['st_atime_ns']=result.st_atime_ns+reads*1000000000
                if mutate_identity and reads%2==0:
                    fields['st_ino']+=1
                return SimpleNamespace(**fields)
            client=helper.client()
            with patch('os.fstat',side_effect=observed):
                rc,out,err=helper.invoke(source,work,client)
            return rc,out.getvalue(),err.getvalue(),client.calls

    def test_legitimate_read_access_time_change_does_not_reject_snapshot(self):
        rc,out,err,calls=self.exercise()
        self.assertEqual(rc,0,err)
        self.assertEqual(calls,12)
        self.assertTrue(json.loads(out)['complete'])

    def test_inode_change_still_rejects_snapshot_before_any_post(self):
        rc,out,err,calls=self.exercise(mutate_identity=True)
        self.assertEqual(rc,2)
        self.assertEqual(calls,0)
        self.assertIn('snapshot_integrity_failed',err)

if __name__=='__main__':unittest.main()
