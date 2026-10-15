<template>
  <div class="app-shell">
    <!-- ==================== 顶部导航（轻量 · 编辑式） ==================== -->
    <nav class="topbar">
      <div class="topbar-inner">
        <button class="brand" @click="goNav('home')" aria-label="AI Retail Analyst 首页">
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
              <path d="M4 17.5 8.5 12l3.5 3.5L19 6" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" />
              <circle cx="19" cy="6" r="2.3" fill="var(--coral)" />
            </svg>
          </span>
          <span class="brand-text">
            <span class="brand-name">AI Retail Analyst</span>
            <span class="brand-tag">经营分析 · 自然语言问数</span>
          </span>
        </button>

        <div class="nav-links" role="navigation">
          <button
            v-for="item in navItems"
            :key="item.key"
            class="nav-link"
            :class="{ active: activeView === item.key }"
            @click="goNav(item.key)"
          >
            {{ item.label }}
          </button>
        </div>

        <div class="nav-right">
          <span class="nav-status" :class="{ offline: !backendOnline }" :title="backendOnline ? '后端服务已连接' : '后端服务未连接'">
            <span class="nav-status-dot"></span>
            {{ backendOnline ? '服务在线' : '服务离线' }}
          </span>
        </div>
      </div>
    </nav>

    <main class="page-container">
      <!-- ==================== 首页 ==================== -->
      <div v-if="activeView === 'home'" class="home-view">
        <!-- Hero：编辑式主视觉（左侧主张 + 提问，右侧实时经营洞察面板） -->
        <section class="hero">
          <div class="hero-inner">
            <div class="hero-copy">
              <div class="hero-eyebrow">
                <span class="eyebrow-dot"></span>
                企业级 AI 经营分析
              </div>
              <h1 class="hero-title">看懂数字，<br />才能看见机会。</h1>
              <p class="hero-desc">把复杂的数据留给 AI，把判断和决策留给你。</p>

              <div class="hero-ask">
                <div class="ask-box">
                  <span class="ask-icon"><el-icon><Search /></el-icon></span>
                  <textarea
                    id="heroAsk"
                    data-testid="home-query-input"
                    v-model="homeQuery"
                    class="hero-input"
                    rows="2"
                    placeholder="今天，你最想弄清楚什么？"
                    @keydown="onHeroKeydown"
                  ></textarea>
                  <el-button
                    type="primary"
                    class="hero-submit"
                    data-testid="home-query-submit"
                    :loading="loading"
                    :disabled="loading || !homeQuery.trim()"
                    @click="submitHome"
                  >
                    <template v-if="!loading"><el-icon><Right /></el-icon>分析</template>
                  </el-button>
                </div>
                <div class="ask-meta">
                  <span class="ask-hint">Enter 提交 · Shift + Enter 换行</span>
                  <span v-if="homeError" class="ask-error" data-testid="home-analysis-error">{{ homeError }} <a role="button" @click="submitHome">重试</a></span>
                </div>
              </div>

              <div class="hero-examples">
                <span class="examples-label">试试这样问</span>
                <button v-for="(ex, i) in heroExamples" :key="i" class="example-chip" @click="submitExample(ex)">
                  {{ ex.text }}
                </button>
              </div>
            </div>

            <aside class="hero-panel">
              <div class="panel-head">
                <div>
                  <div class="panel-title">经营脉搏</div>
                  <div class="panel-sub">实时指标 · 社零趋势</div>
                </div>
                <span class="panel-source">数据来源：国家统计局</span>
              </div>

              <div class="panel-kpis">
                <div class="panel-kpi">
                  <div class="kpi-label">最新社零总额</div>
                  <div class="kpi-value">
                    {{ heroStatus === 'ready' && hero.latest_macro.value != null ? hero.latest_macro.value.toLocaleString() : '—' }}
                    <span class="kpi-unit">亿元</span>
                  </div>
                  <div class="kpi-meta">{{ heroStatus === 'ready' ? (hero.latest_macro.date || '等待数据') : '数据暂不可用' }}</div>
                </div>
                <div class="panel-kpi">
                  <div class="kpi-label">同比增长</div>
                  <div class="kpi-value" :class="trendClass(hero.latest_macro.yoy)">
                    {{ heroStatus === 'ready' && hero.latest_macro.yoy != null ? (hero.latest_macro.yoy > 0 ? '+' : '') + hero.latest_macro.yoy + '%' : '—' }}
                  </div>
                  <div class="kpi-meta">同比增速</div>
                </div>
                <div class="panel-kpi">
                  <div class="kpi-label">预测回测 MAPE</div>
                  <div class="kpi-value">{{ heroStatus === 'ready' && hero.forecast_metrics ? hero.forecast_metrics.mape + '%' : '—' }}</div>
                  <div class="kpi-meta">ARIMA 留出回测</div>
                </div>
              </div>

              <div class="panel-chart-wrap">
                <div id="heroTrendChart" class="panel-chart"></div>
                <div v-if="heroStatus === 'offline'" class="panel-empty">
                  请启动后端服务以载入实时经营趋势
                </div>
              </div>

              <div class="panel-insight">
                <span class="insight-tag">AI 洞察</span>
                <p v-if="report && sectionContent('【核心结论】')" class="insight-text">
                  {{ truncate(sectionContent('【核心结论】'), 92) }}
                </p>
                <p v-else class="insight-text muted">
                  输入一个问题，让 AI 基于真实数据生成可追溯的洞察结论。
                </p>
              </div>
            </aside>
          </div>
        </section>

        <!-- 可探索的分析场景 -->
        <section class="block" id="scenarios">
          <div class="block-head">
            <div class="block-kicker">Explore · 可探索的分析场景</div>
            <h2 class="block-title">四个入口，各自调用真实的模型与工具</h2>
            <p class="block-sub">不是演示占位——每个场景都会走后端真实的数据查询、预测与推理链路。</p>
          </div>

          <div class="quick-grid">
            <button
              v-for="(s, i) in quickScenarios"
              :key="i"
              class="quick-card"
              :data-testid="'quick-scenario-' + s.id"
              :class="'quick-card--' + s.tone"
              @click="submitScenario(s)"
            >
              <div class="quick-top">
                <span class="quick-index">{{ String(i + 1).padStart(2, '0') }}</span>
                <span class="quick-icon"><el-icon><component :is="s.icon" /></el-icon></span>
              </div>
              <div class="quick-body">
                <div class="quick-title">{{ s.title }}</div>
                <div class="quick-desc">{{ s.desc }}</div>
              </div>
              <div class="quick-foot">
                <span class="quick-tag">{{ s.tag }}</span>
                <span class="quick-arrow"><el-icon><Right /></el-icon></span>
              </div>
            </button>
          </div>
        </section>

        <!-- AI 分析过程 -->
        <section class="block block--workflow">
          <div class="block-head">
            <div class="block-kicker">How it works · AI 分析过程</div>
            <h2 class="block-title">从一句话，到可追溯的分析报告</h2>
            <p class="block-sub">LangGraph 工作流先识别意图，再按需调度真实工具，执行轨迹全程可查。</p>
          </div>

          <div class="workflow">
            <template v-for="(w, i) in workflowSteps" :key="i">
              <div class="workflow-node">
                <div class="workflow-icon"><el-icon><component :is="w.icon" /></el-icon></div>
                <div class="workflow-label">{{ w.title }}</div>
                <div class="workflow-desc">{{ w.desc }}</div>
              </div>
              <div v-if="i < workflowSteps.length - 1" class="workflow-arrow"><el-icon><Right /></el-icon></div>
            </template>
          </div>

          <div class="routing">
            <span class="routing-label">意图路由</span>
            <span class="routing-item">宏观分析 → 数据查询 + 趋势预测</span>
            <span class="routing-sep">·</span>
            <span class="routing-item">流失预测 → 批量推理</span>
            <span class="routing-sep">·</span>
            <span class="routing-item">综合分析 → 组合调用</span>
          </div>
        </section>

        <!-- 查询结果（提交问题后显示，真实接口） -->
        <section v-if="report && !loading" class="home-result-section" data-testid="home-analysis-result">
          <div class="result-head">
            <div>
              <div class="block-kicker">Analysis result · 本次分析</div>
              <h2 class="block-title">分析结果</h2>
            </div>
            <div class="result-status-row">
              <span class="pill" :class="'pill--' + reportMeta.status">
                {{ reportMeta.status === 'success' ? 'AI 实时生成' : reportMeta.status === 'fallback' ? 'AI 降级 · 模板兜底' : '系统异常' }}
              </span>
              <span class="intent-chip">意图：{{ intent }}</span>
            </div>
          </div>

          <div v-if="sectionContent('【核心结论】')" class="conclusion">
            {{ sectionContent('【核心结论】') }}
          </div>

          <div class="process-block">
            <div class="process-head">AI 分析流程 · 真实执行步骤</div>
            <ol class="process-list">
              <li v-for="(e, i) in execution" :key="e.name + i" class="process-step">
                <div class="process-index" :class="e.status">{{ i + 1 }}</div>
                <div class="process-body">
                  <div class="process-title">
                    <span>{{ getToolLabel(e.name) }}</span>
                    <em class="process-status" :class="'st--' + e.status">{{ getStatusText(e.status) }}</em>
                  </div>
                  <div class="process-summary">{{ e.summary }}</div>
                </div>
                <div v-if="e.duration_ms != null" class="process-duration">{{ e.duration_ms }}ms</div>
              </li>
            </ol>
          </div>

          <div class="result-grid">
            <div v-if="agentData.forecast" class="result-panel">
              <div class="panel-title">社零预测与置信区间</div>
              <div id="homeForecastChart" class="chart-box"></div>
            </div>
            <div v-if="agentData.churn" class="result-panel">
              <div class="panel-title">流失风险分布</div>
              <div id="homeRiskChart" class="chart-box"></div>
            </div>
          </div>

          <div class="result-actions">
            <el-button type="primary" plain @click="goNav('agent')">在 AI Agent 中查看完整执行明细 <el-icon><Right /></el-icon></el-button>
            <el-button plain @click="exportReport">导出报告</el-button>
          </div>
        </section>

        <!-- 示例报告（默认折叠 · 明确标注示例数据） -->
        <section class="demo-section">
          <el-collapse v-model="demoCollapse" class="demo-collapse">
            <el-collapse-item name="demo">
              <template #title>
                <div class="demo-collapse-title">
                  <span class="demo-collapse-name">示例分析结果</span>
                  <span class="pill pill--sample">示例数据 · 非真实接口结果</span>
                </div>
              </template>
              <div class="demo-card">
                <div class="demo-left">
                  <div class="demo-title-row">
                    <div>
                      <div class="demo-title">最近 30 天销售分析</div>
                      <div class="demo-sub">近 30 日销售额趋势（静态示例）</div>
                    </div>
                    <div class="demo-kpi">
                      <div class="demo-kpi-value">-18%</div>
                      <div class="demo-kpi-label">销售额环比</div>
                    </div>
                  </div>
                  <div id="demoChart" class="demo-chart"></div>
                </div>
                <div class="demo-right">
                  <div class="demo-ai-label">示例分析结论</div>
                  <div class="demo-block">
                    <div class="demo-block-title">主要原因</div>
                    <ol class="demo-list">
                      <li>核心商品销量下降</li>
                      <li>部分区域订单减少</li>
                      <li>库存不足影响成交</li>
                    </ol>
                  </div>
                  <div class="demo-block">
                    <div class="demo-block-title">优化建议</div>
                    <ul class="demo-list">
                      <li>补充高销量商品库存</li>
                      <li>提升重点客户触达</li>
                    </ul>
                  </div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </section>

        <!-- 产品能力与知识库 -->
        <section class="block">
          <div class="block-head">
            <div class="block-kicker">Capabilities · 产品能力</div>
            <h2 class="block-title">一套系统，打通从提问到洞察的闭环</h2>
          </div>

          <div class="ability-grid">
            <div v-for="(a, i) in abilities" :key="i" class="ability-card">
              <div class="ability-icon"><el-icon><component :is="a.icon" /></el-icon></div>
              <div class="ability-title">{{ a.title }}</div>
              <div class="ability-desc">{{ a.desc }}</div>
            </div>
          </div>

          <div class="kb-strip">
            <div class="kb-strip-icon"><el-icon><Notebook /></el-icon></div>
            <div class="kb-strip-body">
              <div class="kb-strip-title">知识库 · RAG 检索增强</div>
              <p class="kb-strip-text">
                基于本地 ChromaDB 与字符 n-gram TF-IDF 的轻量向量检索，为分析提供可追溯的政策与研报依据；
                未命中时如实返回「未在知识库中找到相关研报」，不编造来源。
              </p>
            </div>
            <el-button plain @click="goNav('kb')">了解知识库</el-button>
          </div>

          <p class="data-note">
            * 宏观社零数据来自国家统计局公开数据；用户流失数据为 RFM 规则生成的模拟数据，仅用于演示分析流程。
          </p>
        </section>

        <!-- 底部 -->
        <footer class="footer">
          <div class="footer-brand">
            <span class="brand-mark small" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
                <path d="M4 17.5 8.5 12l3.5 3.5L19 6" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" />
                <circle cx="19" cy="6" r="2.3" fill="var(--coral)" />
              </svg>
            </span>
            <span>AI Retail Analyst</span>
          </div>
          <div class="footer-tags">
            <span>LangGraph Agent</span><span>·</span><span>RAG</span><span>·</span><span>ARIMA</span><span>·</span><span>LightGBM</span><span>·</span><span>可解释分析</span>
          </div>
          <div class="footer-note">让每一次经营决策，都有数据与 AI 的支撑</div>
        </footer>
      </div>

      <!-- ==================== 数据分析（宏观总览 + 用户流失） ==================== -->
      <div v-if="activeView === 'data'" class="page-view">
        <div class="agent-hero">
          <h1 class="page-title">数据分析</h1>
          <p class="page-sub">宏观社零趋势与用户流失风险，数据来源与口径已在页内明确标注。</p>
        </div>
        <el-tabs v-model="dataTab" class="data-tabs">
          <el-tab-pane label="宏观总览" name="macro">
            <el-alert v-if="overviewStatus === 'offline'" title="宏观总览数据暂不可用，请检查后端服务后重试。" type="warning" :closable="false" show-icon style="margin-bottom:16px" />
            <div class="demo-notice">
              <span class="pill pill--sample">
                宏观数据：国家统计局真实数据{{ macroRange ? '（' + macroRange + '）' : '' }}；用户微观数据：RFM 模拟数据
              </span>
            </div>
            <el-row :gutter="20" class="kpi-row">
              <el-col :span="8">
                <el-card shadow="never" class="kpi-card">
                  <div class="kpi-title">最新社零总额（亿元）</div>
                  <div class="kpi-value">{{ overviewStatus === 'ready' && overview.latest_macro.value != null ? overview.latest_macro.value.toLocaleString() : '—' }}</div>
                  <div class="kpi-trend up">同比 {{ overviewStatus === 'ready' && overview.latest_macro.yoy != null ? overview.latest_macro.yoy + '%' : '—' }}<template v-if="overviewStatus === 'ready' && overview.latest_macro.date">（{{ overview.latest_macro.date }}）</template></div>
                </el-card>
              </el-col>
              <el-col :span="8">
                <el-card shadow="never" class="kpi-card">
                  <div class="kpi-title">模拟流失标签占比</div>
                  <div class="kpi-value">{{ overviewStatus === 'ready' && overview.churn.label_rate != null ? (overview.churn.label_rate * 100).toFixed(2) + '%' : '—' }}</div>
                  <div class="kpi-trend">样本 {{ overviewStatus === 'ready' && overview.churn.total != null ? overview.churn.total : '—' }} 名用户</div>
                </el-card>
              </el-col>
              <el-col :span="8">
                <el-card shadow="never" class="kpi-card">
                  <div class="kpi-title">时序回测 MAPE</div>
                  <div class="kpi-value">{{ overview.forecast_metrics ? overview.forecast_metrics.mape + '%' : '—' }}</div>
                  <div class="kpi-trend up">训练期 AUC 约 {{ overviewStatus === 'ready' ? (overview.model_eval?.auc ?? '—') : '—' }}</div>
                </el-card>
              </el-col>
            </el-row>
            <el-card shadow="never" class="chart-card">
              <template #header>
                <div class="card-header">
                  <span>社零总额与增速趋势</span>
                  <span class="pill pill--sample">数据来源：国家统计局</span>
                </div>
              </template>
              <div id="macroChart" style="width: 100%; height: 420px;"></div>
              <div class="chart-note">注：置信区间为 ARIMA 模型基于历史数据的预测，仅供参考，不构成投资建议。</div>
            </el-card>
          </el-tab-pane>

          <el-tab-pane label="用户流失预警" name="churn">
            <el-alert v-if="churnStatus === 'offline'" title="流失预测数据暂不可用，请检查后端服务后重试。" type="warning" :closable="false" show-icon style="margin-bottom:16px" />
            <div class="demo-notice">
              <span class="pill pill--sample">以下用户与流失概率来自 LightGBM 模型对 RFM 模拟数据的真实批量推理</span>
            </div>
            <el-row :gutter="20" class="kpi-row">
              <el-col :span="6">
                <el-card shadow="never" class="kpi-card">
                  <div class="kpi-title">预测样本数</div>
                  <div class="kpi-value">{{ churnStatus === 'ready' ? (churn.total ?? '—') : '—' }}</div>
                  <div class="kpi-trend">模拟用户</div>
                </el-card>
              </el-col>
              <el-col :span="6">
                <el-card shadow="never" class="kpi-card">
                  <div class="kpi-title">极高风险用户</div>
                  <div class="kpi-value">{{ churnStatus === 'ready' ? churnRiskCount('极高风险') : '—' }}</div>
                  <div class="kpi-trend down">概率 ≥ P95</div>
                </el-card>
              </el-col>
              <el-col :span="6">
                <el-card shadow="never" class="kpi-card">
                  <div class="kpi-title">高风险及以上</div>
                  <div class="kpi-value">{{ churnStatus === 'ready' ? churnRiskCount('高风险') + churnRiskCount('极高风险') : '—' }}</div>
                  <div class="kpi-trend">概率 ≥ P80</div>
                </el-card>
              </el-col>
              <el-col :span="6">
                <el-card shadow="never" class="kpi-card">
                  <div class="kpi-title">首要影响特征</div>
                  <div class="kpi-value" style="font-size:20px">{{ churnTopFeature() }}</div>
                  <div class="kpi-trend">SHAP 归因</div>
                </el-card>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-card shadow="never" class="chart-card">
                  <template #header><div class="card-header"><span>风险等级分布</span></div></template>
                  <div id="riskChart" style="width: 100%; height: 300px;"></div>
                </el-card>
              </el-col>
              <el-col :span="12">
                <el-card shadow="never" class="chart-card">
                  <template #header><div class="card-header"><span>特征重要性（SHAP）</span></div></template>
                  <div id="featureChart" style="width: 100%; height: 300px;"></div>
                </el-card>
              </el-col>
            </el-row>
            <el-card shadow="never" style="margin-top:20px">
              <template #header>
                <div class="card-header">
                  <span>高流失风险用户明细（按流失概率降序）</span>
                  <el-button type="primary" size="small" :loading="churnLoading" @click="loadChurn">刷新预测</el-button>
                </div>
              </template>
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
              </div>
              <div class="batch-bar">
                <span class="batch-info">已选 <b>{{ selectedUsers.length }}</b> 位用户</span>
                <el-button type="warning" :disabled="selectedUsers.length === 0" :loading="recallLoading" @click="createRecallTask">批量操作：创建召回任务</el-button>
              </div>
              <el-table :data="filteredChurnUsers" style="width: 100%" stripe v-loading="churnLoading" @selection-change="handleSelectionChange">
                <el-table-column type="selection" width="55" />
                <el-table-column prop="user_id" label="用户ID" width="100" />
                <el-table-column prop="age" label="年龄" width="70" />
                <el-table-column prop="city_tier" label="城市等级" width="90" />
                <el-table-column prop="recency_days" label="最近购买(天)" width="110" />
                <el-table-column prop="frequency" label="购买频次" width="90" />
                <el-table-column prop="churn_prob" label="流失概率" width="110">
                  <template #default="scope">
                    <el-tag :type="getRiskTagType(scope.row.risk_level)" effect="dark">{{ (scope.row.churn_prob * 100).toFixed(1) }}%</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="风险等级" width="100" align="center">
                  <template #default="scope">
                    <el-tag :type="getRiskTagType(scope.row.risk_level)" effect="dark" size="small">{{ scope.row.risk_level }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="建议动作" min-width="140">
                  <template #default="scope"><span class="action-text">{{ getRiskAction(scope.row.risk_level) }}</span></template>
                </el-table-column>
              </el-table>
              <el-empty v-if="!churnLoading && filteredChurnUsers.length === 0" :description="churnStatus === 'offline' ? '预测服务不可用，暂无数据' : '暂无预测数据'" />
            </el-card>
            <el-dialog v-model="recallDialogVisible" title="召回任务创建结果" width="460px">
              <p class="recall-result">已为 <b>{{ recallResult.user_count }}</b> 位用户创建召回任务，任务编号 <b>#{{ recallResult.task_id }}</b>。</p>
              <p class="recall-note">任务已持久化至后端数据库（status=created），当前未接入真实营销触达通道。</p>
              <template #footer><el-button type="primary" @click="recallDialogVisible = false">确定</el-button></template>
            </el-dialog>
          </el-tab-pane>
        </el-tabs>
      </div>

      <!-- ==================== AI Agent（完整工作台） ==================== -->
      <div v-if="activeView === 'agent'" class="page-view">
        <div class="agent-hero">
          <h1 class="page-title">智能问数 Agent</h1>
          <p class="page-sub">输入自然语言问题，自动完成意图识别、真实数据查询、模型预测与知识检索，生成可追溯的结构化分析报告。</p>
        </div>
        <el-card shadow="never" class="agent-input-card">
          <div class="example-list">
            <span class="example-label">示例问题：</span>
            <el-tag v-for="(q, i) in exampleQuestions" :key="i" class="example-tag" :type="query === q ? 'primary' : 'info'" effect="plain" @click="query = q">{{ q }}</el-tag>
          </div>
          <el-input v-model="query" type="textarea" :rows="4" placeholder="请输入你的业务问题，例如：结合宏观零售数据，给出当前用户流失预警和运营建议" />
          <div class="action-bar">
            <div class="upload">
              <el-upload action="#" :auto-upload="false" :show-file-list="false" :on-change="handleImageUpload">
                <el-button size="small" plain><el-icon><Picture /></el-icon> 上传趋势图</el-button>
              </el-upload>
              <span v-if="imageName" class="image-name">{{ imageName }}</span>
              <el-tag v-if="imageName" type="warning" size="small" effect="plain">多模态识图未接入</el-tag>
            </div>
            <el-button type="primary" size="large" :loading="loading" @click="submitAgent">
              <el-icon><MagicStick /></el-icon> 开始智能分析
            </el-button>
          </div>
          <div v-if="agentError" class="agent-error"><span>{{ agentError }}</span><el-button link type="primary" @click="submitAgent">重试</el-button></div>
        </el-card>

        <el-card v-if="loading" shadow="never" class="agent-status-card">
          <div class="agent-loading"><el-icon class="is-loading" style="font-size:22px"><Loading /></el-icon><span>正在执行分析，请稍候…（意图识别 → 数据查询 → 模型预测 → 报告生成）</span></div>
        </el-card>

        <div v-if="report && !loading" class="agent-result-wrap">
          <div class="report-status">
            <span class="pill" :class="'pill--' + reportMeta.status">
              {{ reportMeta.status === 'success' ? 'AI 实时生成' : reportMeta.status === 'fallback' ? 'AI 服务降级 · 模板兜底' : reportMeta.status === 'failed' ? '系统异常' : '生成中' }}
            </span>
            <span class="intent-chip">意图：{{ intent }}（{{ intentReason }}）</span>
          </div>

          <el-card v-if="sectionContent('【核心结论】')" shadow="never" class="result-card core-card">
            <template #header><div class="card-header"><span>核心结论</span></div></template>
            <div class="section-text">{{ sectionContent('【核心结论】') }}</div>
          </el-card>

          <template v-if="agentData.forecast">
            <el-card shadow="never" class="result-card">
              <template #header><div class="card-header"><span>社零预测与置信区间</span><span class="pill pill--sample">ARIMA 真实预测</span></div></template>
              <div id="agentForecastChart" style="width: 100%; height: 360px;"></div>
            </el-card>
          </template>

          <el-row :gutter="20" v-if="agentData.churn">
            <el-col :span="12">
              <el-card shadow="never" class="result-card">
                <template #header><div class="card-header"><span>流失风险分布</span></div></template>
                <div id="agentRiskChart" style="width: 100%; height: 280px;"></div>
              </el-card>
            </el-col>
            <el-col :span="12">
              <el-card shadow="never" class="result-card">
                <template #header><div class="card-header"><span>流失特征重要性</span></div></template>
                <div id="agentFeatureChart" style="width: 100%; height: 280px;"></div>
              </el-card>
            </el-col>
          </el-row>

          <el-card v-if="agentData.forecast && agentData.forecast.anomalies && agentData.forecast.anomalies.length" shadow="never" class="result-card">
            <template #header><div class="card-header"><span>异常月份（IsolationForest）</span></div></template>
            <div class="anomaly-tags">
              <el-tag v-for="a in agentData.forecast.anomalies" :key="a.date" type="danger" effect="plain" class="anomaly-tag">{{ a.date }} · {{ a.value }} 亿元</el-tag>
            </div>
          </el-card>

          <el-card v-if="agentData.churn && agentData.churn.top_risk_users && agentData.churn.top_risk_users.length" shadow="never" class="result-card">
            <template #header><div class="card-header"><span>高风险用户（Top 10）</span></div></template>
            <el-table :data="agentData.churn.top_risk_users.slice(0, 10)" size="small" stripe>
              <el-table-column prop="user_id" label="用户ID" width="100" />
              <el-table-column prop="age" label="年龄" width="70" />
              <el-table-column prop="city_tier" label="城市等级" width="90" />
              <el-table-column prop="recency_days" label="最近购买(天)" width="110" />
              <el-table-column prop="frequency" label="频次" width="70" />
              <el-table-column label="流失概率" width="110"><template #default="scope">{{ (scope.row.churn_prob * 100).toFixed(1) }}%</template></el-table-column>
              <el-table-column label="风险等级" width="100"><template #default="scope"><el-tag :type="getRiskTagType(scope.row.risk_level)" size="small" effect="dark">{{ scope.row.risk_level }}</el-tag></template></el-table-column>
            </el-table>
          </el-card>

          <el-card v-for="sec in otherSections" :key="sec.title" shadow="never" class="result-card">
            <template #header><div class="card-header"><span>{{ sec.title.replace(/【|】/g, '') }}</span></div></template>
            <div class="section-text">{{ sec.content || '暂无数据' }}</div>
          </el-card>

          <el-card shadow="never" class="result-card">
            <template #header><div class="card-header"><span>执行明细</span></div></template>
            <el-collapse v-model="execCollapse">
              <el-collapse-item title="意图识别" name="intent"><div class="exec-text">识别意图：<b>{{ intent }}</b>（{{ intentReason }}）</div></el-collapse-item>
              <el-collapse-item :title="`工具执行记录（${execution.length} 步）`" name="tools">
                <el-table :data="execution" size="small" stripe>
                  <el-table-column label="步骤" width="180"><template #default="scope"><el-tag :type="getExecTagType(scope.row)" size="small" effect="dark">{{ getToolLabel(scope.row.name) }}</el-tag></template></el-table-column>
                  <el-table-column label="状态" width="90"><template #default="scope">{{ getStatusText(scope.row.status) }}</template></el-table-column>
                  <el-table-column prop="summary" label="执行摘要" min-width="240" show-overflow-tooltip />
                  <el-table-column label="耗时" width="90"><template #default="scope">{{ scope.row.duration_ms != null ? scope.row.duration_ms + 'ms' : '—' }}</template></el-table-column>
                </el-table>
                <div v-if="execution.some(e => e.sql)" class="exec-block" style="margin-top:12px">
                  <div class="exec-label">执行 SQL</div>
                  <pre class="exec-code">{{ execution.filter(e => e.sql).map(e => e.sql).join('\n\n') }}</pre>
                </div>
                <div v-if="execution.some(e => e.source)" class="exec-block" style="margin-top:12px">
                  <div class="exec-label">知识库来源</div>
                  <div class="exec-text">{{ execution.filter(e => e.source).map(e => e.source).join(', ') }}</div>
                </div>
              </el-collapse-item>
              <el-collapse-item title="知识库命中片段" name="kb"><div class="exec-text">{{ kbFragments || '（本次未命中知识库）' }}</div></el-collapse-item>
              <el-collapse-item title="报告原文" name="raw"><div class="exec-text">{{ report }}</div></el-collapse-item>
            </el-collapse>
          </el-card>

          <div class="report-actions">
            <el-button type="primary" plain @click="exportReport">导出报告</el-button>
            <el-button plain @click="sendFeedback('up')">👍 有帮助</el-button>
            <el-button plain @click="sendFeedback('down')">👎 无帮助</el-button>
          </div>
        </div>
        <el-empty v-if="!report && !loading && !agentError" description="输入问题并点击「开始智能分析」，查看真实执行结果" />
      </div>

      <!-- ==================== 智能报告（反馈管理） ==================== -->
      <div v-if="activeView === 'report'" class="page-view">
        <div class="agent-hero">
          <h1 class="page-title">智能报告</h1>
          <p class="page-sub">AI 生成的分析报告可点赞/点踩反馈，反馈持久化用于后续 Prompt 迭代。</p>
        </div>
        <el-row :gutter="20" class="kpi-row">
          <el-col :span="6"><el-card shadow="never" class="kpi-card"><div class="kpi-title">反馈总数</div><div class="kpi-value">{{ feedbackStats.total }}</div></el-card></el-col>
          <el-col :span="6"><el-card shadow="never" class="kpi-card"><div class="kpi-title">点赞数</div><div class="kpi-value">{{ feedbackStats.up_count }}</div></el-card></el-col>
          <el-col :span="6"><el-card shadow="never" class="kpi-card"><div class="kpi-title">点踩数</div><div class="kpi-value">{{ feedbackStats.down_count }}</div></el-card></el-col>
          <el-col :span="6"><el-card shadow="never" class="kpi-card"><div class="kpi-title">点赞率</div><div class="kpi-value">{{ (feedbackStats.up_rate * 100).toFixed(1) }}%</div></el-card></el-col>
        </el-row>
        <el-card shadow="never">
          <template #header><div class="card-header"><span>反馈记录</span><el-button type="primary" size="small" :loading="feedbackLoading" @click="refreshFeedback">刷新</el-button></div></template>
          <div class="filter-bar">
            <div class="filter-item"><span class="filter-label">反馈类型：</span>
              <el-select v-model="feedbackFilter" placeholder="全部" clearable style="width: 140px" @change="handleFeedbackFilterChange">
                <el-option label="点赞" value="up" /><el-option label="点踩" value="down" />
              </el-select>
            </div>
          </div>
          <el-table :data="feedbackRecords" v-loading="feedbackLoading" style="width: 100%" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="query" label="用户问题" min-width="240" show-overflow-tooltip />
            <el-table-column label="反馈类型" width="100" align="center"><template #default="scope"><el-tag :type="getFeedbackTagType(scope.row.feedback)" effect="dark" size="small">{{ getFeedbackLabel(scope.row.feedback) }}</el-tag></template></el-table-column>
            <el-table-column prop="created_at" label="提交时间" width="180" />
            <el-table-column label="操作" width="90" align="center"><template #default="scope"><el-button type="primary" link size="small" @click="openFeedbackDetail(scope.row)">查看</el-button></template></el-table-column>
          </el-table>
          <el-empty v-if="!feedbackLoading && feedbackRecords.length === 0" description="暂无反馈记录" />
          <div class="pagination-bar">
            <el-pagination v-model:current-page="feedbackPage" v-model:page-size="feedbackPageSize" :total="feedbackTotal" :page-sizes="[5, 10, 20, 50]" layout="total, sizes, prev, pager, next, jumper" @current-change="handleFeedbackPageChange" @size-change="handleFeedbackSizeChange" />
          </div>
        </el-card>
        <el-dialog v-model="feedbackDetailVisible" title="反馈详情" width="640px">
          <div v-if="feedbackDetail" class="feedback-detail">
            <div class="detail-row"><span class="detail-label">反馈类型：</span><el-tag :type="getFeedbackTagType(feedbackDetail.feedback)" effect="dark" size="small">{{ getFeedbackLabel(feedbackDetail.feedback) }}</el-tag></div>
            <div class="detail-row"><span class="detail-label">提交时间：</span><span>{{ feedbackDetail.created_at }}</span></div>
            <div class="detail-row"><span class="detail-label">用户问题：</span><span>{{ feedbackDetail.query }}</span></div>
            <div class="detail-label">AI 报告内容：</div>
            <div class="detail-report">{{ feedbackDetail.report }}</div>
          </div>
          <template #footer><el-button type="primary" @click="feedbackDetailVisible = false">关闭</el-button></template>
        </el-dialog>
      </div>

      <!-- ==================== 知识库 ==================== -->
      <div v-if="activeView === 'kb'" class="page-view">
        <div class="agent-hero">
          <h1 class="page-title">知识库</h1>
          <p class="page-sub">经营知识辅助检索模块：基于本地 ChromaDB 与字符 n-gram TF-IDF 的轻量向量检索，为 AI 分析提供政策与研报依据，检索结果可追溯到原文片段。</p>
        </div>
        <el-row :gutter="20" class="kpi-row">
          <el-col :span="8"><el-card shadow="never" class="kpi-card"><div class="kpi-title">向量数据库</div><div class="kpi-value">ChromaDB</div><div class="kpi-trend">本地持久化</div></el-card></el-col>
          <el-col :span="8"><el-card shadow="never" class="kpi-card"><div class="kpi-title">分词方案</div><div class="kpi-value">字符 n-gram</div><div class="kpi-trend">TF-IDF，离线可用</div></el-card></el-col>
          <el-col :span="8"><el-card shadow="never" class="kpi-card"><div class="kpi-title">知识来源</div><div class="kpi-value">docs/policy.txt</div><div class="kpi-trend">示例研报文本</div></el-card></el-col>
        </el-row>
        <el-card shadow="never" class="result-card">
          <template #header><div class="card-header"><span>RAG 检索如何工作</span></div></template>
          <ol class="kb-steps">
            <li>读取本地 <code>docs/policy.txt</code>，按空行分块；</li>
            <li>用字符级 n-gram（2,3）TF-IDF 向量化，写入本地 ChromaDB；</li>
            <li>对用户问题做同空间向量化，检索 Top-K 最相似片段；</li>
            <li>命中片段连同来源回传给大模型，作为报告「数据依据」的一部分；</li>
            <li>未命中时明确返回「未在知识库中找到相关研报」，拒绝编造。</li>
          </ol>
          <el-alert type="info" :closable="false" show-icon title="RAG 已接入智能问数 Agent（/api/v1/analyze），在 AI Agent 页执行分析即可看到真实命中片段与来源。" />
        </el-card>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, computed, watch } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'
