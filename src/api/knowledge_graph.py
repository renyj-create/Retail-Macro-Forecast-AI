import logging, re, traceback, uuid
from fastapi import APIRouter,Depends,Query
from fastapi.responses import JSONResponse
from src.knowledge_graph.service import GraphQuery,get_graph_service,GraphUnavailable,DATASET
router=APIRouter(prefix='/api/v1/graph',tags=['graph'])

def respond(action):
    try:
        data=action()
        return {'status':'empty' if not data['nodes'] else 'success','dataset_id':DATASET,'is_simulated':True,'source_type':'graph_query','data_nature':'simulated','data':data}
    except Exception as exc:
        # Do not log exception messages, parameters, credentials or traceback locals.
        diagnostic_id=uuid.uuid4().hex
        raw_code=str(getattr(exc,'code',''))
        code=raw_code if re.fullmatch(r'Neo\.[A-Za-z.]+',raw_code) else ''
        kind=type(exc).__name__
        lower=(kind+' '+code).lower()
        status=503
        if 'timeout' in lower or 'timedout' in lower:
            category='graph_query_timeout'; status=504
        elif 'security' in lower or 'auth' in lower:
            category='graph_authentication_failed'
        elif 'syntax' in lower or 'typeerror' in lower or 'statement' in lower:
            category='graph_statement_failed'
        elif kind in ('ServiceUnavailable','SessionExpired'):
            category='graph_connection_failed'
        elif kind in ('ValueError','TypeError','KeyError'):
            category='graph_execution_failed'
        else: category='graph_query_failed'
        frames=' > '.join(f'{frame.name}:{frame.lineno}' for frame in traceback.extract_tb(exc.__traceback__))
        logging.getLogger(__name__).error('graph_error diagnostic_id=%s category=%s exception_type=%s neo4j_code=%s frames=%s', diagnostic_id,category,kind,code,frames)
        return JSONResponse(status_code=status,content={'status':'unavailable','error_code':category,
            'diagnostic_id':diagnostic_id,'exception_type':kind,'neo4j_code':code,
            'message':'图谱查询失败，请根据诊断 ID 检查后端日志','is_simulated':True})

# Configuration errors must be handled outside the yield dependency as well.
def service_or_status():
    iterator=get_graph_service()
    try:
        try:service=next(iterator)
        except GraphUnavailable as exc:
            yield exc;return
        except Exception:
            yield GraphUnavailable('connection_failed');return
        yield service
    finally:iterator.close()

def unavailable(service):
    if isinstance(service,GraphUnavailable):
        return JSONResponse(status_code=503,content={'status':'not_configured' if service.code=='not_configured' else 'unavailable','error_code':service.code,'message':'图谱未配置或运行环境不可用','is_simulated':True})

@router.get('/entities')
def entities(limit:int=Query(30,ge=1,le=100),service=Depends(service_or_status)):
    error=unavailable(service)
    return error if error is not None else respond(lambda:service.catalog(limit))

@router.post('/query')
def query(body:GraphQuery,service=Depends(service_or_status)):
    error=unavailable(service)
    return error if error is not None else respond(lambda:service.query(body))
