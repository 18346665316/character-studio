"""Production invariants: arbitrary material seams, connectivity, provenance, resume."""
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asset_repository import atomic, read
from terrain import (digest, compile_kit, decode_image, execute, periodic, prepare, road_mask,
                     seam_report, validate, material_variants, natural_mask, variant_at)
from terrain_images import generate_materials, Provider, SubmissionRejected


def encoded(image):
    stream = BytesIO(); image.save(stream, format='PNG')
    return base64.b64encode(stream.getvalue()).decode()


class TerrainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = dict(title='测试套件', description='手绘草地和泥土道路', mode='import',
                         tile_size=64, road_width=.5)

    def random_image(self, seed=1):
        return Image.fromarray(np.random.default_rng(seed).integers(0,256,(117,89,3),dtype='uint8'))

    def test_arbitrary_materials_and_all_widths_match_every_legal_neighbor(self):
        for size in (32,64,128):
            for width in (.25,.35,.5,.65):
                with self.subTest(size=size,width=width):
                    ground=periodic(self.random_image(),size)
                    road=periodic(self.random_image(2),size)
                    tiles=[Image.composite(road,ground,road_mask(size,bits,width)) for bits in range(16)]
                    self.assertEqual(seam_report(tiles)['max_channel_difference'],0)
                    self.assertEqual(seam_report(tiles)['matching_edge_pairs'],256)

    def test_masks_have_only_the_requested_exits(self):
        for bits in range(16):
            mask=np.array(road_mask(64,bits,.65))
            for bit,edge in [(1,mask[0]),(2,mask[:,-1]),(4,mask[-1]),(8,mask[:,0])]:
                self.assertEqual(bool(edge.max()),bool(bits&bit))
            self.assertEqual(int(mask[32,32]),255)

    def test_local_sampling_preserves_features_lost_by_whole_image_reduction(self):
        stripes=np.tile(((np.arange(1024)//8)%2*180+35).astype('uint8'),(1024,1))
        image=Image.fromarray(np.repeat(stripes[:,:,None],3,axis=2))
        whole=np.array(periodic(image,64))[12:-12,12:-12]
        local=np.array(material_variants(image,64)[0])[12:-12,12:-12]
        self.assertGreater(local.std(),whole.std()*3+20)

    def test_natural_variants_keep_exits_and_transparent_layers_compatible(self):
        for size in (32,64,128):
            ground=material_variants(self.random_image(),size)
            road=material_variants(self.random_image(2),size)
            for width in (.25,.65):
                all_masks=[];all_tiles=[]
                for v in range(4):
                    masks=[natural_mask(size,b,width,ground[v],v) for b in range(16)]
                    all_masks.append([np.array(m) for m in masks])
                    all_tiles.append([np.array(Image.composite(road[v],ground[v],m)) for m in masks])
                    for bits,m in enumerate(masks):
                        mask=np.array(m)
                        for bit,edge in [(1,mask[0]),(2,mask[:,-1]),(4,mask[-1]),(8,mask[:,0])]:
                            self.assertEqual(bool(edge.max()),bool(bits&bit))
                for v in range(4):
                    for w in range(4):
                        for b in range(16):
                            self.assertTrue(np.array_equal(all_tiles[v][b][0],all_tiles[w][b][0]))
                            self.assertTrue(np.array_equal(all_tiles[v][b][:,-1],all_tiles[w][b][:,-1]))
                            self.assertTrue(np.array_equal(all_masks[v][b][0],all_masks[w][b][0]))
                        for a in range(16):
                            for b in range(16):
                                if bool(a&2)==bool(b&8):
                                    self.assertTrue(np.array_equal(all_tiles[v][a][:,-1],all_tiles[w][b][:,0]))
                                if bool(a&4)==bool(b&1):
                                    self.assertTrue(np.array_equal(all_tiles[v][a][-1],all_tiles[w][b][0]))

    def test_reuse_compiles_new_version_without_calling_image_provider(self):
        source=prepare(self.root,{**self.spec,'mode':'demo','finish':'classic'})
        execute(self.root,source['id'])
        original=self.root/'terrain-kits'/source['id']
        before=(original/'kit.zip').read_bytes()
        job=prepare(self.root,{**self.spec,'mode':'reuse','source_kit':source['id']})
        with patch('terrain_images.generate_materials',side_effect=AssertionError('Unexpected charge')):
            execute(self.root,job['id'])
        manifest=read(self.root/'terrain-kits'/job['id']/'manifest.json')
        self.assertEqual(manifest['source_kit'],source['id'])
        self.assertEqual(len(manifest['variants']),4)
        self.assertEqual(manifest['validation']['matching_edge_pairs'],4096)
        self.assertEqual(manifest['source_sha256'],read(original/'manifest.json')['source_sha256'])
        self.assertEqual((original/'kit.zip').read_bytes(),before)
        (original/'inputs/ground.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'发生变化'):
            prepare(self.root,{**self.spec,'mode':'reuse','source_kit':source['id']})

    def test_invalid_specs_and_images_rejected(self):
        for changes in [dict(tile_size=True),dict(tile_size=4096),dict(road_width=float('nan')),
                        dict(mode='unknown'),dict(title=' '),dict(description='',mode='ai')]:
            with self.assertRaises(ValueError): validate({**self.spec,**changes})
        for content in [None,'not base64',encoded(Image.new('RGB',(8,8))),
                        encoded(Image.new('RGBA',(64,64),(0,0,0,0)))]:
            with self.assertRaises(ValueError): decode_image(content)

    def test_import_without_ai_inputs_preserves_source_and_never_generates(self):
        data={**self.spec,'asset_type':'material','ground':encoded(self.random_image())}
        data.pop('description')
        with patch('terrain_images.generate_materials',side_effect=AssertionError('Unexpected charge')):
            job=prepare(self.root,data)
            execute(self.root,job['id'])
        manifest=read(self.root/'terrain-kits'/job['id']/'manifest.json')
        self.assertEqual(manifest['mode'],'import')
        self.assertEqual(manifest['description'],'')
        self.assertNotIn('reference.png',manifest['source_sha256'])
        self.assertEqual(manifest['source_sha256']['ground.png'],
                         digest(self.root/'.local/terrain/jobs'/job['id']/'inputs/ground.png'))

    def test_import_is_immutable_and_zip_contains_rules_sources_and_layers(self):
        data={**self.spec,'ground':encoded(self.random_image()),'road':encoded(self.random_image(2)),
              'reference':encoded(self.random_image(3))}
        job=prepare(self.root,data); execute(self.root,job['id'])
        folder=self.root/'terrain-kits'/job['id']
        manifest=read(folder/'manifest.json')
        self.assertEqual(manifest['id'],job['id'])
        self.assertEqual(len(manifest['tiles']),16)
        self.assertEqual(manifest['art_review'],'pending')
        self.assertEqual(len(manifest['source_sha256']),3)
        self.assertEqual(read(self.root/'.local/terrain/jobs'/job['id']/'job.json')['status'],'complete')
        with zipfile.ZipFile(folder/'kit.zip') as archive:
            self.assertEqual(json.loads(archive.read('manifest.json')),manifest)
            self.assertIn('overlays/road_15.png',archive.namelist())
            self.assertIn('inputs/reference.png',archive.namelist())
            self.assertNotIn('job.json',archive.namelist())
        snapshot=(folder/'kit.zip').read_bytes()
        execute(self.root,job['id'])
        self.assertEqual((folder/'kit.zip').read_bytes(),snapshot)

    def test_failure_does_not_publish_partial_kit(self):
        data={**self.spec,'mode':'demo'}
        job=prepare(self.root,data)
        with patch('terrain.compile_kit',side_effect=ValueError('bad seam')):
            execute(self.root,job['id'])
        self.assertFalse((self.root/'terrain-kits'/job['id']).exists())
        self.assertEqual(read(self.root/'.local/terrain/jobs'/job['id']/'job.json')['status'],'failed')

    def test_symlink_output_boundary_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root/'terrain-kits').symlink_to(outside,target_is_directory=True)
            job=prepare(self.root,{**self.spec,'mode':'demo'}); execute(self.root,job['id'])
            self.assertFalse(list(Path(outside).iterdir()))

    def ai_folder(self):
        folder=self.root/'job'; (folder/'inputs').mkdir(parents=True)
        Image.new('RGB',(64,64),'green').save(folder/'inputs/reference.png')
        return folder

    def test_async_generation_uses_reference_then_ground_and_resumes_without_new_calls(self):
        folder=self.ai_folder(); blob=base64.b64decode(encoded(self.random_image()))
        with patch('terrain_images.Provider') as provider:
            client=provider.return_value; client.base='https://example.com/v1'
            client.create.side_effect=[{'id':'ground-task'},{'id':'road-task'}]
            client.request.side_effect=[{'status':'completed'},blob,{'status':'completed'},blob]
            generate_materials(folder,self.spec,lambda _:None)
            self.assertEqual([p.name for p in client.create.call_args_list[0].args[1]],['reference.png'])
            self.assertEqual([p.name for p in client.create.call_args_list[1].args[1]],['reference.png','ground.png'])
            generate_materials(folder,self.spec,lambda _:None)
            self.assertEqual(client.create.call_count,2)
            self.assertEqual(client.request.call_count,4)

    def test_connection_loss_reuses_saved_task_id(self):
        folder=self.ai_folder(); blob=base64.b64decode(encoded(self.random_image()))
        with patch('terrain_images.Provider') as provider:
            client=provider.return_value; client.base='https://example.com/v1'
            client.create.return_value={'id':'saved-task'}
            client.request.side_effect=ValueError('connection lost')
            with self.assertRaises(ValueError): generate_materials(folder,self.spec,lambda _:None)
            self.assertEqual(read(folder/'generation.json')['ground']['remote_id'],'saved-task')
            client.request.side_effect=[{'status':'completed'},blob,{'status':'completed'},blob]
            generate_materials(folder,self.spec,lambda _:None)
            self.assertEqual(client.create.call_count,2) # existing ground + only new road

    def test_uncertain_submission_cannot_silently_charge_again(self):
        folder=self.ai_folder()
        with patch('terrain_images.Provider') as provider:
            client=provider.return_value; client.base='https://example.com/v1'
            client.create.side_effect=ValueError('timeout before ID')
            with self.assertRaises(ValueError): generate_materials(folder,self.spec,lambda _:None)
            with self.assertRaisesRegex(ValueError,'可能已扣费'): generate_materials(folder,self.spec,lambda _:None)
            self.assertEqual(client.create.call_count,1)

    def test_terminal_failure_retries_only_failed_material_on_continuation(self):
        folder=self.ai_folder();blob=base64.b64decode(encoded(self.random_image()))
        with patch('terrain_images.Provider') as provider:
            client=provider.return_value;client.base='https://example.com/v1'
            client.create.side_effect=[{'id':'good-ground'},{'id':'failed-road'},{'id':'retry-road'}]
            client.request.side_effect=[{'status':'completed'},blob,{'status':'failed'}]
            with self.assertRaisesRegex(ValueError,'可能产生费用'):
                generate_materials(folder,self.spec,lambda _:None)
            self.assertEqual(client.create.call_count,2)
            self.assertEqual(read(folder/'generation.json')['road']['remote_status'],'failed')
            client.request.side_effect=[{'status':'completed'},blob]
            generate_materials(folder,self.spec,lambda _:None)
            self.assertEqual(client.create.call_count,3)
            receipt=read(folder/'generation.json')
            self.assertEqual(receipt['ground']['remote_id'],'good-ground')
            self.assertEqual(receipt['road']['failed_attempts'],[{'remote_id':'failed-road','status':'failed'}])
            self.assertEqual(receipt['road']['remote_id'],'retry-road')

    def test_definite_rejection_can_be_retried(self):
        folder=self.ai_folder()
        with patch('terrain_images.Provider') as provider:
            client=provider.return_value; client.base='https://example.com/v1'
            client.create.side_effect=SubmissionRejected('HTTP 403')
            with self.assertRaises(SubmissionRejected): generate_materials(folder,self.spec,lambda _:None)
            self.assertNotIn('submission_uncertain',read(folder/'generation.json')['ground'])

    def test_single_ai_material_makes_only_one_image_call(self):
        folder=self.ai_folder();blob=base64.b64decode(encoded(self.random_image()))
        with patch('terrain_images.Provider') as provider:
            client=provider.return_value;client.base='https://example.com/v1'
            client.create.return_value={'id':'water-task'}
            client.request.side_effect=[{'status':'completed'},blob]
            generate_materials(folder,{**self.spec,'asset_type':'material'},lambda _:None)
            self.assertEqual(client.create.call_count,1)
            self.assertTrue((folder/'inputs/ground.png').is_file())
            self.assertFalse((folder/'inputs/road.png').exists())


if __name__ == '__main__': unittest.main()