import {
  UserFilled, ChatLineRound, MagicStick, Picture, Loading,
  Right, Cpu, TrendCharts, Collection, Document, Search, WarningFilled,
  Aim, Connection, Notebook
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const API_BASE = 'http://127.0.0.1:8003'

// ==================== 导航 ====================
const navItems = [
  { key: 'home', label: '首页' },
  { key: 'data', label: '数据分析' },
  { key: 'agent', label: 'AI Agent' },
  { key: 'report', label: '智能报告' },
  { key: 'kb', label: '知识库' }
]
const activeView = ref('home')
const dataTab = ref('macro')
const macroRange = ref('')
const demoCollapse = ref([])
const backendOnline = ref(false)

// ==================== 首页静态内容 ====================
const quickScenarios = [
  { id: 'sales-anomaly', icon: 'WarningFilled', tone: 'coral', tag: 'IsolationForest · 异常检测', title: '销售异常分析', desc: '识别社零同比增速中的异常月份，结合历史给出解读。', question: '分析最近社零数据走势，识别异常变化，并给出有数据依据的分析建议。' },
  { id: 'sales-forecast', icon: 'TrendCharts', tone: 'blue', tag: 'ARIMA · 未来 3 个月', title: '趋势预测', desc: '预测社零总额未来走势，附 95% 置信区间与回测指标。', question: '基于现有历史数据预测未来三个月社零走势，展示预测结果及模型评估信息。' },
  { id: 'customer-churn', icon: 'UserFilled', tone: 'amber', tag: 'LightGBM · SHAP 归因', title: '客户流失分析', desc: '对模拟用户做真实批量推理，识别高风险人群与关键特征。', question: '分析用户流失预测结果，展示风险分布、主要影响特征和需要注意的模型限制。' },
  { id: 'business-report', icon: 'Document', tone: 'ink', tag: '六段式报告 · 可追溯', title: '经营报告生成', desc: '组合宏观与流失数据，生成结构化经营建议报告。', question: '结合宏观零售数据和用户流失情况，给出可执行的经营建议。' }
]

const heroExamples = [
  { text: '分析最近的销售趋势', q: '基于现有历史数据预测未来三个月社零走势，展示预测结果及模型评估信息。' },
  { text: '哪些客户存在流失风险？', q: '分析用户流失预测结果，展示风险分布、主要影响特征和需要注意的模型限制。' },
  { text: '生成本月经营分析报告', q: '结合宏观零售数据和用户流失情况，给出可执行的经营建议。' }
]

const abilities = [
  { icon: 'Cpu', title: 'AI Agent 编排', desc: 'LangGraph 工作流按意图路由，自动调度分析工具。' },
  { icon: 'TrendCharts', title: '数据洞察', desc: '宏观趋势、异常检测与预测置信区间，一屏看清。' },
  { icon: 'Collection', title: 'RAG 知识增强', desc: '本地向量检索，为分析提供可追溯的政策与研报依据。' },
  { icon: 'Document', title: '结构化报告', desc: '六段式报告，结论、依据与限制一目了然。' }
]

const workflowSteps = [
  { icon: 'ChatLineRound', title: '用户提问', desc: '自然语言描述业务问题' },
  { icon: 'Aim', title: '意图识别', desc: '大模型识别，规则兜底校正' },
  { icon: 'Connection', title: '按需调用工具', desc: '数据查询 · 预测 · 流失 · 检索' },
  { icon: 'MagicStick', title: '报告生成', desc: '六段式结构化报告' },
  { icon: 'Document', title: '可追溯明细', desc: 'SQL / 来源 / 执行轨迹' }
]

const exampleQuestions = [
  '分析最近社零数据走势，识别异常变化，并给出有数据依据的分析建议。',
  '基于现有历史数据预测未来三个月社零走势，展示预测结果及模型评估信息。',
  '分析用户流失预测结果，展示风险分布、主要影响特征和需要注意的模型限制。'
]

// ==================== 首页右侧经营洞察（真实接口） ====================
const hero = ref({ latest_macro: { date: '', value: null, yoy: null }, churn: { total: null, label_rate: null }, forecast_metrics: null })
const heroForecast = ref(null)
const heroStatus = ref('loading') // loading | ready | offline

const trendClass = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : '')
const truncate = (s, n) => (s && s.length > n ? s.slice(0, n) + '…' : (s || ''))

