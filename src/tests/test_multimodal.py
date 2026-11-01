"""Offline only: fake adapters never invoke SDK or network."""
import asyncio
import io
import json
import unittest
from unittest.mock import patch
from PIL import Image, PngImagePlugin
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api.multimodal import router, UploadBodyLimit, PATH
from src.multimodal.image_validation import sanitize_image, ImageError, MAX_BYTES
from src.multimodal.vision_client import MockVisionClient, VisionTimeout, get_vision_client, CompatibleVisionClient
from src.multimodal.service import analyze


def picture(fmt='PNG', size=(12,10)):
    stream=io.BytesIO();Image.new('RGB',size,'white').save(stream,format=fmt);return stream.getvalue()

def output(fields=None):
    return json.dumps({'document_type':'operating_report','fields': fields if fields is not None else [
        {'name':'date','raw_text':'2026-10-29','unit':None},
        {'name':'revenue','raw_text':'12.50','unit':'万元'}]})

class FakeReal(MockVisionClient):
    provider='fake_real_transport_no_network';is_mock=False

class BrokenClient(FakeReal):
    def extract(self,*args): raise RuntimeError('sensitive/internal/path')

class TimeoutClient(FakeReal):
    def extract(self,*args): raise VisionTimeout()

class TestImages(unittest.TestCase):
    def test_png_jpeg(self):
        for fmt,ext in [('PNG','png'),('JPEG','jpg')]:
            image=sanitize_image(picture(fmt),'image.'+ext)
            self.assertEqual((image.width,image.height,image.mime),(12,10,'image/png'))
    def test_mismatch(self):
        with self.assertRaises(ImageError) as caught: sanitize_image(picture(),'fake.jpg')
        self.assertEqual(caught.exception.code,'format_mismatch')
    def test_corrupt(self):
        for data in [b'not image',picture()[:30]]:
            with self.assertRaises(ImageError): sanitize_image(data,'a.png')
    def test_size(self):
        with self.assertRaises(ImageError) as caught: sanitize_image(b'x'*(MAX_BYTES+1),'a.png')
        self.assertEqual(caught.exception.code,'file_too_large')
    def test_pixels(self):
        with self.assertRaises(ImageError) as caught: sanitize_image(picture(size=(4001,4000)),'a.png')
        self.assertEqual(caught.exception.code,'pixel_limit')
    def test_metadata_removed(self):
        stream=io.BytesIO();meta=PngImagePlugin.PngInfo();meta.add_text('private','secret')
        Image.new('RGB',(4,4)).save(stream,format='PNG',pnginfo=meta)
        clean=sanitize_image(stream.getvalue(),'a.png')
        self.assertNotIn('private',Image.open(io.BytesIO(clean.content)).info)
    def test_transparency_composited_white(self):
        stream=io.BytesIO();Image.new('RGBA',(2,2),(0,0,0,0)).save(stream,format='PNG')
        clean=sanitize_image(stream.getvalue(),'a.png')
        self.assertEqual(Image.open(io.BytesIO(clean.content)).getpixel((0,0)),(255,255,255))

    def test_unsupported(self):
        with self.assertRaises(ImageError): sanitize_image(picture('GIF'),'a.png')

