<template>
  <section>
    <h1>零售知识图谱</h1>
    <el-alert title="独立模拟数据 · 仅表示关联关系，不是真实经营事实，不能用于推断促销收益或流失概率" type="warning" :closable="false" />
    <el-button :loading="busy" @click="load">加载图谱实体</el-button>
    <el-select v-model="entityId" placeholder="选择后端返回的实体"><el-option v-for="n in catalog" :key="n.id" :value="n.id" :label="`${n.name} (${n.entity_type})`" /></el-select>
    <el-select v-model="queryType"><el-option v-for="(label,key) in types" :key="key" :value="key" :label="label" /></el-select>
    <el-select v-if="queryType==='path'" v-model="targetId" placeholder="选择终点"><el-option v-for="n in catalog" :key="n.id" :value="n.id" :label="`${n.name} (${n.id})`" /></el-select>
    <span>查询深度：{{ depth }} 跳以内</span>
    <el-button :disabled="!entityId || busy || (queryType==='path' && !targetId)" @click="query">查询关联</el-button>
    <p role="status">{{ busy ? '查询中…' : message }}</p>
    <p v-if="truncated">结果已截断，请缩小查询范围。</p>
    <p>颜色：商品蓝色、品类绿色、供应商橙色、门店紫色、活动红色</p>
    <p>唯一实体 {{ currentNodes.length }} · 唯一关系 {{ edges.length }} · 返回最大跳数 {{ hopCount }}</p>
    <el-button @click="fit">适应画布</el-button><el-button @click="reset">重置布局</el-button><el-button :disabled="busy || !entityId" @click="query">重新查询</el-button>
    <div class="workspace"><div ref="graph" class="graph" aria-label="后端查询返回的关系图"></div>
    <aside><h3>节点属性</h3><p v-if="!selected">点击节点查看属性，双击打开详情</p><dl v-else><template v-for="(value,key) in selected" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></template></dl></aside></div>
    <el-dialog v-model="detailOpen" title="实体详情"><pre>{{ JSON.stringify(selected,null,2) }}</pre></el-dialog>
    <h3>查询路径（顺序表示遍历；箭头表示数据库真实方向）</h3>
    <el-button @click="highlight(-1)">清除路径高亮</el-button>
    <div class="paths"><button v-for="(p,i) in paths" :key="i" :class="{active:activePath===i}" @click="highlight(i)">{{ pathText(p) }}（{{ p.hop_count }} 跳）</button></div>

    <el-table :data="edges"><el-table-column prop="source" label="起点" /><el-table-column prop="relation" label="关系" /><el-table-column prop="target" label="终点" /></el-table>
    <p>来源：graph_query；数据性质：simulated；数据集：{{ dataset || '尚未查询' }}</p>
  </section>
</template>
<script setup>
import { computed, ref, nextTick, onMounted, onBeforeUnmount } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'
const props=defineProps({apiBase:{type:String,required:true}})
const graph=ref(null),catalog=ref([]),entityId=ref(''),queryType=ref('one_hop'),busy=ref(false),message=ref('尚未查询'),selected=ref(null),edges=ref([]),dataset=ref(''),truncated=ref(false)
const targetId=ref(''), paths=ref([]), currentNodes=ref([]), hopCount=ref(0), activePath=ref(-1), detailOpen=ref(false)
const depth=computed(()=>({one_hop:1,two_hop:2,three_hop:3,path:3}[queryType.value] || 1))
const types={one_hop:'一跳关系',two_hop:'二跳关系',three_hop:'三跳关系',path:'路径查询',product_category:'商品品类',product_suppliers:'商品供应商',store_products:'门店经营商品',promotion_details:'活动关联商品与门店'}
let chart, observer, alive=true
function draw(nodes,links){
 if(!chart)return
 if(!nodes.length){chart.clear();return}
 const colors={Product:'#409eff',Category:'#67c23a',Supplier:'#e6a23c',Store:'#9855cc',Promotion:'#f56c6c'}
 const path=paths.value[activePath.value], count=nodes.length
 const degree=id=>links.filter(e=>e.source===id || e.target===id).length
 chart.setOption({tooltip:{show:true,renderMode:'richText',formatter:p=>p.dataType==='node'?`${p.data.entity.name}\n${p.data.id} · ${p.data.entity.entity_type}`:p.data.relation},animationDurationUpdate:350,series:[{type:'graph',layout:'force',roam:true,draggable:true,scaleLimit:{min:0.2,max:5},force:{repulsion:Math.min(1600,450+count*45),edgeLength:[130,220],gravity:0.06,layoutAnimation:true},label:{show:true,position:'bottom',formatter:p=>p.name.length>12?p.name.slice(0,12)+'…':p.name},edgeLabel:{show:true,fontSize:11,formatter:p=>p.data.relation},edgeSymbol:['none','arrow'],edgeSymbolSize:9,emphasis:{focus:'adjacency'},data:nodes.map(n=>({id:n.id,name:n.name,symbolSize:38+Math.min(12,degree(n.id)*2),itemStyle:{color:colors[n.entity_type],opacity:!path || path.node_ids.includes(n.id)?1:0.18},entity:n})),links:links.map(e=>({...e,lineStyle:{width:path?.relationship_ids.includes(e.id)?4:1.5,opacity:!path || path.relationship_ids.includes(e.id)?1:0.12,curveness:links.some(other=>other.source===e.target && other.target===e.source)?0.2:0.07}}))}]},true)
 chart.resize()
}
function fit(){chart?.setOption({series:[{zoom:1,center:['50%','50%']}]});chart?.resize()}
function reset(){activePath.value=-1;draw(currentNodes.value,edges.value);fit()}
function highlight(i){activePath.value=i;draw(currentNodes.value,edges.value)}
function pathText(p){return p.node_ids.reduce((text,id,i)=>{if(!i)return id;const e=edges.value.find(e=>e.id===p.relationship_ids[i-1]);return text+(e?.source===p.node_ids[i-1]?` —${e.relation}→ `:` ←${e?.relation}— `)+id},'')}

