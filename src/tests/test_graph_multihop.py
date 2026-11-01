"""Supplemental offline contract tests; never substitutes for Neo4j integration."""
import unittest
from unittest.mock import Mock, MagicMock
from pydantic import ValidationError
from src.knowledge_graph.service import GraphQuery, GraphService, MULTIHOP, DATASET

class MultihopTests(unittest.TestCase):
 def test_validation(self):
  for changes in [dict(max_hops=0),dict(max_hops=4),dict(max_nodes=101),dict(max_relationships=101),dict(labels=['Unknown']),dict(relationship_types=['DELETE']),dict(query_type='path'),dict(max_hops=2),dict(dataset_id='other')]:
   with self.subTest(changes=changes),self.assertRaises(ValidationError):
    GraphQuery(**(dict(query_type='one_hop',entity_id='P001')|changes))
 def test_templates(self):
  for depth,template in MULTIHOP.items():
   self.assertIn(f'*1..{depth}',template)
   for clause in ['single(w IN nodes(p)', 'r.dataset_id=$dataset','v.dataset_id=$dataset','r.is_simulated=true','v.is_simulated=true','startNode(r).id','endNode(r).id','LIMIT $limit']:
    self.assertIn(clause,template)
 def test_caps_and_dedup(self):
  node=lambda id:dict(id=id,dataset_id=DATASET,is_simulated=True)
  row=dict(nodes=[node('P001'),node('S001')],relationships=[dict(id='R003',source='S001',target='P001')],node_ids=['P001','S001'],relationship_ids=['R003'],hop_count=1)
  for cap in [1,2]:
   service=GraphService(None,'neo4j');service.read=Mock(side_effect=[[dict(node=node('P001'))],[row,row]])
   result=service.query(GraphQuery(query_type='two_hop',entity_id='P001',max_nodes=cap))
   self.assertEqual(len(result['nodes']),cap)
   self.assertEqual(len(result['paths']),cap-1)
   self.assertEqual(result['truncated'],cap==1)

 def test_managed_transaction_timeout_and_plain_query(self):
  driver=MagicMock();session=driver.session.return_value.__enter__.return_value
  tx=Mock();tx.run.return_value=[]
  def execute(work):
   self.assertEqual(work.timeout,5)
   return work(tx)
  session.execute_read.side_effect=execute
  self.assertEqual(GraphService(driver,'neo4j').read('RETURN $value',{'value':1}),[])
  tx.run.assert_called_once_with('RETURN $value',value=1)

 def test_error_classification_redacts_message(self):
  from src.api.knowledge_graph import respond
  class StatementFailure(Exception):
   code='Neo.ClientError.Statement.TypeError'
  def fail():raise StatementFailure('secret password and image base64')
  with self.assertLogs('src.api.knowledge_graph',level='ERROR') as logs:
   response=respond(fail)
  self.assertEqual(response.status_code,503)
  self.assertIn(b'graph_statement_failed',response.body)
  self.assertNotIn('secret',' '.join(logs.output))
  self.assertNotIn(b'secret',response.body)
 def test_relationship_projection(self):
  for template in MULTIHOP.values():
   self.assertIn('r {.*, source:',template)
   self.assertNotIn('properties(r) +',template)