const loadHeroInsight = async () => {
  heroStatus.value = 'loading'
  try {
    const [ov, fc] = await Promise.all([
      axios.get(`${API_BASE}/api/v1/overview`),
      axios.get(`${API_BASE}/api/v1/forecast`)
    ])
    if (ov.data && ov.data.data) hero.value = ov.data.data
    heroForecast.value = fc.data
    heroStatus.value = 'ready'
    nextTick(() => renderHeroTrendChart())
  } catch (e) {
    hero.value = { latest_macro: { date: '', value: null, yoy: null }, churn: { total: null, label_rate: null }, forecast_metrics: null }
    heroForecast.value = null
    const chart = echarts.getInstanceByDom(document.getElementById('heroTrendChart'))
    chart?.clear()
    heroStatus.value = 'offline'
  }
}

const renderHeroTrendChart = () => {
  const dom = document.getElementById('heroTrendChart')
  if (!dom || !heroForecast.value) return
  const chart = initChart(dom)
  if (!chart) return
  const d = heroForecast.value
  const H = d.historical_dates.length
  const N = 18 // 仅展示最近 18 个月历史，保持首屏简洁
  const start = Math.max(0, H - N)
  const histDates = d.historical_dates.slice(start)
  const histVals = d.historical_values.slice(start)
  const F = d.forecast_dates.length
  const lastHist = histVals[histVals.length - 1]
  const cats = [...histDates, ...d.forecast_dates]
  const histLine = [...histVals, ...Array(F).fill(null)]
  const fcLine = Array(histVals.length).fill(null)
  fcLine[histVals.length - 1] = lastHist
  d.forecast_values.forEach(v => fcLine.push(v))
  const ciLower = Array(histVals.length).fill(null)
  ciLower[histVals.length - 1] = lastHist
  d.lower_bound.forEach(v => ciLower.push(v))
  const ciBand = Array(histVals.length).fill(null)
  ciBand[histVals.length - 1] = 0
  d.upper_bound.forEach((u, i) => ciBand.push(Number((u - d.lower_bound[i]).toFixed(1))))
  const anomalyData = (d.anomalies || []).map(a => { const idx = histDates.indexOf(a.date); return idx >= 0 ? [idx, a.value] : null }).filter(Boolean)

  chart.setOption({
    color: ['#2451E6', '#F2552C'],
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(25,24,22,0.92)', borderWidth: 0, textStyle: { color: '#fff', fontSize: 12 }, extraCssText: 'border-radius:8px;' },
    grid: { left: 8, right: 8, top: 24, bottom: 6, containLabel: true },
    xAxis: { type: 'category', data: cats, boundaryGap: false, axisLine: { lineStyle: { color: '#E8E3DA' } }, axisTick: { show: false }, axisLabel: { color: '#8A857B', interval: Math.ceil(cats.length / 8), hideOverlap: true, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#8A857B', fontSize: 10, formatter: (v) => (v / 10000).toFixed(1) + '万' }, splitLine: { lineStyle: { color: '#F0ECE4', type: 'dashed' } } },
    series: [
      { name: '历史真实值', type: 'line', data: histLine, symbol: 'none', smooth: false, lineStyle: { width: 2, color: '#2451E6' }, areaStyle: { color: 'rgba(36,81,230,0.05)' } },
      { name: '预测值', type: 'line', data: fcLine, symbol: 'circle', symbolSize: 5, lineStyle: { width: 2, color: '#F2552C', type: 'dashed' }, itemStyle: { color: '#F2552C' } },
      { name: '置信区间下界(占位)', type: 'line', data: ciLower, stack: 'ci', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, emphasis: { disabled: true } },
      { name: '95% 置信区间', type: 'line', data: ciBand, stack: 'ci', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(242,85,44,0.14)' }, emphasis: { disabled: true } },
      { name: '异常点', type: 'scatter', data: anomalyData, symbolSize: 8, itemStyle: { color: '#F2552C', borderColor: '#fff', borderWidth: 1.5 }, z: 10 }
    ]
  }, true)
}

// ==================== 分析状态（首页与 AI Agent 共用） ====================
const query = ref(exampleQuestions[0])
const homeQuery = ref('')
const report = ref('')
const loading = ref(false)
const agentError = ref('')
const homeError = ref('')
const imageName = ref('')
const imageBase64 = ref('')
const intent = ref('')
const intentReason = ref('')
const sections = ref([])
const execution = ref([])
const agentData = ref({ macro: [], forecast: null, churn: null })
const reportMeta = ref({ status: '', reason: '' })
const kbFragments = ref('')
const execCollapse = ref(['intent', 'tools'])

const sectionContent = (title) => {
  const sec = sections.value.find(s => s.title === title)
  return sec ? sec.content : ''
}
const otherSections = computed(() => {
  const exclude = ['【核心结论】']
  return sections.value.filter(s => !exclude.includes(s.title))
})

const runAnalysis = async (q) => {
  if (!q || !q.trim()) { ElMessage.warning('请输入分析问题'); return }
  if (loading.value) return
  query.value = q
  loading.value = true
  agentError.value = ''
  homeError.value = ''
  report.value = ''
  intent.value = ''; intentReason.value = ''; sections.value = []; execution.value = []
  agentData.value = { macro: [], forecast: null, churn: null }
  reportMeta.value = { status: '', reason: '' }
  kbFragments.value = ''

  try {
    const response = await axios.post(`${API_BASE}/api/v1/analyze`, { query: q, image_base64: imageBase64.value })
    const d = response.data
    report.value = d.report
    intent.value = d.intent
    intentReason.value = d.intent_reason
    sections.value = d.sections || []
    execution.value = d.execution || []
    agentData.value = d.data || { macro: [], forecast: null, churn: null }
    reportMeta.value = { status: d.generation_status || 'success', reason: d.fallback_reason || '' }
    kbFragments.value = d.kb_fragments || ''

    renderResultCharts()
  } catch (error) {
    console.warn('分析请求失败:', error)
    const msg = '服务连接失败，请确认后端服务已启动（http://127.0.0.1:8003）。'
    agentError.value = msg
    homeError.value = msg
    reportMeta.value = { status: 'failed', reason: '无法连接后端服务' }
  } finally {
    loading.value = false
  }
}

const submitHome = () => runAnalysis(homeQuery.value)
const submitScenario = (s) => { homeQuery.value = s.question; runAnalysis(s.question) }
const submitExample = (ex) => { homeQuery.value = ex.q; runAnalysis(ex.q) }
const submitAgent = () => runAnalysis(query.value)

const onHeroKeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submitHome()
  }
}

const renderResultCharts = () => {
  nextTick(() => {
    if (activeView.value === 'home') {
      if (agentData.value.forecast) renderForecastChart(document.getElementById('homeForecastChart'), agentData.value.forecast)
      if (agentData.value.churn) renderRiskChart(document.getElementById('homeRiskChart'), agentData.value.churn.risk_distribution)
    } else if (activeView.value === 'agent') {
      if (agentData.value.forecast) renderForecastChart(document.getElementById('agentForecastChart'), agentData.value.forecast)
      if (agentData.value.churn) {
        renderRiskChart(document.getElementById('agentRiskChart'), agentData.value.churn.risk_distribution)
        renderFeatureChart(document.getElementById('agentFeatureChart'), agentData.value.churn.feature_importance)
      }
    }
  })
}

const handleImageUpload = (uploadFile) => {
  imageName.value = uploadFile.name
  const reader = new FileReader()
  reader.readAsDataURL(uploadFile.raw)
  reader.onload = () => { imageBase64.value = reader.result.split(',')[1] }
}
const exportReport = () => window.print()
const sendFeedback = async (type) => {
  try {
    await axios.post(`${API_BASE}/api/v1/feedback`, { query: query.value, feedback: type, report: report.value })
    ElMessage.success('感谢反馈')
  } catch (error) { console.error(error); ElMessage.error('反馈提交失败，请稍后重试') }
}

// ==================== 工具标签 / 状态 / 风险映射 ====================
const TOOL_LABELS = {
  intent_recognition: '任务理解',
  rag_search: '知识检索',
  query_macro_sqlite: '数据查询',
  forecast_timeseries: '趋势预测',
  predict_churn_batch: '流失预测',
  predict_churn_lightgbm: '流失预测',
  evaluate_ab_test: 'A/B 检验',
  report_generation: '报告生成'
}
const getToolLabel = (name) => TOOL_LABELS[name] || name
const getStatusText = (status) => ({ success: '成功', failed: '失败', fallback: '降级', not_configured: '未接入' }[status] || status)
const getExecTagType = (row) => {
  if (row.status === 'success') return 'primary'
  if (row.status === 'fallback') return 'warning'
  if (row.status === 'not_configured') return 'info'
  return 'danger'
}

const FEATURE_LABELS = {
  recency_days: '最近购买天数', frequency: '购买频次', monetary: '累计消费金额',
  avg_amount: '平均客单价', age: '年龄', city_tier_二线: '二线城市', city_tier_三线: '三线城市'
}
const featureLabel = (f) => FEATURE_LABELS[f] || f
const getRiskTagType = (level) => ({ '低风险': 'info', '中风险': 'primary', '高风险': 'warning', '极高风险': 'danger' }[level] || 'info')
const getRiskAction = (level) => {
  if (level === '低风险') return '持续观察'
  if (level === '中风险') return '关注复购'
  if (level === '高风险') return '纳入召回名单'
  return '优先人工跟进'
}

// ==================== 图表渲染 ====================
function initChart(dom) {
  if (!dom) return null
  let inst = echarts.getInstanceByDom(dom)
  if (!inst) inst = echarts.init(dom)
  return inst
}

const renderForecastChart = (dom, d) => {
  const chart = initChart(dom)
  if (!chart || !d) return
  const H = d.historical_dates.length
  const F = d.forecast_dates.length
  const lastHist = d.historical_values[H - 1]
  const categories = [...d.historical_dates, ...d.forecast_dates]
  const historicalLine = [...d.historical_values, ...Array(F).fill(null)]
  const forecastLine = Array(H).fill(null)
  forecastLine[H - 1] = lastHist
  d.forecast_values.forEach(v => forecastLine.push(v))
  const ciLower = Array(H).fill(null)
  ciLower[H - 1] = lastHist
  d.lower_bound.forEach(v => ciLower.push(v))
  const ciBand = Array(H).fill(null)
  ciBand[H - 1] = 0
  d.upper_bound.forEach((u, i) => ciBand.push(Number((u - d.lower_bound[i]).toFixed(1))))
  const anomalyData = (d.anomalies || []).map(a => { const idx = d.historical_dates.indexOf(a.date); return idx >= 0 ? [idx, a.value] : null }).filter(Boolean)

  chart.setOption({
    color: ['#2451E6', '#F2552C'],
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(25,24,22,0.92)', borderWidth: 0, textStyle: { color: '#fff', fontSize: 12 }, extraCssText: 'border-radius:8px;' },
    legend: { data: ['历史真实值', '预测值', '异常点'], bottom: 0, left: 'center', itemWidth: 16, itemHeight: 9, textStyle: { color: '#8A857B', fontSize: 12 } },
    grid: { left: '3%', right: '4%', top: 40, bottom: 40, containLabel: true },
    xAxis: { type: 'category', data: categories, boundaryGap: false, axisLine: { lineStyle: { color: '#E8E3DA' } }, axisTick: { show: false }, axisLabel: { color: '#8A857B', interval: Math.ceil(categories.length / 12), hideOverlap: true } },
    yAxis: { type: 'value', name: '亿元', scale: true, axisLabel: { color: '#8A857B' }, splitLine: { lineStyle: { type: 'dashed', color: '#F0ECE4' } } },
    series: [
      { name: '历史真实值', type: 'line', data: historicalLine, symbol: 'none', lineStyle: { width: 2.5, color: '#2451E6' }, areaStyle: { color: 'rgba(36,81,230,0.05)' } },
      { name: '预测值', type: 'line', data: forecastLine, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2.5, color: '#F2552C', type: 'dashed' }, itemStyle: { color: '#F2552C' } },
      { name: '置信区间下界(占位)', type: 'line', data: ciLower, stack: 'ci', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, emphasis: { disabled: true } },
      { name: '95% 置信区间', type: 'line', data: ciBand, stack: 'ci', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(242,85,44,0.16)' }, emphasis: { disabled: true } },
      { name: '异常点', type: 'scatter', data: anomalyData, symbolSize: 9, itemStyle: { color: '#F2552C', borderColor: '#fff', borderWidth: 1.5 }, z: 10 }
    ]
  }, true)
}

const renderRiskChart = (dom, dist) => {
  const chart = initChart(dom)
  if (!chart || !dist) return
  const colors = { '低风险': '#B9C4E6', '中风险': '#2451E6', '高风险': '#E8923A', '极高风险': '#F2552C' }
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: 'rgba(25,24,22,0.92)', borderWidth: 0, textStyle: { color: '#fff', fontSize: 12 }, extraCssText: 'border-radius:8px;' },
    grid: { left: '8%', right: '6%', top: 20, bottom: 30, containLabel: true },
    xAxis: { type: 'category', data: dist.map(d => d.level), axisLine: { lineStyle: { color: '#E8E3DA' } }, axisTick: { show: false }, axisLabel: { color: '#8A857B' } },
    yAxis: { type: 'value', name: '人数', axisLabel: { color: '#8A857B' }, splitLine: { lineStyle: { type: 'dashed', color: '#F0ECE4' } } },
    series: [{ type: 'bar', data: dist.map(d => ({ value: d.count, itemStyle: { color: colors[d.level] || '#2451E6' } })), barMaxWidth: 48, borderRadius: [6, 6, 0, 0], label: { show: true, position: 'top', color: '#4B4740', formatter: '{c}' } }]
  }, true)
}

