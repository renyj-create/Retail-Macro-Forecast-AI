<template>
  <el-card shadow="never" class="image-analysis">
    <h3>经营报表截图分析</h3>
    <el-alert title="图片识别信息未经核实，不是数据库事实。仅支持 PNG/JPEG，最大 5 MiB、1600 万像素。" type="warning" :closable="false" />
    <input ref="picker" type="file" accept="image/png,image/jpeg" :disabled="busy" aria-label="选择经营报表截图" @click="resetPicker" @change="choose" />
    <p v-if="file" data-testid="selected-image-name">已选择：{{ file.name }}</p>
    <div v-if="preview"><img :src="preview" alt="待分析截图预览" class="preview" /><el-button :disabled="busy" @click="remove">移除图片</el-button></div>
    <el-input v-model="question" type="textarea" maxlength="2000" placeholder="请输入针对截图的问题；图片将发送到配置的视觉服务" :disabled="busy" />
    <el-button type="primary" :loading="busy" :disabled="!file || !question.trim()" @click="submit">分析截图</el-button>
    <p role="status">{{ busy ? '处理中…' : statusText }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="result">
      <el-alert :type="result.is_mock ? 'warning' : 'info'" :title="result.message" :closable="false" />
      <p>任务：{{ result.task_id }} · 来源：{{ result.evidence?.source_type }} · {{ result.evidence?.data_nature }} · {{ result.provider }}</p>
      <el-table :data="result.fields || []">
        <el-table-column prop="name" label="字段" /><el-table-column prop="raw_text" label="原始文本" />
        <el-table-column prop="normalized_value" label="规范值" /><el-table-column prop="normalized_unit" label="单位" />
        <el-table-column prop="validation_status" label="校验状态" />
      </el-table>
      <ul><li v-for="(issue, index) in result.issues || []" :key="index">{{ issue.field }} · {{ issue.code }}：{{ issue.message }}</li></ul>
      <p v-if="result.report_status === 'template'">确定性模板报告，未调用报告生成模型</p>
      <pre>{{ result.report }}</pre>
    </template>
  </el-card>
</template>
<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import axios from 'axios'
const props = defineProps({ apiBase: { type: String, required: true } })
const picker = ref(null), file = ref(null), preview = ref(''), question = ref('请识别报表中的日期、营业收入等可见字段并检查单位。')
const busy = ref(false), result = ref(null), error = ref('')
const statusText = computed(() => error.value ? '分析失败：' + error.value : ({ success: '识别完成，仍需核实原图', needs_review: '识别完成，存在待核实字段', mock: '模拟识别结果，仅供开发测试', failed: '识别失败', not_configured: '视觉模型未配置，未执行识别' }[result.value?.status] || (file.value ? '已选择图片，待上传' : '请选择图片')))
function remove() {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''; file.value = null; result.value = null; error.value = ''
  if (picker.value) picker.value.value = ''
}
function resetPicker() {
  // Clear only the native picker so choosing the same file emits change.
  // Keep the File and preview until another selection is confirmed.
  if (picker.value) picker.value.value = ''
}
function choose(event) {
  const selected = event.target.files?.[0]
  if (!selected) return
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''; file.value = null; result.value = null; error.value = ''
  if (!/\.(png|jpe?g)$/i.test(selected.name) || selected.size > 5 * 1024 * 1024) { error.value = '请选择不超过 5 MiB 的 PNG/JPEG 图片'; return }
  file.value = selected; preview.value = URL.createObjectURL(selected)

}
async function submit() {
  if (busy.value || !file.value || !question.value.trim()) return
  busy.value = true; result.value = null; error.value = ''
  const data = new FormData(); data.append('file', file.value); data.append('question', question.value)
  try { result.value = (await axios.post(`${props.apiBase}/api/v1/multimodal/analyze`, data, { timeout: 60000 })).data }
  catch (e) { error.value = e.response?.data?.message || '上传或分析失败，请检查服务后重试' }
  finally { busy.value = false }
}
onBeforeUnmount(() => { if (preview.value) URL.revokeObjectURL(preview.value) })
</script>
<style scoped>
.image-analysis { margin: 20px 0; }
.preview { max-width: 100%; max-height: 260px; display: block; margin: 12px 0; }
input, .el-textarea, .el-button { margin-top: 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
