<template>
  <el-container class="layout">
    <!-- 左侧垂直菜单 -->
    <el-aside width="220px" class="sidebar">
      <div class="logo">
        <el-icon><DataLine /></el-icon>
        <span>零售数据洞察</span>
      </div>
      <el-menu
        default-active="1"
        class="el-menu-vertical"
        :background-color="'#1f2937'"
        :text-color="'#9ca3af'"
        :active-text-color="'#60a5fa'"
        :border-right="'none'"
        @select="handleMenuSelect"
      >
        <el-menu-item index="1">
          <el-icon><Odometer /></el-icon>
          <span>数据总览</span>
        </el-menu-item>
        <el-menu-item index="2">
          <el-icon><UserFilled /></el-icon>
          <span>用户流失预警</span>
        </el-menu-item>
        <el-menu-item index="3">
          <el-icon><ChatDotRound /></el-icon>
          <span>智能问数 Agent</span>
        </el-menu-item>
        <el-menu-item index="4">
          <el-icon><Comment /></el-icon>
          <span>报告反馈管理</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 右侧内容区 -->
    <el-container class="main-container">
      <!-- 顶部导航栏 -->
      <el-header class="header">
        <div class="breadcrumb">首页 / {{ currentPageName }}</div>
        <div class="user-info">
          <el-avatar :size="32" src="https://cube.elemecdn.com/0/88/03b0d39583f48206768a7534e55bcpng.png" />
          <span>管理员</span>
        </div>
      </el-header>

      <!-- 主内容区 -->
      <el-main class="main-content">

        <!-- 页面 1: 数据总览 -->
        <div v-if="activeMenu === '1'">
          <!-- 演示数据声明：醒目提示 -->
          <div class="demo-notice">
            <el-tag type="warning" effect="dark" size="large" class="demo-notice-tag">
              演示数据：宏观数据为真实统计局数据，用户微观数据为RFM模拟数据
            </el-tag>
          </div>

          <el-row :gutter="20" class="kpi-row">
            <el-col :span="8">
              <el-card shadow="hover" class="kpi-card">
                <div class="kpi-title">最新社零总额（亿元）</div>
                <div class="kpi-value">39,824.4</div>
                <div class="kpi-trend up">同比 +0.4%</div>
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="hover" class="kpi-card">
                <div class="kpi-title">预测用户流失率</div>
                <div class="kpi-value">15.95%</div>
                <div class="kpi-trend">模拟数据集标签占比</div>
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="hover" class="kpi-card">
                <div class="kpi-title">模型 AUC 评估</div>
                <div class="kpi-value">0.82</div>
                <div class="kpi-trend up">KS: 0.56</div>
              </el-card>
            </el-col>
          </el-row>

          <el-card shadow="hover" class="chart-card">
            <template #header>
              <div class="card-header">
                <span>社零总额与增速趋势</span>
                <el-tag size="small" type="info">数据来源：国家统计局</el-tag>
              </div>
            </template>
            <div id="macroChart" style="width: 100%; height: 420px;"></div>
            <div class="chart-note">注：置信区间为 ARIMA 模型基于历史数据的预测，仅供参考，不构成投资建议。</div>
          </el-card>
        </div>

        <!-- 页面 2: 用户流失预警 -->
        <div v-if="activeMenu === '2'">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span>高流失风险用户明细</span>
                <el-button type="primary" size="small" :loading="refreshLoading" @click="refreshPrediction">刷新预测</el-button>
              </div>
            </template>

            <!-- 筛选器工具栏：风险等级筛选 + 最近购买天数排序 -->
            <div class="filter-bar">
              <div class="filter-item">
                <span class="filter-label">风险等级：</span>
                <el-select v-model="riskFilter" placeholder="全部风险等级" clearable style="width: 160px">
                  <el-option label="低风险" value="低风险" />
                  <el-option label="中风险" value="中风险" />
                  <el-option label="高风险" value="高风险" />
                  <el-option label="极高风险" value="极高风险" />
                </el-select>
              </div>
              <div class="filter-item">
                <span class="filter-label">最近购买排序：</span>
                <el-select v-model="recencySort" placeholder="默认排序" style="width: 180px">
                  <el-option label="默认排序" value="" />
                  <el-option label="最近购买（升序）" value="asc" />
                  <el-option label="最近购买（降序）" value="desc" />
                </el-select>
              </div>
            </div>

            <!-- 批量操作工具栏 -->
            <div class="batch-bar">
              <span class="batch-info">已选 <b>{{ selectedUsers.length }}</b> 位用户</span>
              <el-button type="warning" :disabled="selectedUsers.length === 0" @click="openRecallDialog">批量操作：生成召回计划</el-button>
            </div>

            <el-table :data="filteredTableData" style="width: 100%" stripe @selection-change="handleSelectionChange">
              <el-table-column type="selection" width="55" />
              <el-table-column prop="userId" label="用户ID" width="100" />
              <el-table-column prop="age" label="年龄" width="70" />
              <el-table-column prop="cityTier" label="城市等级" width="90" />
              <el-table-column prop="recency" label="最近购买(天)" width="110" />
              <el-table-column prop="frequency" label="购买频次" width="90" />
              <el-table-column prop="churnProb" label="流失概率" width="110">
                <template #default="scope">
                  <el-tag :type="getRiskTagType(scope.row.churnProb)" effect="dark">
                    {{ (scope.row.churnProb * 100).toFixed(1) }}%
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="风险等级" width="100" align="center">
                <template #default="scope">
                  <el-tag :type="getRiskTagType(scope.row.churnProb)" effect="dark" size="small">
                    {{ getRiskLevel(scope.row.churnProb) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="建议动作" min-width="140">
                <template #default="scope">
                  <span class="action-text">{{ getRiskAction(scope.row.churnProb) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="跟进状态" width="100" align="center">
                <template #default="scope">
                  <el-tag :type="getFollowStatusTagType(scope.row.followStatus)" size="small">
                    {{ scope.row.followStatus }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <!-- 批量操作结果对话框 -->
          <el-dialog v-model="recallDialogVisible" title="批量生成召回计划" width="440px">
            <p class="recall-result">已成功为 <b>{{ selectedUsers.length }}</b> 位高风险用户生成召回计划。</p>
            <template #footer>
              <el-button type="primary" @click="recallDialogVisible = false">确定</el-button>
            </template>
          </el-dialog>
        </div>

        <!-- 页面 3: 智能问数 Agent -->
        <div v-if="activeMenu === '3'">
          <el-card shadow="hover" class="agent-card">
            <template #header>
              <div class="card-header">
                <span>🤖 企业级智能问数 Agent</span>
                <el-tag type="success" size="small">LangGraph + MCP + RAG</el-tag>
              </div>
            </template>

            <div class="agent-input-area">
              <el-input
                v-model="query"
                type="textarea"
                :rows="4"
                placeholder="请输入你的业务问题，例如：结合宏观零售数据，给出当前用户流失预警和运营建议"
              />
              <div class="action-bar">
                <div class="upload">
                  <el-upload action="#" :auto-upload="false" :show-file-list="false" :on-change="handleImageUpload">
                    <el-button size="small" plain><el-icon><Picture /></el-icon> 上传趋势图/门店照片</el-button>
                  </el-upload>
                  <span v-if="imageName" class="image-name">{{ imageName }}</span>
                </div>
                <el-button type="primary" size="large" :loading="loading" @click="sendQuery">
                  <el-icon><MagicStick /></el-icon> 开始智能分析
                </el-button>
              </div>
            </div>

            <div v-if="report" class="agent-result">
              <!-- 🌟 可打印的报告区域 -->
              <div class="print-area">
                <!-- 🌟 报告生成状态标签 -->
                <div class="report-status">
                  <el-tag v-if="reportMeta.status === 'success'" type="success" effect="dark" size="large">AI 实时生成</el-tag>
                  <el-tag v-else-if="reportMeta.status === 'fallback'" type="warning" effect="dark" size="large">AI 服务降级，当前为模板兜底报告（原因：{{ reportMeta.reason }}）</el-tag>
                  <el-tag v-else-if="reportMeta.status === 'failed'" type="danger" effect="dark" size="large">系统异常，请重试</el-tag>
                </div>

                <el-divider content-position="left">诊断报告</el-divider>
                <div class="report-content">{{ report }}</div>

                <!-- 🌟 可解释性：执行明细折叠面板 -->
                <el-collapse v-model="execCollapse" class="exec-collapse">
                  <el-collapse-item title="查看执行明细" name="exec">
                    <div class="exec-detail">
                      <div class="exec-block">
                        <div class="exec-label">原始 SQL 语句</div>
                        <pre class="exec-code">{{ execDetail.sql || '（本次查询未涉及 SQL）' }}</pre>
                      </div>
                      <div class="exec-block">
                        <div class="exec-label">查到的数据量</div>
                        <div class="exec-text">{{ execDetail.dataCount }} 条记录</div>
                      </div>
                      <div class="exec-block">
                        <div class="exec-label">知识库原文片段（ChromaDB）</div>
                        <div class="exec-text">{{ execDetail.kbFragments || '（无检索结果）' }}</div>
                      </div>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </div>

              <!-- 🌟 报告操作：导出 + 反馈 -->
              <div class="report-actions">
                <el-button type="primary" plain @click="exportReport">导出报告</el-button>
                <el-button type="success" plain @click="sendFeedback('up')">👍 有帮助</el-button>
                <el-button type="danger" plain @click="sendFeedback('down')">👎 无帮助</el-button>
              </div>
            </div>
          </el-card>
        </div>

        <!-- 页面 4: 报告反馈管理 -->
        <div v-if="activeMenu === '4'">
          <!-- 统计卡片 -->
          <el-row :gutter="20" class="kpi-row">
            <el-col :span="6">
              <el-card shadow="hover" class="kpi-card">
                <div class="kpi-title">反馈总数</div>
                <div class="kpi-value">{{ feedbackStats.total }}</div>
                <div class="kpi-trend up">Total Feedback</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="hover" class="kpi-card">
                <div class="kpi-title">点赞数</div>
                <div class="kpi-value">{{ feedbackStats.up_count }}</div>
                <div class="kpi-trend up">👍 有帮助</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="hover" class="kpi-card">
                <div class="kpi-title">点踩数</div>
                <div class="kpi-value">{{ feedbackStats.down_count }}</div>
                <div class="kpi-trend down">👎 无帮助</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="hover" class="kpi-card">
                <div class="kpi-title">点赞率</div>
                <div class="kpi-value">{{ (feedbackStats.up_rate * 100).toFixed(1) }}%</div>
                <div class="kpi-trend up">Up Rate</div>
              </el-card>
            </el-col>
          </el-row>

          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span>反馈记录</span>
                <el-button type="primary" size="small" :loading="feedbackLoading" @click="refreshFeedback">刷新</el-button>
              </div>
            </template>

            <!-- 反馈类型筛选 -->
            <div class="filter-bar">
              <div class="filter-item">
                <span class="filter-label">反馈类型：</span>
                <el-select v-model="feedbackFilter" placeholder="全部" clearable style="width: 140px" @change="handleFeedbackFilterChange">
                  <el-option label="点赞" value="up" />
                  <el-option label="点踩" value="down" />
                </el-select>
              </div>
            </div>

            <el-table :data="feedbackRecords" v-loading="feedbackLoading" style="width: 100%" stripe>
              <el-table-column prop="id" label="ID" width="80" />
              <el-table-column prop="query" label="用户问题" min-width="240" show-overflow-tooltip />
              <el-table-column label="反馈类型" width="100" align="center">
                <template #default="scope">
                  <el-tag :type="getFeedbackTagType(scope.row.feedback)" effect="dark" size="small">
                    {{ getFeedbackLabel(scope.row.feedback) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="created_at" label="提交时间" width="180" />
              <el-table-column label="操作" width="90" align="center">
                <template #default="scope">
                  <el-button type="primary" link size="small" @click="openFeedbackDetail(scope.row)">查看</el-button>
                </template>
              </el-table-column>
            </el-table>

            <!-- 空状态 -->
            <el-empty v-if="!feedbackLoading && feedbackRecords.length === 0" description="暂无反馈记录" />

            <!-- 分页 -->
            <div class="pagination-bar">
              <el-pagination
                v-model:current-page="feedbackPage"
                v-model:page-size="feedbackPageSize"
                :total="feedbackTotal"
                :page-sizes="[5, 10, 20, 50]"
                layout="total, sizes, prev, pager, next, jumper"
                @current-change="handleFeedbackPageChange"
                @size-change="handleFeedbackSizeChange"
              />
            </div>
          </el-card>

          <!-- 反馈详情对话框 -->
          <el-dialog v-model="feedbackDetailVisible" title="反馈详情" width="640px">
            <div v-if="feedbackDetail" class="feedback-detail">
              <div class="detail-row">
                <span class="detail-label">反馈类型：</span>
                <el-tag :type="getFeedbackTagType(feedbackDetail.feedback)" effect="dark" size="small">{{ getFeedbackLabel(feedbackDetail.feedback) }}</el-tag>
              </div>
              <div class="detail-row"><span class="detail-label">提交时间：</span><span>{{ feedbackDetail.created_at }}</span></div>
              <div class="detail-row"><span class="detail-label">用户问题：</span><span>{{ feedbackDetail.query }}</span></div>
              <div class="detail-label">AI 报告内容：</div>
              <div class="detail-report">{{ feedbackDetail.report }}</div>
            </div>
            <template #footer>
              <el-button type="primary" @click="feedbackDetailVisible = false">关闭</el-button>
            </template>
          </el-dialog>
        </div>

      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, onMounted, nextTick, computed } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'
import { DataLine, Odometer, UserFilled, ChatDotRound, MagicStick, Picture, Comment } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const activeMenu = ref('1')
const query = ref('结合宏观零售数据，给出当前用户流失预警和运营建议')
const report = ref('')
const loading = ref(false)
const imageName = ref('')
const imageBase64 = ref('')
// 🌟 可解释性：后端返回的执行明细（SQL / 数据量 / 知识库片段）
const execDetail = ref({ sql: '', dataCount: 0, kbFragments: '' })
const execCollapse = ref([])
// 🌟 报告生成状态（success / fallback / failed）
const reportMeta = ref({ status: '', reason: '' })

const currentPageName = computed(() => {
  const map = { '1': '数据总览', '2': '用户流失预警', '3': '智能问数 Agent', '4': '报告反馈管理' }
  return map[activeMenu.value]
})

const tableData = ref([
  { userId: '10001', age: 28, cityTier: '一线', recency: 75, frequency: 1, churnProb: 0.85, followStatus: '待跟进' },
  { userId: '10002', age: 35, cityTier: '二线', recency: 62, frequency: 2, churnProb: 0.65, followStatus: '召回中' },
  { userId: '10003', age: 42, cityTier: '三线', recency: 90, frequency: 0, churnProb: 0.92, followStatus: '待跟进' },
  { userId: '10004', age: 23, cityTier: '一线', recency: 45, frequency: 3, churnProb: 0.35, followStatus: '已跟进' },
  { userId: '10005', age: 31, cityTier: '二线', recency: 55, frequency: 1, churnProb: 0.58, followStatus: '召回中' },
  { userId: '10006', age: 27, cityTier: '一线', recency: 8, frequency: 6, churnProb: 0.12, followStatus: '已跟进' },
  { userId: '10007', age: 33, cityTier: '三线', recency: 18, frequency: 4, churnProb: 0.24, followStatus: '已跟进' },
  { userId: '10008', age: 29, cityTier: '二线', recency: 33, frequency: 3, churnProb: 0.42, followStatus: '待跟进' },
  { userId: '10009', age: 40, cityTier: '一线', recency: 70, frequency: 1, churnProb: 0.74, followStatus: '待跟进' },
])

// 🌟 风险等级 / 建议动作 / 标签颜色映射（基于流失概率阈值）
const getRiskLevel = (prob) => {
  if (prob < 0.30) return '低风险'
  if (prob < 0.50) return '中风险'
  if (prob < 0.70) return '高风险'
  return '极高风险'
}

const getRiskAction = (prob) => {
  if (prob < 0.30) return '持续观察'
  if (prob < 0.50) return '关注复购'
  if (prob < 0.70) return '纳入召回名单'
  return '优先人工跟进'
}

const getRiskTagType = (prob) => {
  if (prob < 0.30) return 'success'
  if (prob < 0.50) return 'info'
  if (prob < 0.70) return 'warning'
  return 'danger'
}

// 🌟 筛选器状态：风险等级筛选 + 最近购买天数排序
const riskFilter = ref('')
const recencySort = ref('')

const filteredTableData = computed(() => {
  let list = [...tableData.value]
  // 按风险等级筛选
  if (riskFilter.value) {
    list = list.filter(row => getRiskLevel(row.churnProb) === riskFilter.value)
  }
  // 按最近购买天数排序
  if (recencySort.value === 'asc') {
    list.sort((a, b) => a.recency - b.recency)
  } else if (recencySort.value === 'desc') {
    list.sort((a, b) => b.recency - a.recency)
  }
  return list
})

// 🌟 表格多选 + 跟进状态 + 批量操作
const selectedUsers = ref([])
const recallDialogVisible = ref(false)

const getFollowStatusTagType = (status) => {
  const map = { '待跟进': 'info', '召回中': 'warning', '已跟进': 'success' }
  return map[status] || 'info'
}

const handleSelectionChange = (rows) => {
  selectedUsers.value = rows
}

const openRecallDialog = () => {
  if (selectedUsers.value.length === 0) {
    ElMessage.warning('请先勾选需要操作的用户')
    return
  }
  recallDialogVisible.value = true
}

// 🌟 刷新预测：显示加载状态 + 弹出更新提示
const refreshLoading = ref(false)

const refreshPrediction = async () => {
  refreshLoading.value = true
  try {
    // 模拟从后端重新拉取模型预测结果（实际项目替换为真实 churn 预测接口）
    await new Promise(resolve => setTimeout(resolve, 600))
    const now = new Date()
    const hh = String(now.getHours()).padStart(2, '0')
    const mm = String(now.getMinutes()).padStart(2, '0')
    ElMessage.success(`已从后端重新拉取模型预测结果，更新时间：${hh}:${mm}`)
  } catch (error) {
    console.error(error)
    ElMessage.error('预测结果拉取失败，请稍后重试')
  } finally {
    refreshLoading.value = false
  }
}

const handleMenuSelect = (index) => {
  activeMenu.value = index
  if (index === '1') {
    nextTick(() => initMacroChart())
  }
  if (index === '4') {
    refreshFeedback()
  }
}

// 处理图片上传并转为 Base64
const handleImageUpload = (uploadFile) => {
  imageName.value = uploadFile.name
  const reader = new FileReader()
  reader.readAsDataURL(uploadFile.raw)
  reader.onload = () => {
    // 去掉 data:image/png;base64, 前缀，只保留纯 base64 数据
    imageBase64.value = reader.result.split(',')[1]
  }
}

const sendQuery = async () => {
  if (!query.value.trim()) return
  loading.value = true
  report.value = ''
  // 重置执行明细与状态
  execDetail.value = { sql: '', dataCount: 0, kbFragments: '' }
  execCollapse.value = []
  reportMeta.value = { status: '', reason: '' }

  try {
    const response = await axios.post('http://127.0.0.1:8003/api/v1/analyze', {
      query: query.value,
      image_base64: imageBase64.value // 把图片发给后端
    })
    report.value = response.data.report
    // 🌟 保存后端返回的执行明细（SQL / 数据量 / 知识库片段）
    execDetail.value = {
      sql: response.data.sql || '',
      dataCount: response.data.data_count ?? 0,
      kbFragments: response.data.kb_fragments || ''
    }
    // 🌟 保存报告生成状态（success / fallback / failed）
    reportMeta.value = {
      status: response.data.generation_status || 'success',
      reason: response.data.fallback_reason || ''
    }
  } catch (error) {
    console.error(error)
    report.value = '服务连接失败，请确认后端服务已启动。'
    reportMeta.value = { status: 'failed', reason: '无法连接后端服务' }
  } finally {
    loading.value = false
    imageName.value = '' // 清空图片名称
    imageBase64.value = ''
  }
}

// 🌟 导出报告：调用浏览器打印当前报告区域
const exportReport = () => {
  window.print()
}

// 🌟 点赞/踩反馈：提交到后端模拟接口并弹提示
const sendFeedback = async (type) => {
  try {
    await axios.post('http://127.0.0.1:8003/api/v1/feedback', {
      query: query.value,
      feedback: type,
      report: report.value
    })
    ElMessage.success('感谢反馈')
  } catch (error) {
    console.error(error)
    ElMessage.error('反馈提交失败，请稍后重试')
  }
}

// 🌟 报告反馈管理
const feedbackStats = ref({ total: 0, up_count: 0, down_count: 0, up_rate: 0 })
const feedbackRecords = ref([])
const feedbackTotal = ref(0)
const feedbackFilter = ref('') // ''=全部, 'up'=点赞, 'down'=点踩
const feedbackPage = ref(1)
const feedbackPageSize = ref(10)
const feedbackLoading = ref(false)
const feedbackDetailVisible = ref(false)
const feedbackDetail = ref(null)

const getFeedbackTagType = (fb) => (fb === 'up' ? 'success' : 'danger')
const getFeedbackLabel = (fb) => (fb === 'up' ? '点赞' : '点踩')

const loadFeedbackStats = async () => {
  try {
    const { data } = await axios.get('http://127.0.0.1:8003/api/v1/feedback/stats')
    feedbackStats.value = data.data || { total: 0, up_count: 0, down_count: 0, up_rate: 0 }
  } catch (error) {
    console.error('加载反馈统计失败:', error)
    ElMessage.error('反馈统计加载失败')
  }
}

const loadFeedbackRecords = async () => {
  feedbackLoading.value = true
  try {
    const params = { page: feedbackPage.value, page_size: feedbackPageSize.value }
    if (feedbackFilter.value) params.feedback = feedbackFilter.value
    const { data } = await axios.get('http://127.0.0.1:8003/api/v1/feedback', { params })
    const d = data.data || { records: [], total: 0 }
    feedbackRecords.value = d.records
    feedbackTotal.value = d.total
  } catch (error) {
    console.error('加载反馈记录失败:', error)
    feedbackRecords.value = []
    feedbackTotal.value = 0
    ElMessage.error('反馈记录加载失败')
  } finally {
    feedbackLoading.value = false
  }
}

const refreshFeedback = () => {
  loadFeedbackStats()
  loadFeedbackRecords()
}

const handleFeedbackFilterChange = () => {
  feedbackPage.value = 1
  loadFeedbackRecords()
}

const handleFeedbackPageChange = (page) => {
  feedbackPage.value = page
  loadFeedbackRecords()
}

const handleFeedbackSizeChange = (size) => {
  feedbackPageSize.value = size
  feedbackPage.value = 1
  loadFeedbackRecords()
}

const openFeedbackDetail = (row) => {
  feedbackDetail.value = row
  feedbackDetailVisible.value = true
}

const initMacroChart = async () => {
  const chartDom = document.getElementById('macroChart')
  if (!chartDom) return
  // 复用已有实例（若 DOM 被 v-if 销毁重建，则重新 init）
  let myChart = echarts.getInstanceByDom(chartDom)
  if (!myChart) myChart = echarts.init(chartDom)

  myChart.showLoading({ text: '加载预测数据...', color: '#60a5fa', textColor: '#6b7280', maskColor: 'rgba(255,255,255,0.6)' })

  try {
    const { data } = await axios.get('http://127.0.0.1:8003/api/v1/forecast')
    renderForecastChart(myChart, data)
  } catch (error) {
    console.error('预测接口调用失败:', error)
    myChart.hideLoading()
    // 后端不可用时优雅降级：在图表区域给出提示
    myChart.setOption({
      title: {
        text: '预测服务暂不可用',
        subtext: '请确认后端 FastAPI 服务已启动（http://127.0.0.1:8003）',
        left: 'center',
        top: 'middle',
        textStyle: { fontSize: 16, color: '#9ca3af' },
        subtextStyle: { fontSize: 12, color: '#d1d5db' }
      }
    })
  }
}

const renderForecastChart = (myChart, d) => {
  const H = d.historical_dates.length
  const F = d.forecast_dates.length
  const lastHist = d.historical_values[H - 1]
  const m = d.metrics || {}

  // x 轴类别：历史月份 + 预测月份
  const categories = [...d.historical_dates, ...d.forecast_dates]

  // 历史真实值（蓝色实线）：后面补 null 占位
  const historicalLine = [...d.historical_values, ...Array(F).fill(null)]

  // 预测值（橙色虚线）：与历史末值相连，保证曲线连续
  const forecastLine = Array(H).fill(null)
  forecastLine[H - 1] = lastHist
  d.forecast_values.forEach(v => forecastLine.push(v))

  // 置信区间下界（透明占位，仅用于堆叠定位下边界）
  const ciLower = Array(H).fill(null)
  ciLower[H - 1] = lastHist
  d.lower_bound.forEach(v => ciLower.push(v))

  // 置信区间带宽（上界 - 下界），堆叠后形成 [下界, 上界] 的淡橙填充带
  const ciBand = Array(H).fill(null)
  ciBand[H - 1] = 0
  d.upper_bound.forEach((u, i) => ciBand.push(Number((u - d.lower_bound[i]).toFixed(1))))

  // 异常点（红色散点）：按月份映射到 x 轴索引
  const anomalyData = (d.anomalies || [])
    .map(a => {
      const idx = d.historical_dates.indexOf(a.date)
      return idx >= 0 ? [idx, a.value] : null
    })
    .filter(Boolean)

  const option = {
    color: ['#3b82f6', '#f97316'],
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(17,24,39,0.92)',
      borderWidth: 0,
      padding: [10, 14],
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params) => {
        if (!params || params.length === 0) return ''
        const head = params[0].axisValueLabel ?? categories[params[0].dataIndex]
        let html = `<div style="font-weight:600;margin-bottom:6px;">${head}</div>`
        for (const p of params) {
          // 空值判断：跳过 null / undefined / NaN 的数据点（如历史阶段的预测值被 null 填充）
          if (p.value === null || p.value === undefined || (typeof p.value === 'number' && Number.isNaN(p.value))) continue
          // 跳过置信区间填充带与占位系列，区间信息已在「预测值」行内展示
          if (p.seriesName === '95% 置信区间' || p.seriesName.includes('占位')) continue
          if (p.seriesName === '异常点') {
            html += `<div style="display:flex;align-items:center;gap:6px;margin-top:3px;"><span style="width:9px;height:9px;border-radius:50%;background:#ef4444;display:inline-block;"></span>异常点：${Number(p.value[1]).toLocaleString()} 亿元</div>`
            continue
          }
          const color = p.seriesName === '预测值' ? '#f97316' : '#3b82f6'
          let row = `<div style="display:flex;align-items:center;gap:6px;margin-top:3px;"><span style="width:9px;height:9px;border-radius:50%;background:${color};display:inline-block;"></span>${p.seriesName}：<b>${Number(p.value).toLocaleString()}</b> 亿元`
          if (p.seriesName === '预测值') {
            const fi = p.dataIndex - H
            if (fi >= 0 && fi < F) {
              row += `<span style="color:#cbd5e1;margin-left:4px;">[${d.lower_bound[fi]} ~ ${d.upper_bound[fi]}]</span>`
            }
          }
          row += '</div>'
          html += row
        }
        return html
      }
    },
    legend: {
      data: ['历史真实值', '预测值', '95% 置信区间', '异常点'],
      bottom: 0,
      left: 'center',
      itemWidth: 18,
      itemHeight: 10,
      textStyle: { color: '#6b7280', fontSize: 12 }
    },
    grid: { left: '3%', right: '4%', top: 70, bottom: 40, containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#d1d5db' } },
      axisLabel: { color: '#9ca3af', interval: Math.ceil(categories.length / 12), hideOverlap: true }
    },
    yAxis: {
      type: 'value',
      name: '亿元',
      scale: true,
      nameTextStyle: { color: '#9ca3af' },
      axisLabel: { color: '#9ca3af' },
      splitLine: { lineStyle: { type: 'dashed', color: '#eef0f3' } }
    },
    graphic: [
      {
        type: 'group',
        right: 18,
        top: 12,
        children: [
          {
            type: 'rect',
            shape: { width: 180, height: 62 },
            style: { fill: 'rgba(255,255,255,0.94)', stroke: '#eef0f3', lineWidth: 1, borderRadius: 12, shadowBlur: 12, shadowColor: 'rgba(0,0,0,0.06)' }
          },
          {
            type: 'text',
            left: 18,
            top: 14,
            style: { text: `MAPE: ${m.mape}%`, fontSize: 22, fontWeight: 'bold', fill: '#f97316' }
          },
          {
            type: 'text',
            left: 18,
            top: 44,
            style: { text: `回测 MAE ${m.mae} · RMSE ${m.rmse}`, fontSize: 11, fill: '#9ca3af' }
          }
        ]
      }
    ],
    series: [
      {
        name: '历史真实值',
        type: 'line',
        data: historicalLine,
        symbol: 'none',
        smooth: false,
        lineStyle: { width: 2.5, color: '#3b82f6' },
        areaStyle: { color: 'rgba(59,130,246,0.06)' }
      },
      {
        name: '预测值',
        type: 'line',
        data: forecastLine,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2.5, color: '#f97316', type: 'dashed' },
        itemStyle: { color: '#f97316' }
      },
      {
        name: '置信区间下界(占位)',
        type: 'line',
        data: ciLower,
        stack: 'ci',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0 },
        emphasis: { disabled: true }
      },
      {
        name: '95% 置信区间',
        type: 'line',
        data: ciBand,
        stack: 'ci',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: 'rgba(249,115,22,0.18)' },
        emphasis: { disabled: true }
      },
      {
        name: '异常点',
        type: 'scatter',
        data: anomalyData,
        symbolSize: 9,
        itemStyle: { color: '#ef4444', borderColor: '#fff', borderWidth: 1.5 },
        z: 10
      }
    ]
  }

  myChart.hideLoading()
  myChart.setOption(option, true)
}

onMounted(() => {
  // 监听窗口缩放，自适应图表尺寸
  window.addEventListener('resize', () => {
    const dom = document.getElementById('macroChart')
    const inst = dom && echarts.getInstanceByDom(dom)
    if (inst) inst.resize()
  })
  initMacroChart()
})
</script>

<style scoped>
/* 全局高级配色 */
.layout {
  height: 100vh;
  background-color: #f3f4f6;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

/* 侧边栏深色质感 */
.sidebar {
  background-color: #1f2937;
  color: #fff;
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.05);
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 18px;
  font-weight: bold;
  color: #fff;
  background-color: #111827;
  letter-spacing: 1px;
}

.el-menu-vertical {
  border-right: none;
  flex: 1;
}

/* 顶栏 */
.header {
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
  z-index: 10;
  height: 60px;
  padding: 0 24px;
}

.breadcrumb { font-size: 14px; color: #6b7280; }
.user-info { display: flex; align-items: center; gap: 10px; font-size: 14px; color: #374151; }

/* 主内容区 */
.main-content { padding: 24px; overflow-y: auto; }

/* 演示数据声明 */
.demo-notice { display: flex; justify-content: flex-end; margin-bottom: 16px; }
.demo-notice-tag {
  font-size: 14px;
  font-weight: 600;
  height: auto;
  padding: 8px 18px;
  border-radius: 6px;
  letter-spacing: 0.5px;
  box-shadow: 0 4px 14px rgba(230, 162, 60, 0.35);
}

/* KPI 卡片 */
.kpi-row { margin-bottom: 20px; }
.kpi-card { border-radius: 8px; border: none; }
.kpi-title { font-size: 14px; color: #6b7280; margin-bottom: 10px; }
.kpi-value { font-size: 28px; font-weight: bold; color: #111827; margin-bottom: 8px; }
.kpi-trend { font-size: 13px; }
.kpi-trend.up { color: #10b981; }
.kpi-trend.down { color: #ef4444; }

/* 图表卡片 */
.chart-card { border-radius: 8px; border: none; margin-bottom: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; font-weight: bold; font-size: 16px; color: #374151; }
.chart-note { margin-top: 14px; font-size: 12px; color: #9ca3af; text-align: right; line-height: 1.6; }

/* 用户流失预警：筛选器工具栏 */
.filter-bar { display: flex; align-items: center; gap: 24px; margin-bottom: 16px; flex-wrap: wrap; }
.filter-item { display: flex; align-items: center; gap: 8px; }
.filter-label { font-size: 13px; color: #6b7280; }
.action-text { font-size: 13px; color: #374151; }

/* 批量操作工具栏 */
.batch-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.batch-info { font-size: 13px; color: #6b7280; }
.batch-info b { color: #f97316; font-size: 15px; }
.recall-result { font-size: 15px; color: #374151; margin: 8px 0; }
.recall-result b { color: #ef4444; font-size: 18px; }

/* 报告反馈管理 */
.pagination-bar { display: flex; justify-content: flex-end; margin-top: 16px; }
.feedback-detail { display: flex; flex-direction: column; gap: 12px; }
.detail-row { display: flex; align-items: flex-start; gap: 8px; font-size: 14px; color: #374151; }
.detail-label { font-size: 14px; font-weight: 600; color: #374151; }
.detail-report { max-height: 320px; overflow-y: auto; padding: 12px; background-color: #f8fafc; border-radius: 6px; white-space: pre-wrap; line-height: 1.7; font-size: 13px; color: #1e293b; }

/* Agent 交互卡片 */
.agent-card { border-radius: 8px; border: none; }
.agent-input-area { margin-bottom: 20px; }
.action-bar { display: flex; justify-content: space-between; align-items: center; margin-top: 16px; }
.upload { display: flex; align-items: center; gap: 10px; }
.image-name { color: #67c23a; font-size: 14px; }
.agent-result { background-color: #f8fafc; padding: 20px; border-radius: 8px; border: 1px dashed #cbd5e1; }
.report-content { white-space: pre-wrap; line-height: 1.8; color: #1e293b; font-size: 15px; }

/* 报告生成状态标签 */
.report-status { margin-bottom: 12px; }

/* 报告操作按钮 */
.report-actions { display: flex; gap: 12px; margin-top: 16px; }

/* 执行明细折叠面板 */
.exec-collapse { margin-top: 16px; border: none; }
.exec-detail { display: flex; flex-direction: column; gap: 14px; padding: 4px 0; }
.exec-block { border-left: 3px solid #e5e7eb; padding-left: 12px; }
.exec-label { font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 6px; }
.exec-code { margin: 0; padding: 10px 12px; background-color: #0f172a; color: #e2e8f0; border-radius: 6px; font-size: 12px; line-height: 1.6; overflow-x: auto; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; }
.exec-text { font-size: 13px; color: #4b5563; line-height: 1.7; white-space: pre-wrap; }
</style>

<style>
/* 打印样式：仅打印报告区域（非 scoped，作用于全局 body） */
@media print {
  body * { visibility: hidden; }
  .print-area, .print-area * { visibility: visible; }
  .print-area { position: absolute; left: 0; top: 0; width: 100%; padding: 24px; }
}
</style>