const renderFeatureChart = (dom, fi) => {
  const chart = initChart(dom)
  if (!chart || !fi) return
  const top = (fi || []).slice(0, 7).slice().reverse()
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: 'rgba(25,24,22,0.92)', borderWidth: 0, textStyle: { color: '#fff', fontSize: 12 }, extraCssText: 'border-radius:8px;' },
    grid: { left: '24%', right: '8%', top: 10, bottom: 30, containLabel: true },
    xAxis: { type: 'value', name: '重要性', axisLabel: { color: '#8A857B' }, splitLine: { lineStyle: { type: 'dashed', color: '#F0ECE4' } } },
    yAxis: { type: 'category', data: top.map(f => featureLabel(f.feature)), axisLine: { lineStyle: { color: '#E8E3DA' } }, axisTick: { show: false }, axisLabel: { color: '#4B4740' } },
    series: [{ type: 'bar', data: top.map(f => f.importance), barMaxWidth: 20, itemStyle: { color: '#2451E6', borderRadius: [0, 6, 6, 0] }, label: { show: true, position: 'right', color: '#8A857B', formatter: (p) => Number(p.value).toFixed(3) } }]
  }, true)
}

const renderDemoChart = (dom) => {
  const chart = initChart(dom)
  if (!chart) return
  const days = Array.from({ length: 30 }, (_, i) => `${i + 1}日`)
  const values = Array.from({ length: 30 }, (_, i) => Math.round((120 - i * 0.9 + Math.sin(i / 2.5) * 4) * 10) / 10)
  chart.setOption({
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(25,24,22,0.92)', borderWidth: 0, textStyle: { color: '#fff', fontSize: 12 }, extraCssText: 'border-radius:8px;' },
    grid: { left: '3%', right: '4%', top: 20, bottom: 30, containLabel: true },
    xAxis: { type: 'category', data: days, boundaryGap: false, axisLine: { lineStyle: { color: '#E8E3DA' } }, axisTick: { show: false }, axisLabel: { color: '#8A857B', interval: 4 } },
    yAxis: { type: 'value', name: '销售额', axisLabel: { color: '#8A857B' }, splitLine: { lineStyle: { type: 'dashed', color: '#F0ECE4' } } },
    series: [{ name: '销售额', type: 'line', data: values, symbol: 'none', smooth: true, lineStyle: { width: 3, color: '#2451E6' }, areaStyle: { color: 'rgba(36,81,230,0.08)' } }]
  }, true)
}

