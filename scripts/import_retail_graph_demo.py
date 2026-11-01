"""Explicit admin-only import; never run automatically on API startup."""
import os,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.knowledge_graph.service import DATASET

def load_dataset():
    return json.loads((ROOT/'data/graph_demo/retail_demo.json').read_text(encoding='utf8'))

def import_dataset(driver,database,data):
    labels={'Product','Category','Supplier','Store','Promotion'}
    relations={'BELONGS_TO','SUPPLIES','STOCKS','FEATURES','APPLIES_TO'}
    nodes=data['nodes'];edges=data['edges'];ids={n['id'] for n in nodes}
    if len(ids)!=len(nodes) or len({e['id'] for e in edges})!=len(edges):raise ValueError('duplicate dataset ids')
    for row in nodes+edges:
        if row.get('dataset_id')!=DATASET or row.get('is_simulated') is not True:raise ValueError('simulation provenance missing')
    for n in nodes:
        if n['entity_type'] not in labels:raise ValueError('invalid label')
    for e in edges:
        if e['relation'] not in relations or e['source'] not in ids or e['target'] not in ids:raise ValueError('invalid relation')
    with driver.session(database=database) as s:
        s.run('CREATE CONSTRAINT retail_demo_identity IF NOT EXISTS FOR (n:RetailDemo) REQUIRE (n.dataset_id,n.id) IS UNIQUE').consume()
        def write(tx):
            for n in nodes:
                tx.run('MERGE (n:RetailDemo:'+n['entity_type']+' {dataset_id:$dataset,id:$id}) SET n += $properties',dataset=DATASET,id=n['id'],properties=n).consume()
            for e in edges:
                tx.run('MATCH (a:RetailDemo {dataset_id:$dataset,id:$source}), (b:RetailDemo {dataset_id:$dataset,id:$target}) MERGE (a)-[r:'+e['relation']+' {dataset_id:$dataset,id:$id}]->(b) SET r.is_simulated=true',dataset=DATASET,source=e['source'],target=e['target'],id=e['id']).consume()
        s.execute_write(write)

if __name__=='__main__':
    from neo4j import GraphDatabase
    keys=('NEO4J_URI','NEO4J_IMPORT_USER','NEO4J_IMPORT_PASSWORD','NEO4J_DATABASE')
    config=[os.getenv(k) for k in keys]
    if not all(config):raise SystemExit('Missing dedicated importer configuration; nothing imported')
    try:
        with GraphDatabase.driver(config[0],auth=(config[1],config[2]),connection_timeout=5) as driver:import_dataset(driver,config[3],load_dataset())
    except Exception:raise SystemExit('Import failed; inspect local Neo4j diagnostics, no credentials printed') from None
    print('Imported simulated retail_demo_v1 dataset')
