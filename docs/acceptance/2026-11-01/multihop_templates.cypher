// max_hops=1
MATCH p=(n:RetailDemo {dataset_id:$dataset,id:$id,is_simulated:true})
-[:BELONGS_TO|SUPPLIES|STOCKS|FEATURES|APPLIES_TO*1..1]-(m:RetailDemo)
WHERE ($target IS NULL OR m.id=$target)
AND all(v IN nodes(p) WHERE v:RetailDemo AND v.dataset_id=$dataset AND v.is_simulated=true
 AND v.entity_type IN $labels AND any(label IN labels(v) WHERE label IN $labels))
AND all(r IN relationships(p) WHERE r.dataset_id=$dataset AND r.is_simulated=true AND type(r) IN $relations)
AND all(v IN nodes(p) WHERE single(w IN nodes(p) WHERE w=v))
RETURN [v IN nodes(p) | properties(v)] AS nodes,
[r IN relationships(p) | r {.*, source:startNode(r).id,target:endNode(r).id,relation:type(r)}] AS relationships,
[v IN nodes(p) | v.id] AS node_ids, [r IN relationships(p) | r.id] AS relationship_ids,
length(p) AS hop_count
LIMIT $limit

// max_hops=2
MATCH p=(n:RetailDemo {dataset_id:$dataset,id:$id,is_simulated:true})
-[:BELONGS_TO|SUPPLIES|STOCKS|FEATURES|APPLIES_TO*1..2]-(m:RetailDemo)
WHERE ($target IS NULL OR m.id=$target)
AND all(v IN nodes(p) WHERE v:RetailDemo AND v.dataset_id=$dataset AND v.is_simulated=true
 AND v.entity_type IN $labels AND any(label IN labels(v) WHERE label IN $labels))
AND all(r IN relationships(p) WHERE r.dataset_id=$dataset AND r.is_simulated=true AND type(r) IN $relations)
AND all(v IN nodes(p) WHERE single(w IN nodes(p) WHERE w=v))
RETURN [v IN nodes(p) | properties(v)] AS nodes,
[r IN relationships(p) | r {.*, source:startNode(r).id,target:endNode(r).id,relation:type(r)}] AS relationships,
[v IN nodes(p) | v.id] AS node_ids, [r IN relationships(p) | r.id] AS relationship_ids,
length(p) AS hop_count
LIMIT $limit

// max_hops=3
MATCH p=(n:RetailDemo {dataset_id:$dataset,id:$id,is_simulated:true})
-[:BELONGS_TO|SUPPLIES|STOCKS|FEATURES|APPLIES_TO*1..3]-(m:RetailDemo)
WHERE ($target IS NULL OR m.id=$target)
AND all(v IN nodes(p) WHERE v:RetailDemo AND v.dataset_id=$dataset AND v.is_simulated=true
 AND v.entity_type IN $labels AND any(label IN labels(v) WHERE label IN $labels))
AND all(r IN relationships(p) WHERE r.dataset_id=$dataset AND r.is_simulated=true AND type(r) IN $relations)
AND all(v IN nodes(p) WHERE single(w IN nodes(p) WHERE w=v))
RETURN [v IN nodes(p) | properties(v)] AS nodes,
[r IN relationships(p) | r {.*, source:startNode(r).id,target:endNode(r).id,relation:type(r)}] AS relationships,
[v IN nodes(p) | v.id] AS node_ids, [r IN relationships(p) | r.id] AS relationship_ids,
length(p) AS hop_count
LIMIT $limit