// ==================== 数据分析页：总览 ====================
const overview = ref({ latest_macro: { date: '', value: null, yoy: null }, churn: { total: null, label_rate: null }, forecast_metrics: null, model_eval: { auc: null, ks: null } })
const overviewStatus = ref('loading')
const loadOverview = async () => {
  overviewStatus.value = 'loading'
  try {
    const { data } = await axios.get(`${API_BASE}/api/v1/overview`)
    if (!data.data) throw new Error('总览接口未返回数据')
    overview.value = data.data
    overviewStatus.value = 'ready'
  } catch (e) {
    overview.value = { latest_macro: { date: '', value: null, yoy: null }, churn: { total: null, label_rate: null }, forecast_metrics: null, model_eval: { auc: null, ks: null } }
    overviewStatus.value = 'offline'
    console.warn('加载数据总览失败:', e)
  }
}

// ==================== 数据分析页：流失预警 ====================
const churn = ref({})
const churnStatus = ref('loading')
const churnLoading = ref(false)
const riskFilter = ref('')
const selectedUsers = ref([])
const recallLoading = ref(false)
const recallDialogVisible = ref(false)
const recallResult = ref({ task_id: null, user_count: 0 })
const filteredChurnUsers = computed(() => {
  const list = (churn.value.top_risk_users || []).slice()
  return riskFilter.value ? list.filter(r => r.risk_level === riskFilter.value) : list
})
const churnRiskCount = (level) => { const i = (churn.value.risk_distribution || []).find(d => d.level === level); return i ? i.count : 0 }
const churnTopFeature = () => { const fi = churn.value.feature_importance || []; return fi.length ? featureLabel(fi[0].feature) : '—' }