async function request(path,body){
 if(busy.value)return
 busy.value=true;selected.value=null;edges.value=[];paths.value=[];currentNodes.value=[];hopCount.value=0;activePath.value=-1;draw([],[]);message.value=''
 try{
  const {data}=body?await axios.post(props.apiBase+path,body,{timeout:10000}):await axios.get(props.apiBase+path,{timeout:10000})
  if(!alive)return
  dataset.value=data.dataset_id;truncated.value=data.data.truncated
  if(!body){catalog.value=data.data.nodes;entityId.value=catalog.value[0]?.id || ''}
  currentNodes.value=data.data.nodes;paths.value=data.data.paths || [];hopCount.value=data.data.hop_count || 0
  edges.value=data.data.edges
  message.value=data.status==='empty'?'没有查询到实体':data.data.type_mismatch?'实体类型不适用于该查询':body && !edges.value.length?'没有匹配的关联关系':'查询完成（模拟数据）'
  draw(data.data.nodes,edges.value)
 }catch(e){if(alive){message.value=e.response?.data?.status==='not_configured'?'图谱服务未配置':e.response?.data?.error_code || '图谱查询失败';if(!body){catalog.value=[];entityId.value=''}}}
 finally{if(alive)busy.value=false}
}
function load(){return request('/api/v1/graph/entities?limit=100')}
function query(){return request('/api/v1/graph/query',{query_type:queryType.value,entity_id:entityId.value,limit:100,max_nodes:100,max_relationships:100,...(['one_hop','two_hop','three_hop','path'].includes(queryType.value)?{max_hops:depth.value}:{}),...(queryType.value==='path'?{target_id:targetId.value}:{})})}
onMounted(async()=>{await nextTick();if(!alive)return;chart=echarts.init(graph.value);chart.on('click',p=>{if(p.dataType==='node'){selected.value=p.data.entity;entityId.value=p.data.id}});chart.on('dblclick',p=>{if(p.dataType==='node'){selected.value=p.data.entity;detailOpen.value=true}});observer=new ResizeObserver(()=>chart?.resize());observer.observe(graph.value);load()})
onBeforeUnmount(()=>{alive=false;observer?.disconnect();chart?.dispose();chart=null})
</script>
<style scoped>.el-select{width:230px;margin:12px}.el-button{margin:12px}pre{white-space:pre-wrap}.workspace{display:flex;gap:16px}.graph{height:520px;flex:1;min-width:0}aside{width:240px;overflow:auto;max-height:520px;background:#f5f7fa;padding:12px}dd{margin:0;overflow-wrap:anywhere}dt{font-weight:bold;margin-top:8px}.paths{max-height:220px;overflow:auto}.paths button{display:block;margin:6px;padding:8px;border:1px solid #ddd;background:white;cursor:pointer}.paths .active{background:#d9ecff}@media(max-width:800px){.workspace{flex-direction:column}aside{width:auto}.graph{flex:auto;width:100%}}</style>
