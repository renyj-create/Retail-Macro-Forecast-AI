"""Offline protocol tests. Integration requires explicit opt-in and a running Neo4j."""
import os,unittest
from unittest.mock import Mock,patch
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.knowledge_graph.service import GraphQuery,GraphService,GraphUnavailable,TEMPLATES,DATASET
from src.api.knowledge_graph import router,service_or_status
from scripts.import_retail_graph_demo import load_dataset,import_dataset

class GraphTests(unittest.TestCase):
 def test_dataset_provenance(self):
  data=load_dataset()
  self.assertEqual(len({n['id'] for n in data['nodes']}),len(data['nodes']))
  self.assertEqual({n['entity_type'] for n in data['nodes']},{'Product','Category','Supplier','Store','Promotion'})
  self.assertTrue(all(x['is_simulated'] and x['dataset_id']==DATASET for x in data['nodes']+data['edges']))
 def test_invalid_contract(self):
  for extra in [{'query_type':'MATCH (n) RETURN n'},{'entity_id':"P001' DELETE n"},{'limit':101},{'limit':0},{'limit':1.5},{'cypher':'x'}]:
   args=dict(query_type='one_hop',entity_id='P001',limit=10);args.update(extra)
   with self.subTest(args=args),self.assertRaises(ValidationError):GraphQuery(**args)
 def test_unknown_and_truncated(self):
  service=GraphService(None,'test');service.read=Mock(return_value=[])
  self.assertFalse(service.query(GraphQuery(query_type='one_hop',entity_id='P001'))['entity_found'])
  data=load_dataset();root=data['nodes'][0];target=data['nodes'][2]
  row={'nodes':[root,target],'relationships':[dict(data['edges'][0],source='P001',target='C001',relation='BELONGS_TO')],'node_ids':['P001','C001'],'relationship_ids':['R001'],'hop_count':1}
  service.read=Mock(side_effect=[[{'node':root}],[row,row]])
  result=service.query(GraphQuery(query_type='one_hop',entity_id='P001',limit=1))
  self.assertFalse(result['truncated']);self.assertEqual(len(result['edges']),1)
  query,params=service.read.call_args.args
  self.assertIn('$id',query);self.assertNotIn('P001',query);self.assertEqual(params['id'],'P001');self.assertEqual(params['limit'],2001)
 def test_read_mode_and_templates(self):
  driver=Mock();driver.session.return_value.__enter__=Mock(return_value=Mock());driver.session.return_value.__exit__=Mock()
  GraphService(driver,'test').read('RETURN 1',{})
  self.assertEqual(driver.session.call_args.kwargs['default_access_mode'],'READ')
  for query in TEMPLATES.values():
   self.assertIn('LIMIT $limit',query);self.assertIn('r.is_simulated=true',query)
   self.assertNotIn('DELETE',query)
 def test_import_uses_merge_and_rejects_invalid(self):
  data=load_dataset();driver=Mock();session=Mock();driver.session.return_value.__enter__=Mock(return_value=session);driver.session.return_value.__exit__=Mock()
  tx=Mock();session.execute_write.side_effect=lambda f:f(tx)
  import_dataset(driver,'test',data)
  self.assertEqual(tx.run.call_count,len(data['nodes'])+len(data['edges']))
  self.assertTrue(all('MERGE' in call.args[0] for call in tx.run.call_args_list))
  data['edges'][0]['relation']='DELETE'
  with self.assertRaises(ValueError):import_dataset(driver,'test',data)
 def test_api_states_and_validation(self):
  app=FastAPI();app.include_router(router)
  app.dependency_overrides[service_or_status]=lambda:GraphUnavailable('not_configured')
  client=TestClient(app)
  self.assertEqual(client.get('/api/v1/graph/entities').json()['status'],'not_configured')
  self.assertEqual(client.get('/api/v1/graph/entities?limit=101').status_code,422)
  self.assertEqual(client.post('/api/v1/graph/query',json={'query_type':'arbitrary','entity_id':'P001'}).status_code,422)
  service=Mock();service.query.return_value={'nodes':[],'edges':[],'entity_found':False,'truncated':False}
  app.dependency_overrides[service_or_status]=lambda:service
  response=client.post('/api/v1/graph/query',json={'query_type':'one_hop','entity_id':'UNKNOWN'})
  self.assertEqual(response.json()['status'],'empty')
  service.query.side_effect=RuntimeError('secret internal path')
  response=client.post('/api/v1/graph/query',json={'query_type':'one_hop','entity_id':'P001'})
  self.assertEqual(response.status_code,503);self.assertNotIn('secret',response.text)

@unittest.skipUnless(os.getenv('ENABLE_GRAPH_INTEGRATION')=='true','Neo4j integration not enabled; not a passing integration result')
class RealNeo4jTests(unittest.TestCase):
 def test_read_only_multihop(self):
  from neo4j import GraphDatabase
  config=[os.environ[k] for k in ('NEO4J_URI','NEO4J_USER','NEO4J_PASSWORD','NEO4J_DATABASE')]
  with GraphDatabase.driver(config[0],auth=(config[1],config[2])) as driver:
   service=GraphService(driver,config[3])
   for mode,root,expected in [('one_hop','T001',{'T001','P001','P002','M001'}),('two_hop','T001',{'T001','P001','P002','M001','C001','S001'}),('three_hop','P001',{'T001','P001','P002','M001','C001','S001'})]:
    result=service.query(GraphQuery(query_type=mode,entity_id=root,limit=100))
    self.assertEqual({n['id'] for n in result['nodes']},expected)
    self.assertTrue(all(n['dataset_id']==DATASET and n['is_simulated'] for n in result['nodes']+result['edges']))
    self.assertEqual(len(result['nodes']),len(expected))
    for path in result['paths']:self.assertEqual(len(path['node_ids']),len(set(path['node_ids'])))
    for edge in result['edges']:
     if edge['id']=='R003':self.assertEqual((edge['source'],edge['target']),('S001','P001'))
   result=service.query(GraphQuery(query_type='path',entity_id='T001',target_id='C001'))
   self.assertIn(['T001','P001','C001'],[p['node_ids'] for p in result['paths']])
   for field,value in [('max_nodes',1),('max_relationships',1)]:
    result=service.query(GraphQuery(query_type='three_hop',entity_id='P001',**{field:value}))
    self.assertLessEqual(len(result['nodes'] if field=='max_nodes' else result['edges']),value)
   self.assertFalse(service.query(GraphQuery(query_type='one_hop',entity_id='UNKNOWN'))['entity_found'])
   self.assertFalse(service.query(GraphQuery(query_type='path',entity_id='P001',target_id='UNKNOWN'))['target_found'])