const loadChurn = async () => {
  churnStatus.value = 'loading'
  churnLoading.value = true
  try {
    const { data } = await axios.get(`${API_BASE}/api/v1/churn/predict`, { params: { top_n: 100 } })
    churn.value = data.data || {}
    churnStatus.value = 'ready'
    nextTick(() => {
      renderRiskChart(document.getElementById('riskChart'), churn.value.risk_distribution)
      renderFeatureChart(document.getElementById('featureChart'), churn.value.feature_importance)
    })
  } catch (e) {
    console.warn('加载流失预测失败:', e)
    ElMessage.error('流失预测数据加载失败')
    churn.value = {}
    churnStatus.value = 'offline'
    echarts.getInstanceByDom(document.getElementById('riskChart'))?.clear()
    echarts.getInstanceByDom(document.getElementById('featureChart'))?.clear()
  }
  finally { churnLoading.value = false }
}
const handleSelectionChange = (rows) => { selectedUsers.value = rows }
const createRecallTask = async () => {
  if (selectedUsers.value.length === 0) { ElMessage.warning('请先勾选需要操作的用户'); return }
  recallLoading.value = true
  try {
    const user_ids = selectedUsers.value.map(r => r.user_id)
    const { data } = await axios.post(`${API_BASE}/api/v1/churn/recall`, { user_ids })
    recallResult.value = data.data
    recallDialogVisible.value = true
  } catch (e) { console.error(e); ElMessage.error('召回任务创建失败，请稍后重试') }
  finally { recallLoading.value = false }
}

// ==================== 智能报告：反馈 ====================
const feedbackStats = ref({ total: 0, up_count: 0, down_count: 0, up_rate: 0 })
const feedbackRecords = ref([])
const feedbackTotal = ref(0)
const feedbackFilter = ref('')
const feedbackPage = ref(1)
const feedbackPageSize = ref(10)
const feedbackLoading = ref(false)
const feedbackDetailVisible = ref(false)
const feedbackDetail = ref(null)
const getFeedbackTagType = (fb) => (fb === 'up' ? 'primary' : 'danger')
const getFeedbackLabel = (fb) => (fb === 'up' ? '点赞' : '点踩')
const loadFeedbackStats = async () => {
  try { const { data } = await axios.get(`${API_BASE}/api/v1/feedback/stats`); feedbackStats.value = data.data || { total: 0, up_count: 0, down_count: 0, up_rate: 0 } }
  catch (e) { console.error('加载反馈统计失败:', e) }
}
const loadFeedbackRecords = async () => {
  feedbackLoading.value = true
  try {
    const params = { page: feedbackPage.value, page_size: feedbackPageSize.value }
    if (feedbackFilter.value) params.feedback = feedbackFilter.value
    const { data } = await axios.get(`${API_BASE}/api/v1/feedback`, { params })
    const d = data.data || { records: [], total: 0 }
    feedbackRecords.value = d.records; feedbackTotal.value = d.total
  } catch (e) { console.error('加载反馈记录失败:', e); feedbackRecords.value = []; feedbackTotal.value = 0 }
  finally { feedbackLoading.value = false }
}
const refreshFeedback = () => { loadFeedbackStats(); loadFeedbackRecords() }
const handleFeedbackFilterChange = () => { feedbackPage.value = 1; loadFeedbackRecords() }
const handleFeedbackPageChange = (p) => { feedbackPage.value = p; loadFeedbackRecords() }
const handleFeedbackSizeChange = (s) => { feedbackPageSize.value = s; feedbackPage.value = 1; loadFeedbackRecords() }
const openFeedbackDetail = (row) => { feedbackDetail.value = row; feedbackDetailVisible.value = true }

// ==================== 宏图初始化 ====================
const initMacroChart = async () => {
  const chartDom = document.getElementById('macroChart')
  if (!chartDom) return
  const myChart = initChart(chartDom)
  myChart.showLoading({ text: '加载预测数据...', color: '#2451E6', textColor: '#8A857B', maskColor: 'rgba(255,255,255,0.6)' })
  try {
    const { data } = await axios.get(`${API_BASE}/api/v1/forecast`)
    myChart.hideLoading()
    renderForecastChart(chartDom, data)
    if (data.historical_dates && data.historical_dates.length) {
      macroRange.value = `${data.historical_dates[0]} 至 ${data.historical_dates[data.historical_dates.length - 1]}`
    }
  } catch (error) {
    console.warn('预测接口调用失败:', error)
    myChart.hideLoading()
    myChart.clear()
    myChart.setOption({ title: { text: '预测服务暂不可用', subtext: '请确认后端 FastAPI 服务已启动（http://127.0.0.1:8003）', left: 'center', top: 'middle', textStyle: { fontSize: 16, color: '#8A857B' }, subtextStyle: { fontSize: 12, color: '#B6B1A8' } } })
  }
}

const checkHealth = async () => {
  try { const { data } = await axios.get(`${API_BASE}/health`, { timeout: 4000 }); backendOnline.value = data.status === 'ok' }
  catch (e) { backendOnline.value = false }
}

onMounted(() => {
  window.addEventListener('resize', () => {
    document.querySelectorAll('[id$="Chart"]').forEach(dom => { const inst = echarts.getInstanceByDom(dom); if (inst) inst.resize() })
  })
  checkHealth()
  loadOverview()
  loadHeroInsight()
})

// 示例区域展开时渲染演示图表（默认折叠，避免首屏占用）
watch(demoCollapse, (val) => {
  if (val.includes('demo')) {
    nextTick(() => {
      const dom = document.getElementById('demoChart')
      if (!dom) return
      const inst = echarts.getInstanceByDom(dom)
      if (inst) inst.resize()
      else renderDemoChart(dom)
    })
  }
})

// 导航：切换视图并按需渲染图表 / 加载数据
const goNav = (key) => {
  activeView.value = key
  nextTick(() => {
    if (key === 'data') {
      if (dataTab.value === 'macro') initMacroChart()
      else if (!churn.value.total) loadChurn()
    } else if (key === 'report') {
      refreshFeedback()
    } else if (key === 'agent' && report.value) {
      renderResultCharts()
    } else if (key === 'home' && report.value) {
      renderResultCharts()
    }
  })
}

// 数据分析页 tab 切换
watch(dataTab, (tab) => {
  if (activeView.value !== 'data') return
  nextTick(() => {
    if (tab === 'macro') {
      initMacroChart()
    } else {
      if (!churn.value.total) loadChurn()
      else {
        renderRiskChart(document.getElementById('riskChart'), churn.value.risk_distribution)
        renderFeatureChart(document.getElementById('featureChart'), churn.value.feature_importance)
      }
    }
  })
})
</script>

<style scoped>
.app-shell { min-height: 100vh; background: var(--bg); color: var(--ink); }

/* ===== 顶部导航 ===== */
.topbar { position: sticky; top: 0; z-index: 50; background: rgba(250, 248, 243, 0.86); backdrop-filter: blur(14px); border-bottom: 1px solid var(--line-soft); }
.topbar-inner { max-width: 1200px; margin: 0 auto; height: 64px; padding: 0 28px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.brand { display: flex; align-items: center; gap: 11px; border: none; background: none; cursor: pointer; padding: 0; text-align: left; }
.brand-mark { width: 34px; height: 34px; border-radius: 9px; background: var(--ink); color: #fff; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
.brand-mark.small { width: 26px; height: 26px; border-radius: 7px; }
.brand-text { display: flex; flex-direction: column; line-height: 1.2; }
.brand-name { font-size: 15px; font-weight: 700; letter-spacing: -0.2px; color: var(--ink); }
.brand-tag { font-size: 11px; color: var(--ink-3); margin-top: 2px; }
.nav-links { display: flex; align-items: center; gap: 2px; margin-left: auto; }
.nav-link { border: none; background: none; padding: 7px 13px; border-radius: 8px; font-size: 14px; color: var(--ink-2); cursor: pointer; transition: color 0.15s, background 0.15s; }
.nav-link:hover { color: var(--ink); background: rgba(25,24,22,0.05); }
.nav-link.active { color: var(--accent); background: var(--accent-soft); font-weight: 600; }
.nav-right { display: flex; align-items: center; }
.nav-status { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; color: var(--ink-2); padding: 6px 12px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface); }
.nav-status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.nav-status.offline .nav-status-dot { background: var(--coral); box-shadow: 0 0 0 3px var(--coral-soft); }

.page-container { max-width: 1200px; margin: 0 auto; padding: 0 28px 88px; }
.page-view { padding-top: 36px; }
.home-view { padding-top: 40px; }

/* ===== Hero ===== */
.hero { position: relative; overflow: hidden; }
.hero::before { content: ''; position: absolute; inset: 0; background-image: radial-gradient(rgba(25,24,22,0.05) 1px, transparent 1px); background-size: 24px 24px; pointer-events: none; opacity: 0.5; }
.hero-inner { position: relative; display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 56px; align-items: center; padding: 28px 0 8px; }

.hero-eyebrow { display: inline-flex; align-items: center; gap: 9px; font-size: 13px; letter-spacing: 0.12em; color: var(--ink-2); margin-bottom: 26px; }
.eyebrow-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--coral); }
.hero-title { font-family: var(--font-serif); font-size: clamp(40px, 5.6vw, 66px); font-weight: 600; line-height: 1.14; letter-spacing: -0.02em; margin: 0 0 22px; color: var(--ink); }
.hero-desc { font-size: 17px; line-height: 1.7; color: var(--ink-2); margin: 0 0 38px; max-width: 460px; }

