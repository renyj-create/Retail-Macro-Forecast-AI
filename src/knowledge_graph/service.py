"""Fixed read-only templates, dataset-scoped; no caller-supplied Cypher."""
import os
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Literal

DATASET='retail_demo_v1'
class QueryType(str,Enum):
    category='product_category'
    supplier='product_suppliers'
    store='store_products'
    promotion='promotion_details'
    neighbors='one_hop'
    two='two_hop'
    three='three_hop'
    path='path'
class GraphQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query_type: QueryType
    entity_id: str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')
    target_id: str | None=Field(default=None,pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')
    max_hops: int | None=Field(default=None,ge=1,le=3,strict=True)
    max_nodes: int=Field(default=100,ge=1,le=100,strict=True)
    max_relationships: int=Field(default=100,ge=1,le=100,strict=True)
    relationship_types: list[Literal['BELONGS_TO','SUPPLIES','STOCKS','FEATURES','APPLIES_TO']] | None=None
    labels: list[Literal['Product','Category','Supplier','Store','Promotion']] | None=None
    @model_validator(mode='after')
    def validate_mode(self):
        depths={'one_hop':1,'two_hop':2,'three_hop':3,'path':3}
        depth=depths.get(self.query_type)
        if depth and self.max_hops is not None and self.max_hops!=depth:
            if self.query_type!='path': raise ValueError('depth must match query mode')
        if self.query_type=='path' and not self.target_id: raise ValueError('target_id required')
        return self
    limit: int=Field(default=30,ge=1,le=100,strict=True)

ROOT='MATCH (n:RetailDemo {dataset_id:$dataset, id:$id, is_simulated:true}) RETURN properties(n) AS node'
PATTERNS={
 QueryType.category:'(n:Product)-[r:BELONGS_TO]->(m:Category)',
 QueryType.supplier:'(n:Product)<-[r:SUPPLIES]-(m:Supplier)',
 QueryType.store:'(n:Store)-[r:STOCKS]->(m:Product)',
 QueryType.promotion:'(n:Promotion)-[r:FEATURES|APPLIES_TO]->(m)',
 QueryType.neighbors:'(n)-[r:BELONGS_TO|SUPPLIES|STOCKS|FEATURES|APPLIES_TO]-(m)',
}
TEMPLATES={key:'MATCH '+pattern+' WHERE n:RetailDemo AND m:RetailDemo AND n.dataset_id=$dataset AND n.id=$id AND m.dataset_id=$dataset AND r.dataset_id=$dataset AND n.is_simulated=true AND m.is_simulated=true AND r.is_simulated=true RETURN properties(m) AS node, properties(r) AS edge, startNode(r).id AS source, endNode(r).id AS target, type(r) AS relation ORDER BY r.id LIMIT $limit' for key,pattern in PATTERNS.items()}
CATALOG='MATCH (n:RetailDemo {dataset_id:$dataset, is_simulated:true}) RETURN properties(n) AS node ORDER BY n.id LIMIT $limit'

LABELS=['Product','Category','Supplier','Store','Promotion']
RELATIONS=['BELONGS_TO','SUPPLIES','STOCKS','FEATURES','APPLIES_TO']
# Only server-owned integer depths enter these templates. All caller values are parameters.
MULTIHOP={depth: """MATCH p=(n:RetailDemo {dataset_id:$dataset,id:$id,is_simulated:true})
-[:BELONGS_TO|SUPPLIES|STOCKS|FEATURES|APPLIES_TO*1..DEPTH]-(m:RetailDemo)
WHERE ($target IS NULL OR m.id=$target)
AND all(v IN nodes(p) WHERE v:RetailDemo AND v.dataset_id=$dataset AND v.is_simulated=true
 AND v.entity_type IN $labels AND any(label IN labels(v) WHERE label IN $labels))
AND all(r IN relationships(p) WHERE r.dataset_id=$dataset AND r.is_simulated=true AND type(r) IN $relations)
AND all(v IN nodes(p) WHERE single(w IN nodes(p) WHERE w=v))
RETURN [v IN nodes(p) | properties(v)] AS nodes,
[r IN relationships(p) | r {.*, source:startNode(r).id,target:endNode(r).id,relation:type(r)}] AS relationships,
[v IN nodes(p) | v.id] AS node_ids, [r IN relationships(p) | r.id] AS relationship_ids,
length(p) AS hop_count
LIMIT $limit""".replace('DEPTH',str(depth)) for depth in (1,2,3)}

class GraphUnavailable(Exception):
    def __init__(self,code):self.code=code

class GraphService:
    def __init__(self,driver,database):self.driver=driver;self.database=database
    def read(self,query,params):
        # Access mode routes reads; DB account must ALSO be granted read-only rights.
        with self.driver.session(database=self.database,default_access_mode='READ') as session:
            from neo4j import unit_of_work
            @unit_of_work(timeout=5)
            def read_transaction(tx):
                return [record.data() for record in tx.run(query, **params)]
            return session.execute_read(read_transaction)
    def catalog(self,limit):
        rows=self.read(CATALOG,{'dataset':DATASET,'limit':limit+1})
        return {'nodes':[r['node'] for r in rows[:limit]],'edges':[],'truncated':len(rows)>limit}
    def multihop(self,request):
        params={'dataset':DATASET,'id':request.entity_id}
        root=self.read(ROOT,params)
        result={'nodes':[],'edges':[],'relationships':[],'paths':[],'hop_count':0,
                'source':'neo4j','dataset_id':DATASET,'is_simulated':True,'truncated':False,'entity_found':bool(root)}
        if not root:return result
        if request.query_type==QueryType.path:
            target=self.read(ROOT,dict(params,id=request.target_id))
            result['target_found']=bool(target)
            if not target:return result
        depth=request.max_hops or {QueryType.neighbors:1,QueryType.two:2,QueryType.three:3,QueryType.path:3}[request.query_type]
        params.update(target=request.target_id if request.query_type==QueryType.path else None,
                      labels=request.labels if request.labels is not None else LABELS,
                      relations=request.relationship_types if request.relationship_types is not None else RELATIONS,limit=2001)
        rows=self.read(MULTIHOP[depth],params)
        nodes={request.entity_id:root[0]['node']};edges={};seen=set()
        result['truncated']=len(rows)>2000
        for row in rows[:2000]:
            key=(tuple(row['node_ids']),tuple(row['relationship_ids']))
            if key in seen:continue
            seen.add(key)
            incoming_nodes={n['id']:n for n in row['nodes']}
            incoming_edges={e['id']:e for e in row['relationships']}
            if len(nodes.keys() | incoming_nodes.keys())>request.max_nodes or len(edges.keys() | incoming_edges.keys())>min(request.limit,request.max_relationships):
                result['truncated']=True;continue
            nodes.update(incoming_nodes);edges.update(incoming_edges)
            result['paths'].append({k:row[k] for k in ('node_ids','relationship_ids','hop_count')})
        result.update(nodes=list(nodes.values()),edges=list(edges.values()),relationships=list(edges.values()),
                      hop_count=max((p['hop_count'] for p in result['paths']),default=0))
        return result

    def query(self,request):
        if request.query_type in (QueryType.neighbors,QueryType.two,QueryType.three,QueryType.path):
            return self.multihop(request)

        root=self.read(ROOT,{'dataset':DATASET,'id':request.entity_id})
        if not root:return {'nodes':[],'edges':[],'truncated':False,'entity_found':False}
        expected={QueryType.category:'Product',QueryType.supplier:'Product',QueryType.store:'Store',QueryType.promotion:'Promotion'}
        if request.query_type in expected and root[0]['node'].get('entity_type')!=expected[request.query_type]:
            return {'nodes':[],'edges':[],'truncated':False,'entity_found':True,'type_mismatch':True}
        rows=self.read(TEMPLATES[request.query_type],{'dataset':DATASET,'id':request.entity_id,'limit':request.limit+1})
        nodes={request.entity_id:root[0]['node']};edges={}
        for row in rows[:request.limit]:
            nodes[row['node']['id']]=row['node'];edge=dict(row['edge']);edge.update(source=row['source'],target=row['target'],relation=row['relation']);edges[edge['id']]=edge
        return {'nodes':list(nodes.values()),'edges':list(edges.values()),'truncated':len(rows)>request.limit,'entity_found':True}

def get_graph_service():
    values=[os.getenv(k) for k in ('NEO4J_URI','NEO4J_USER','NEO4J_PASSWORD','NEO4J_DATABASE')]
    if not all(values):raise GraphUnavailable('not_configured')
    try:from neo4j import GraphDatabase
    except ImportError:raise GraphUnavailable('driver_missing') from None
    try:
        driver=GraphDatabase.driver(values[0],auth=(values[1],values[2]),connection_timeout=5,connection_acquisition_timeout=5,max_transaction_retry_time=0)
        yield GraphService(driver,values[3])
    except GraphUnavailable:raise
    finally:
        if 'driver' in locals():driver.close()