class TestExtraction(unittest.TestCase):
    def setUp(self): self.image=sanitize_image(picture(),'a.png')
    def test_no_configuration(self):
        with patch.dict('os.environ',{'VISION_ENABLED':'false'}): self.assertIsNone(get_vision_client())
        result=analyze(self.image,'q',None)
        self.assertEqual(result.status,'not_configured');self.assertFalse(result.report)
    def test_mock_real_distinction(self):
        for client,status,nature in [(MockVisionClient(output()),'mock','simulated'),(FakeReal(output()),'success','user_uploaded_unverified')]:
            r=analyze(self.image,'q',client);self.assertEqual(r.status,status)
            self.assertEqual(r.evidence.data_nature,nature);self.assertEqual(r.report_status,'template')
            self.assertEqual(r.fields[1].normalized_value,'125000.00')
    def test_invalid_json_schema(self):
        for raw in ['not json','{"a":1}',output().replace('12.50','NaN')+'broken']:
            self.assertEqual(analyze(self.image,'q',FakeReal(raw)).error_code,'invalid_model_output')
    def test_timeout(self):
        self.assertEqual(analyze(self.image,'q',TimeoutClient('')).error_code,'vision_timeout')
    def test_service_failure_redacted(self):
        r=analyze(self.image,'q',BrokenClient(''))
        self.assertEqual(r.error_code,'vision_service_error');self.assertNotIn('sensitive',r.model_dump_json())
    def test_invalid_values(self):
        for value,unit,name,code in [('NaN','元','revenue','nonfinite_number'),('Infinity','元','revenue','nonfinite_number'),
                ('2026-02-30',None,'date','invalid_date'),('2','%','revenue','unit_invalid'),
                ('20','元','margin_pct','unit_invalid'),('101','%','margin_pct','out_of_range')]:
            with self.subTest(value=value,name=name):
                r=analyze(self.image,'q',FakeReal(output([{'name':name,'raw_text':value,'unit':unit}])))
                self.assertEqual(r.status,'needs_review');self.assertIn(code,[x.code for x in r.issues])
                self.assertIsNone(r.fields[0].normalized_value)
    def test_missing_not_zero(self):
        r=analyze(self.image,'q',FakeReal(output([])))
        self.assertTrue(all(f.normalized_value is None for f in r.fields))
        self.assertEqual(len(r.issues),2)
    def test_sdk_adapter_request_without_network(self):
        from types import SimpleNamespace
        with patch('openai.OpenAI') as sdk:
            sdk.return_value.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=output()))])
            client=CompatibleVisionClient('test-placeholder','https://vision.invalid/v1','test-vision')
            r=analyze(self.image,'检查收入',client)
            self.assertEqual(r.status,'success')
            args=sdk.return_value.chat.completions.create.call_args.kwargs
            self.assertEqual(args['model'],'test-vision')
            self.assertTrue(args['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))
            self.assertEqual(sdk.call_args.kwargs['max_retries'],0)

    def test_duplicate_unknown(self):
        r=analyze(self.image,'q',FakeReal(output([{'name':'other','raw_text':'1','unit':'元'},
             {'name':'date','raw_text':'2026-10-29'}, {'name':'date','raw_text':'2026-10-29'}])))
        self.assertIn('duplicate_field',[i.code for i in r.issues]);self.assertIn('unknown_field',[i.code for i in r.issues])

class TestMultimodalAPI(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI();self.app.include_router(router);self.app.add_middleware(UploadBodyLimit)
        self.app.dependency_overrides[get_vision_client]=lambda:None
        self.client=TestClient(self.app)
    def post(self, data=None, filename='a.png'):
        return self.client.post(PATH,files={'file':(filename,picture() if data is None else data,'image/png')},data={'question':'检查收入'})
    def test_multipart_not_configured(self):
        r=self.post();self.assertEqual(r.status_code,200);self.assertEqual(r.json()['status'],'not_configured')
    def test_api_mock(self):
        self.app.dependency_overrides[get_vision_client]=lambda:MockVisionClient(output())
        r=self.post();self.assertEqual(r.json()['status'],'mock');self.assertTrue(r.json()['is_mock'])
    def test_api_model_failures(self):
        for adapter,code in [(TimeoutClient(''),'vision_timeout'),(BrokenClient(''),'vision_service_error'),(FakeReal('bad'),'invalid_model_output')]:
            self.app.dependency_overrides[get_vision_client]=lambda adapter=adapter:adapter
            response=self.post()
            self.assertEqual(response.json()['status'],'failed')
            self.assertEqual(response.json()['error_code'],code)

    def test_api_invalid_image(self):
        r=self.post(b'bad');self.assertEqual(r.status_code,422);self.assertEqual(r.json()['error_code'],'decode_failed')
    def test_api_mismatch(self): self.assertEqual(self.post(filename='a.jpg').status_code,415)
    def test_api_over_file_limit(self): self.assertEqual(self.post(b'x'*(MAX_BYTES+1)).status_code,413)
    def test_missing_question(self):
        r=self.client.post(PATH,files={'file':('a.png',picture())});self.assertEqual(r.status_code,422)
    def test_chunked_body_stops_early(self):
        async def check():
            calls=0;sent=[]
            async def receive():
                nonlocal calls
                calls+=1;return {'type':'http.request','body':b'x'*65536,'more_body':True}
            async def send(message): sent.append(message)
            async def forbidden(*args): self.fail('oversized body reached parser')
            await UploadBodyLimit(forbidden)({'type':'http','path':PATH,'method':'POST'},receive,send)
            self.assertEqual(sent[0]['status'],413);self.assertLess(calls,100)
        asyncio.run(check())
    def test_existing_api_registration(self):
        # Existing app is only imported; its agent/model is never invoked here.
        from src.api.main import app, QueryRequest
        self.assertIn('/api/v1/analyze',list(app.openapi()['paths']))
        self.assertIn(PATH,list(app.openapi()['paths']))
        self.assertEqual(QueryRequest(query='q').image_base64,'')
        self.assertEqual(TestClient(app).get('/health').status_code,200)
        app.dependency_overrides[get_vision_client]=lambda:None
        try:
            response=TestClient(app).post(PATH, files={'file':('a.png',picture(),'image/png')},data={'question':'检查截图'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['status'],'not_configured')
        finally:
            app.dependency_overrides.pop(get_vision_client,None)

if __name__=='__main__': unittest.main()