.hero-ask { max-width: 560px; }
.ask-box { display: flex; align-items: flex-end; gap: 10px; padding: 12px 12px 12px 18px; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; box-shadow: var(--shadow-sm); transition: border-color 0.2s, box-shadow 0.2s; }
.ask-box:focus-within { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft), var(--shadow-sm); }
.ask-icon { color: var(--ink-3); font-size: 18px; flex-shrink: 0; margin-bottom: 6px; display: inline-flex; }
.hero-input { flex: 1; border: none; outline: none; resize: none; font-size: 15px; line-height: 1.6; color: var(--ink); background: transparent; font-family: var(--font-sans); }
.hero-input::placeholder { color: var(--ink-3); }
.hero-submit { height: 44px; padding: 0 22px; border-radius: 11px; font-size: 14px; font-weight: 600; }
.ask-meta { display: flex; align-items: center; gap: 14px; margin-top: 12px; min-height: 20px; }
.ask-hint { font-size: 12px; color: var(--ink-3); }
.ask-error { font-size: 13px; color: var(--coral); }
.ask-error a { color: var(--coral); cursor: pointer; text-decoration: underline; }

.hero-examples { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin-top: 26px; }
.examples-label { font-size: 12px; color: var(--ink-3); margin-right: 4px; }
.example-chip { border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); font-size: 13px; padding: 8px 14px; border-radius: 999px; cursor: pointer; transition: all 0.16s; font-family: inherit; }
.example-chip:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); transform: translateY(-1px); }

/* 右侧经营洞察面板 */
.hero-panel { position: relative; background: var(--surface); border: 1px solid var(--line); border-radius: 18px; box-shadow: var(--shadow-md); padding: 24px 24px 20px; overflow: hidden; }
.hero-panel::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent); }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.panel-title { font-size: 17px; font-weight: 700; letter-spacing: -0.2px; }
.panel-sub { font-size: 12px; color: var(--ink-3); margin-top: 3px; }
.panel-source { font-size: 11px; color: var(--ink-3); padding: 5px 10px; border: 1px solid var(--line); border-radius: 999px; white-space: nowrap; }

.panel-kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0; margin-bottom: 20px; }
.panel-kpi { padding: 0 16px; border-left: 1px solid var(--line-soft); }
.panel-kpi:first-child { padding-left: 0; border-left: none; }
.kpi-label { font-size: 12px; color: var(--ink-3); margin-bottom: 8px; }
.kpi-value { font-family: var(--font-mono); font-size: 22px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); }
.kpi-value.up { color: var(--accent); }
.kpi-value.down { color: var(--coral); }
.kpi-unit { font-family: var(--font-sans); font-size: 12px; font-weight: 500; color: var(--ink-3); margin-left: 3px; }
.kpi-meta { font-size: 11px; color: var(--ink-3); margin-top: 6px; }

.panel-chart-wrap { position: relative; height: 200px; margin-bottom: 18px; }
.panel-chart { width: 100%; height: 100%; }
.panel-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 13px; color: var(--ink-3); background: var(--surface); }

.panel-insight { display: flex; gap: 12px; padding: 14px 16px; background: var(--surface-warm); border: 1px solid var(--line-soft); border-radius: 12px; }
.insight-tag { flex-shrink: 0; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; color: var(--accent); background: var(--accent-soft); padding: 4px 9px; border-radius: 6px; height: fit-content; }
.insight-text { margin: 0; font-size: 13px; line-height: 1.65; color: var(--ink-2); }
.insight-text.muted { color: var(--ink-3); }

/* ===== 通用段落 ===== */
.block { margin-top: 84px; }
.block--workflow { margin-top: 96px; }
.block-head { max-width: 640px; margin-bottom: 34px; }
.block-kicker { font-size: 12px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent); margin-bottom: 14px; }
.block-title { font-family: var(--font-serif); font-size: clamp(26px, 3vw, 34px); font-weight: 600; line-height: 1.25; letter-spacing: -0.01em; margin: 0 0 12px; color: var(--ink); }
.block-sub { font-size: 15px; line-height: 1.7; color: var(--ink-2); margin: 0; }

