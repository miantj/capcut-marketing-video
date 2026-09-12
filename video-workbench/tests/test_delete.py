import tempfile,unittest
from pathlib import Path
from workbench.store import Store

class DeleteTests(unittest.TestCase):
 def test_delete_excludes_queue_and_keeps_revision_files(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp));job=s.create({'title':'delete test'});key=job['id']
   self.assertEqual(s.delete(key),'busy')
   s.update(key,'queued','queued',0)
   child=s.create({},key,2)
   asset=Path(tmp)/'jobs'/key/'uploads'/'keep.txt';asset.write_text('keep')
   self.assertEqual(s.delete(key),'deleted');self.assertIsNone(s.claim());self.assertIsNone(s.get(key))
   self.assertEqual([j['id'] for j in s.list()],[child['id']]);self.assertFalse(asset.parent.parent.exists());self.assertTrue((Path(tmp)/'jobs'/child['id']).exists())
   self.assertEqual(s.delete(key),'missing')
 def test_processing_cannot_be_deleted(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp));key=s.create({})['id'];s.update(key,'queued','queued',0)
   self.assertEqual(s.claim(),key);self.assertEqual(s.delete(key),'busy');self.assertEqual(s.get(key)['status'],'processing')

if __name__=='__main__':unittest.main()
