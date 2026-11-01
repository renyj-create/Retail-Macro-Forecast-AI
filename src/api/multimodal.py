from fastapi import APIRouter, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from src.multimodal.image_validation import MAX_BYTES, ImageError, sanitize_image
from src.multimodal.vision_client import get_vision_client
from src.multimodal.service import analyze
from src.multimodal.schemas import AnalysisResponse

PATH='/api/v1/multimodal/analyze'
router=APIRouter()

class UploadBodyLimit:
    """Count bytes BEFORE multipart parsing, including chunked requests.

    Bounded buffer permits multipart overhead but never an unbounded UploadFile spool.
    """
    def __init__(self, app): self.app=app
    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or scope.get('path')!=PATH or scope.get('method')!='POST':
            return await self.app(scope,receive,send)
        body=bytearray()
        while True:
            event=await receive()
            if event['type']=='http.disconnect': return
            chunk=event.get('body',b'')
            if len(body)+len(chunk)>MAX_BYTES+65536:
                return await JSONResponse(status_code=413,content={'status':'failed','error_code':'request_too_large','message':'上传请求超限'})(scope,receive,send)
            body.extend(chunk)
            if not event.get('more_body',False): break
        sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True;return {'type':'http.request','body':bytes(body),'more_body':False}
            return await receive()
        await self.app(scope,replay,send)

@router.post(PATH, response_model=AnalysisResponse)
async def analyze_image(file: UploadFile=File(...), question: str=Form(...,min_length=1,max_length=2000), client=Depends(get_vision_client)):
    try:
        if not question.strip():
            return JSONResponse(status_code=422,content={'status':'failed','error_code':'invalid_question','message':'问题不能为空'})
        content=bytearray()
        while True:
            chunk=await file.read(65536)
            if not chunk: break
            content.extend(chunk)
            if len(content)>MAX_BYTES:
                raise ImageError('file_too_large','图片不能超过 5 MiB',413)
        image=await run_in_threadpool(sanitize_image,bytes(content),file.filename)
        return await run_in_threadpool(analyze,image,question,client)
    except ImageError as error:
        return JSONResponse(status_code=error.http_status,content={'status':'failed','error_code':error.code,'message':error.message})
    finally:
        await file.close()