/* ===== 快捷场景 ===== */
.quick-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.quick-card { position: relative; display: flex; flex-direction: column; gap: 16px; text-align: left; padding: 22px 20px 18px; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; cursor: pointer; transition: all 0.2s; overflow: hidden; font-family: inherit; }
.quick-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: transparent; transition: background 0.2s; }
.quick-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-md); border-color: var(--line); }
.quick-card--coral::before, .quick-card--coral:hover::before { background: var(--coral); }
.quick-card--blue::before, .quick-card--blue:hover::before { background: var(--accent); }
.quick-card--amber::before, .quick-card--amber:hover::before { background: var(--amber); }
.quick-card--ink::before, .quick-card--ink:hover::before { background: var(--ink); }
.quick-top { display: flex; align-items: center; justify-content: space-between; }
.quick-index { font-family: var(--font-mono); font-size: 12px; color: var(--ink-3); letter-spacing: 0.08em; }
.quick-icon { width: 40px; height: 40px; border-radius: 11px; display: inline-flex; align-items: center; justify-content: center; font-size: 20px; }
.quick-card--coral .quick-icon { background: var(--coral-soft); color: var(--coral); }
.quick-card--blue .quick-icon { background: var(--accent-soft); color: var(--accent); }
.quick-card--amber .quick-icon { background: #FBF0E2; color: var(--amber); }
.quick-card--ink .quick-icon { background: #ECEAE4; color: var(--ink); }
.quick-title { font-size: 16px; font-weight: 700; letter-spacing: -0.1px; color: var(--ink); }
.quick-desc { font-size: 13px; line-height: 1.6; color: var(--ink-2); margin-top: 6px; }
.quick-foot { display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: 14px; border-top: 1px solid var(--line-soft); }
.quick-tag { font-size: 11px; color: var(--ink-3); }
.quick-arrow { color: var(--ink-3); font-size: 15px; transition: transform 0.2s, color 0.2s; display: inline-flex; }
.quick-card:hover .quick-arrow { transform: translateX(3px); color: var(--accent); }

/* ===== 工作流 ===== */
.workflow { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; padding: 8px 0 4px; }
.workflow-node { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 12px; text-align: center; }
.workflow-icon { width: 52px; height: 52px; border-radius: 16px; background: var(--surface); border: 1px solid var(--line); color: var(--accent); display: flex; align-items: center; justify-content: center; font-size: 22px; box-shadow: var(--shadow-sm); }
.workflow-label { font-size: 14px; font-weight: 700; color: var(--ink); }
.workflow-desc { font-size: 12px; color: var(--ink-3); line-height: 1.5; max-width: 140px; }
.workflow-arrow { color: var(--ink-3); font-size: 16px; padding-top: 18px; flex-shrink: 0; }
.routing { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 34px; padding: 16px 20px; background: var(--surface-warm); border: 1px solid var(--line-soft); border-radius: 12px; font-size: 13px; }
.routing-label { font-weight: 700; color: var(--ink); margin-right: 6px; }
.routing-item { color: var(--ink-2); }
.routing-sep { color: var(--ink-3); }

/* ===== 首页内联结果 ===== */
.home-result-section { margin-top: 84px; padding: 32px; background: var(--surface); border: 1px solid var(--line); border-radius: 18px; box-shadow: var(--shadow-md); }
.result-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
.result-status-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.intent-chip { font-size: 12px; color: var(--ink-2); background: var(--surface-warm); border: 1px solid var(--line-soft); padding: 5px 12px; border-radius: 999px; }
.conclusion { padding: 20px 22px; background: var(--surface-warm); border-left: 3px solid var(--accent); border-radius: 0 12px 12px 0; font-size: 15px; line-height: 1.85; color: var(--ink); margin-bottom: 24px; white-space: pre-wrap; }
.result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
.result-grid > .result-panel:only-child { grid-column: 1 / -1; }
.result-panel { padding: 18px; border: 1px solid var(--line); border-radius: 14px; }
.panel-title { font-size: 14px; font-weight: 700; margin-bottom: 12px; }
.chart-box { width: 100%; height: 300px; }
.process-block { margin-bottom: 24px; padding: 20px 22px; background: var(--surface-warm); border: 1px solid var(--line-soft); border-radius: 14px; }
.process-head { font-size: 14px; font-weight: 700; color: var(--ink); margin-bottom: 14px; }
.process-list { list-style: none; margin: 0; padding: 0; }
.process-step { display: flex; align-items: flex-start; gap: 13px; padding: 11px 0; border-bottom: 1px dashed var(--line); }
.process-step:last-child { border-bottom: none; padding-bottom: 0; }
.process-index { width: 24px; height: 24px; border-radius: 50%; background: var(--accent); color: #fff; font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
.process-index.failed, .process-index.fallback { background: var(--amber); }
.process-index.not_configured { background: var(--ink-3); }
.process-body { flex: 1; min-width: 0; }
.process-title { display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 700; color: var(--ink); }
.process-status { font-style: normal; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 999px; }
.process-status.st--success { color: var(--accent); background: var(--accent-soft); }
.process-status.st--fallback { color: var(--amber); background: #FBF0E2; }
.process-status.st--not_configured { color: var(--ink-3); background: #ECEAE4; }
.process-status.st--failed { color: var(--coral); background: var(--coral-soft); }
.process-summary { font-size: 12.5px; color: var(--ink-2); margin-top: 4px; line-height: 1.55; }
.process-duration { font-size: 12px; color: var(--ink-3); flex-shrink: 0; margin-top: 2px; font-family: var(--font-mono); }
.result-actions { display: flex; gap: 12px; }

/* ===== 示例 Demo（折叠降权） ===== */
.demo-section { margin-top: 32px; }
.demo-collapse { border: 1px solid var(--line); border-radius: 14px; background: var(--surface); overflow: hidden; }
.demo-collapse-title { display: flex; align-items: center; gap: 12px; }
.demo-collapse-name { font-size: 15px; font-weight: 700; color: var(--ink); }
.demo-card { display: grid; grid-template-columns: 1.4fr 1fr; gap: 28px; padding: 24px; }
.demo-title-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.demo-title { font-size: 17px; font-weight: 700; }
.demo-sub { font-size: 13px; color: var(--ink-3); margin-top: 2px; }
.demo-kpi { text-align: right; }
.demo-kpi-value { font-family: var(--font-mono); font-size: 30px; font-weight: 800; color: var(--coral); }
.demo-kpi-label { font-size: 12px; color: var(--ink-3); }
.demo-chart { width: 100%; height: 260px; }
.demo-ai-label { display: inline-block; font-size: 12px; font-weight: 700; color: var(--accent); background: var(--accent-soft); padding: 5px 10px; border-radius: 6px; margin-bottom: 16px; }
.demo-block { margin-bottom: 18px; }
.demo-block-title { font-size: 14px; font-weight: 700; margin-bottom: 8px; }
.demo-list { margin: 0; padding-left: 20px; font-size: 14px; color: var(--ink-2); line-height: 1.9; }

/* ===== 能力 + 知识库 ===== */
.ability-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.ability-card { padding: 26px 22px; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; transition: all 0.22s; }
.ability-card:hover { border-color: var(--accent); box-shadow: var(--shadow-md); transform: translateY(-3px); }
.ability-icon { width: 46px; height: 46px; border-radius: 13px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; font-size: 23px; margin-bottom: 18px; }
.ability-title { font-size: 16px; font-weight: 700; margin-bottom: 8px; }
.ability-desc { font-size: 13px; color: var(--ink-2); line-height: 1.7; }

.kb-strip { display: flex; align-items: center; gap: 20px; margin-top: 20px; padding: 22px 24px; background: var(--surface-warm); border: 1px solid var(--line-soft); border-radius: 16px; }
.kb-strip-icon { width: 46px; height: 46px; border-radius: 13px; background: var(--surface); border: 1px solid var(--line); color: var(--ink); display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; }
.kb-strip-body { flex: 1; min-width: 0; }
.kb-strip-title { font-size: 15px; font-weight: 700; margin-bottom: 6px; }
.kb-strip-text { margin: 0; font-size: 13px; line-height: 1.7; color: var(--ink-2); }
.data-note { margin-top: 20px; font-size: 12px; color: var(--ink-3); line-height: 1.7; }

/* ===== 状态 pill ===== */
.pill { display: inline-flex; align-items: center; font-size: 11px; font-weight: 700; letter-spacing: 0.02em; padding: 5px 12px; border-radius: 999px; white-space: nowrap; }
.pill--success { color: var(--accent); background: var(--accent-soft); }
.pill--fallback { color: var(--amber); background: #FBF0E2; }
.pill--failed { color: var(--coral); background: var(--coral-soft); }
.pill--sample { color: var(--ink-2); background: var(--surface-warm); border: 1px solid var(--line); }

/* ===== 底部 ===== */
.footer { margin-top: 96px; padding: 44px 0 20px; border-top: 1px solid var(--line); text-align: center; }
.footer-brand { display: flex; align-items: center; justify-content: center; gap: 9px; font-weight: 700; margin-bottom: 16px; }
.footer-tags { display: flex; align-items: center; justify-content: center; gap: 10px; font-size: 13px; color: var(--ink-3); margin-bottom: 14px; flex-wrap: wrap; }
.footer-note { font-size: 13px; color: var(--ink-3); }

/* ===== 通用页头 / 卡片（内页复用） ===== */
.page-title { font-family: var(--font-serif); font-size: 30px; font-weight: 600; letter-spacing: -0.01em; margin: 0 0 8px; }
.page-sub { font-size: 14px; color: var(--ink-2); margin: 0 0 28px; line-height: 1.7; }
.agent-hero { margin-bottom: 24px; }
.demo-notice { display: flex; justify-content: flex-end; margin-bottom: 16px; }
.kpi-row { margin-bottom: 20px; }
.kpi-card { border-radius: 14px; border: 1px solid var(--line); }
.kpi-title { font-size: 13px; color: var(--ink-3); margin-bottom: 8px; }
.kpi-value { font-family: var(--font-mono); font-size: 26px; font-weight: 800; color: var(--ink); margin-bottom: 6px; }
.kpi-trend { font-size: 12px; color: var(--ink-3); }
.kpi-trend.up { color: var(--accent); }
.kpi-trend.down { color: var(--coral); }
.chart-card { border-radius: 14px; border: 1px solid var(--line); margin-bottom: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; font-weight: 700; font-size: 15px; color: var(--ink); }
.chart-note { margin-top: 12px; font-size: 12px; color: var(--ink-3); text-align: right; }
.filter-bar { display: flex; align-items: center; gap: 24px; margin-bottom: 16px; }
.filter-item { display: flex; align-items: center; gap: 8px; }
.filter-label { font-size: 13px; color: var(--ink-2); }
.action-text { font-size: 13px; color: var(--ink-2); }
.batch-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.batch-info { font-size: 13px; color: var(--ink-2); }
.batch-info b { color: var(--amber); font-size: 15px; }
.recall-result { font-size: 15px; color: var(--ink-2); margin: 8px 0; }
.recall-result b { color: var(--coral); font-size: 18px; }
.recall-note { font-size: 13px; color: var(--ink-3); }
.pagination-bar { display: flex; justify-content: flex-end; margin-top: 16px; }
.feedback-detail { display: flex; flex-direction: column; gap: 12px; }
.detail-row { display: flex; align-items: flex-start; gap: 8px; font-size: 14px; color: var(--ink-2); }
.detail-label { font-size: 14px; font-weight: 600; color: var(--ink); }
.detail-report { max-height: 320px; overflow-y: auto; padding: 12px; background-color: var(--surface-warm); border-radius: 6px; white-space: pre-wrap; line-height: 1.7; font-size: 13px; color: var(--ink); }

/* Agent 页 */
.agent-input-card { border-radius: 16px; border: 1px solid var(--line); margin-bottom: 20px; }
.example-list { margin-bottom: 14px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.example-label { font-size: 13px; color: var(--ink-2); }
.example-tag { cursor: pointer; white-space: normal; height: auto; line-height: 1.5; padding: 6px 10px; }
.action-bar { display: flex; justify-content: space-between; align-items: center; margin-top: 16px; }
.upload { display: flex; align-items: center; gap: 10px; }
.image-name { color: var(--accent); font-size: 14px; }
.agent-error { margin-top: 12px; color: var(--coral); font-size: 14px; display: flex; align-items: center; gap: 8px; }
.agent-status-card { border-radius: 16px; margin-bottom: 20px; }
.agent-loading { display: flex; align-items: center; gap: 12px; color: var(--ink-2); font-size: 15px; padding: 8px 0; }
.agent-result-wrap { display: flex; flex-direction: column; gap: 16px; }
.report-status { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; flex-wrap: wrap; }
.result-card { border-radius: 16px; border: 1px solid var(--line); }
.core-card { border-left: 4px solid var(--accent); }
.section-text { white-space: pre-wrap; line-height: 1.85; color: var(--ink); font-size: 14px; }
.anomaly-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.anomaly-tag { font-size: 13px; }
.report-actions { display: flex; gap: 12px; }
.exec-text { font-size: 13px; color: var(--ink-2); line-height: 1.7; white-space: pre-wrap; }
.exec-block { border-left: 3px solid var(--line); padding-left: 12px; }
.exec-label { font-size: 13px; font-weight: 600; color: var(--ink); margin-bottom: 6px; }
.exec-code { margin: 0; padding: 10px 12px; background-color: #191816; color: #ECE9E2; border-radius: 8px; font-size: 12px; line-height: 1.6; overflow-x: auto; font-family: var(--font-mono); }

/* 知识库页 */
.kb-steps { margin: 0; padding-left: 20px; font-size: 14px; color: var(--ink-2); line-height: 2; }
.kb-steps code { background: var(--surface-warm); padding: 2px 6px; border-radius: 4px; font-size: 13px; }

/* ===== 响应式 ===== */
@media (max-width: 1080px) {
  .hero-inner { grid-template-columns: 1fr; gap: 36px; }
  .quick-grid { grid-template-columns: repeat(2, 1fr); }
  .ability-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 860px) {
  .brand-tag { display: none; }
  .nav-links { gap: 0; }
  .nav-link { padding: 7px 9px; font-size: 13px; }
  .workflow { flex-direction: column; gap: 4px; }
  .workflow-arrow { display: none; }
  .workflow-node { flex-direction: row; text-align: left; gap: 14px; width: 100%; }
  .workflow-desc { max-width: none; }
  .result-grid { grid-template-columns: 1fr; }
  .demo-card { grid-template-columns: 1fr; }
  .kb-strip { flex-direction: column; align-items: flex-start; }
}
@media (max-width: 620px) {
  .page-container { padding: 0 16px 64px; }
  .topbar-inner { min-height: 56px; height: auto; padding: 8px 16px; flex-wrap: wrap; row-gap: 4px; }
  .brand { flex: 0 0 auto; }
  .brand-name { white-space: nowrap; }
  .nav-links { order: 1; flex: 0 0 100%; width: 100%; margin-left: 0; overflow-x: auto; flex-wrap: nowrap; scrollbar-width: none; }
  .nav-links::-webkit-scrollbar { display: none; }
  .nav-link { flex: 0 0 auto; white-space: nowrap; }
  .nav-right { display: none; }
  .nav-status { display: none; }
  .hero-title { font-size: 38px; }
  .hero-desc { font-size: 15px; }
  .hero { padding: 0; }
  .panel-kpis { grid-template-columns: 1fr; gap: 12px; }
  .panel-kpi { padding: 0; border-left: none; }
  .quick-grid { grid-template-columns: 1fr; }
  .ability-grid { grid-template-columns: 1fr; }
  .home-result-section { padding: 20px; }
  .result-head { flex-direction: column; }
  .block { margin-top: 60px; }
  .block--workflow { margin-top: 68px; }
  .ask-box { flex-direction: column; align-items: stretch; }
  .hero-submit { width: 100%; }
}
</style>

<style>
/* ===== 设计令牌（暖纸白 · 深墨 · 钴蓝 · 珊瑚） ===== */
:root {
  --accent: #2451E6;
  --accent-strong: #1A3EC4;
  --accent-soft: #E9EEFD;
  --coral: #F2552C;
  --coral-soft: #FBE9E2;
  --amber: #E8923A;
  --bg: #F6F3ED;
  --surface: #FFFFFF;
  --surface-warm: #FBFAF6;
  --ink: #191816;
  --ink-2: #4B4740;
  --ink-3: #8A857B;
  --line: #E8E3DA;
  --line-soft: #F0ECE4;
  --shadow-sm: 0 1px 2px rgba(25, 24, 22, 0.04), 0 4px 12px rgba(25, 24, 22, 0.05);
  --shadow-md: 0 2px 4px rgba(25, 24, 22, 0.05), 0 14px 36px rgba(25, 24, 22, 0.08);
  --font-sans: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-serif: 'Noto Serif SC', 'Source Han Serif SC', 'Songti SC', 'STSong', 'SimSun', serif;
  --font-mono: 'SF Mono', 'Cascadia Mono', 'JetBrains Mono', Consolas, 'Courier New', monospace;

  /* Element Plus 主题对齐 */
  --el-color-primary: #2451E6;
  --el-color-primary-light-3: #5B7CEE;
  --el-color-primary-light-5: #8AA2F3;
  --el-color-primary-light-7: #B9C8F8;
  --el-color-primary-light-8: #D0DAFB;
  --el-color-primary-light-9: #E9EEFD;
  --el-color-primary-dark-2: #1A3EC4;
  --el-color-success: #2451E6;
  --el-color-success-light-3: #5B7CEE;
  --el-color-success-light-5: #8AA2F3;
  --el-color-success-light-7: #B9C8F8;
  --el-color-success-light-8: #D0DAFB;
  --el-color-success-light-9: #E9EEFD;
  --el-color-success-dark-2: #1A3EC4;
  --el-color-warning: #E8923A;
  --el-color-danger: #F2552C;
  --el-border-radius-base: 10px;
  --el-font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; text-rendering: optimizeLegibility; }

body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--font-sans); font-size: 14px; }

/* Element Plus 细节微调 */
.el-button--primary { font-weight: 600; }
.el-card { --el-card-border-color: var(--line); }
.el-tag { border-radius: 6px; }

@media print {
  body * { visibility: hidden; }
  .agent-result-wrap, .agent-result-wrap * { visibility: visible; }
  .agent-result-wrap { position: absolute; left: 0; top: 0; width: 100%; padding: 24px; }
}
</style>
