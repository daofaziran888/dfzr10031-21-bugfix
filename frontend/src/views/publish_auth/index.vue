<template>
  <section class="page" data-module="publish_auth">
    <header class="page-head">
      <div>
        <h2>发布授权预检</h2>
        <p class="page-desc">
          核算看板各图表引用数据域的发布授权：多域取授权交集、跨团队许可独立留痕、撤回显式阻断，
          并裁决组外组合页降级或收回独立交付。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reloadAll">刷新基础数据</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">数据域</span>
        <strong class="stat-value">{{ domains.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">生效中许可 / 已撤回</span>
        <strong class="stat-value">{{ activeLicenseCount }} / {{ revokedLicenseCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">累计签收</span>
        <strong class="stat-value">{{ signoffs.length }}</strong>
      </article>
    </div>

    <h3 class="section-title">① 基础数据：数据域、分组与来源许可</h3>
    <div class="grid-2">
      <div class="panel">
        <h4>数据域</h4>
        <table class="data-table compact">
          <thead><tr><th>数据域编号</th><th>名称</th><th>归属团队</th></tr></thead>
          <tbody>
            <tr v-for="d in domains" :key="d.数据域编号">
              <td>{{ d.数据域编号 }}</td><td>{{ d.数据域名称 }}</td><td>{{ d.归属团队 }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h4>用户分组</h4>
        <table class="data-table compact">
          <thead><tr><th>组编号</th><th>组名称</th><th>所属团队</th><th>共享类型</th></tr></thead>
          <tbody>
            <tr v-for="g in groups" :key="g.组编号">
              <td>{{ g.组编号 }}</td><td>{{ g.组名称 }}</td><td>{{ g.所属团队 }}</td>
              <td><span :class="['tag', g.共享类型 === '合作方共享' ? 'tag-warn' : 'tag-ok']">{{ g.共享类型 }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <h4>来源许可（合作方允许的起止日期与汇总级别）</h4>
      <table class="data-table compact">
        <thead>
          <tr>
            <th>许可编号</th><th>数据域</th><th>来源团队</th><th>共享范围</th><th>授权分组</th>
            <th>最高汇总级别</th><th>许可开始</th><th>许可结束</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="lic in licenses" :key="lic.id" :class="{ 'row-revoked': lic.许可状态 === '已撤回' }">
            <td>{{ lic.许可编号 }}</td>
            <td>{{ lic.数据域编号 }}</td>
            <td>{{ lic.来源团队 }}</td>
            <td>{{ lic.共享范围 }}</td>
            <td>{{ lic.授权分组编号 }}</td>
            <td>{{ lic.最高汇总级别 }}</td>
            <td>{{ lic.许可开始日期 }}</td>
            <td>{{ lic.许可结束日期 }}</td>
            <td>
              <span :class="['tag', lic.许可状态 === '已撤回' ? 'tag-danger' : 'tag-ok']">{{ lic.许可状态 }}</span>
            </td>
            <td>
              <button v-if="lic.许可状态 !== '已撤回'" class="link" type="button" @click="revoke(lic)">撤回许可</button>
              <span v-else class="muted">已留痕</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3 class="section-title">② 发布授权预检（多数据域授权交集）</h3>
    <div class="panel">
      <form class="filter-bar" @submit.prevent="runPrecheck">
        <label class="filter-item"><span>看板编号</span>
          <input v-model="precheckForm.看板编号" placeholder="如 DASH-COMBO-01" required />
        </label>
        <label class="filter-item"><span>请求人分组</span>
          <select v-model="precheckForm.请求人分组编号" required>
            <option value="" disabled>请选择分组</option>
            <option v-for="g in groups" :key="g.组编号" :value="g.组编号">{{ g.组名称 }}（{{ g.组编号 }}）</option>
          </select>
        </label>
        <label class="filter-item"><span>核对日期</span>
          <input v-model="precheckForm.核对日期" type="date" required />
        </label>
        <label class="filter-item"><span>请求汇总级别</span>
          <select v-model="precheckForm.请求汇总级别">
            <option>明细</option><option>地区级汇总</option><option>总量汇总</option>
          </select>
        </label>
        <button class="btn primary" type="submit">执行预检</button>
      </form>

      <div v-if="precheckResult" class="result-box">
        <div class="result-head">
          <span class="result-title">
            组合有效级别：<strong :class="precheckResult.组合有效汇总级别 === '无' ? 'text-danger' : 'text-ok'">
              {{ precheckResult.组合有效汇总级别 }}
            </strong>
            <span class="muted">（请求 {{ precheckResult.请求汇总级别 }}，{{ precheckResult.组合是否满足请求 ? '满足' : '不满足' }}）</span>
          </span>
          <span :class="['tag', precheckResult.是否存在撤回许可 ? 'tag-danger' : 'tag-ok']">
            {{ precheckResult.是否存在撤回许可 ? '含撤回许可（不隐藏）' : '无撤回' }}
          </span>
        </div>
        <p class="recommend">
          建议发布方式：<strong>{{ precheckResult.建议发布方式 }}</strong> —— {{ precheckResult.建议说明 }}
        </p>
        <table class="data-table compact">
          <thead>
            <tr><th>数据域</th><th>归属团队</th><th>有效级别</th><th>请求级别</th><th>是否满足</th><th>撤回</th><th>阻断原因 / 许可命中</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in precheckResult.数据域核算" :key="d.数据域编号">
              <td>{{ d.数据域编号 }}<br /><span class="muted">{{ d.数据域名称 }}</span></td>
              <td>{{ d.归属团队 }}</td>
              <td><strong :class="d.有效汇总级别 === '无' ? 'text-danger' : ''">{{ d.有效汇总级别 }}</strong></td>
              <td>{{ d.请求汇总级别 }}</td>
              <td>{{ d.该域是否满足请求 ? '满足' : '不满足' }}</td>
              <td>{{ d.是否存在撤回 ? '是' : '否' }}</td>
              <td class="detail-cell">
                <div v-if="d.阻断原因.length"><span v-for="(b, i) in d.阻断原因" :key="i" class="blocker">· {{ b }}<br /></span></div>
                <div class="muted">
                  归属团队命中：{{ formatEvals(d.归属团队命中许可) }}
                  <template v-if="d.非归属团队许可留痕.length">
                    <br />非归属团队留痕（不参与定级）：{{ formatEvals(d.非归属团队许可留痕) }}
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="row-actions" style="margin-top: 10px">
          <button class="btn primary" type="button" :disabled="precheckResult.组合有效汇总级别 === '无'"
                  @click="signoff(precheckResult.建议发布方式)">
            按建议签收（{{ precheckResult.建议发布方式 }}）
          </button>
          <button class="btn" type="button" @click="signoff('收回组合页并按数据域独立交付')">
            强制按数据域独立交付
          </button>
        </div>
      </div>
    </div>

    <h3 class="section-title">③ 同一账户访问核验：撤回后组合统计读取 + 旧签收回查</h3>
    <div class="panel">
      <form class="filter-bar" @submit.prevent="runVerify">
        <label class="filter-item"><span>组外账户分组</span>
          <select v-model="verifyForm.请求人分组编号" required>
            <option value="" disabled>请选择分组</option>
            <option v-for="g in groups" :key="g.组编号" :value="g.组编号">{{ g.组名称 }}</option>
          </select>
        </label>
        <label class="filter-item"><span>数据域</span>
          <select v-model="verifyForm.数据域编号" required>
            <option value="" disabled>请选择数据域</option>
            <option v-for="d in domains" :key="d.数据域编号" :value="d.数据域编号">{{ d.数据域名称 }}</option>
          </select>
        </label>
        <label class="filter-item"><span>请求级别</span>
          <select v-model="verifyForm.请求汇总级别">
            <option>明细</option><option>地区级汇总</option><option>总量汇总</option>
          </select>
        </label>
        <label class="filter-item"><span>核对日期</span>
          <input v-model="verifyForm.核对日期" type="date" required />
        </label>
        <button class="btn primary" type="submit">验证能否读取</button>
      </form>
      <div v-if="verifyResult" class="result-box">
        <p>
          读取结论：<strong :class="verifyResult.读取结论 === '允许读取' ? 'text-ok' : 'text-danger'">
            {{ verifyResult.读取结论 }}
          </strong>
          <span class="muted">（当前有效级别 {{ verifyResult.当前有效汇总级别 }}，
            {{ verifyResult.是否因撤回拒绝 ? '因撤回拒绝' : '非撤回原因' }}）</span>
        </p>
        <div v-if="verifyResult.阻断原因.length" class="muted">
          <span v-for="(b, i) in verifyResult.阻断原因" :key="i">· {{ b }}<br /></span>
        </div>
        <h4>旧签收依据回查（只追加，撤回后仍可查）</h4>
        <table v-if="verifyResult.旧签收依据.length" class="data-table compact">
          <thead><tr><th>签收编号</th><th>看板</th><th>组合交付级别</th><th>发布方式</th><th>签收时间</th><th>依据</th></tr></thead>
          <tbody>
            <tr v-for="s in verifyResult.旧签收依据" :key="s.签收编号">
              <td>{{ s.签收编号 }}</td><td>{{ s.看板编号 }}</td><td>{{ s.组合交付级别 }}</td>
              <td>{{ s.发布方式 }}</td><td>{{ s.签收时间 }}</td>
              <td class="muted">{{ formatBasis(s.签收依据) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">该分组暂无历史签收。</p>
      </div>
    </div>

    <h3 class="section-title">④ 用户组消费范围（只读页面与汇总数据范围）</h3>
    <div class="panel">
      <form class="filter-bar" @submit.prevent="loadConsumption">
        <label class="filter-item"><span>选择分组</span>
          <select v-model="consumptionGroup" required>
            <option value="" disabled>请选择分组</option>
            <option v-for="g in groups" :key="g.组编号" :value="g.组编号">{{ g.组名称 }}</option>
          </select>
        </label>
        <button class="btn primary" type="submit">计算消费范围</button>
        <button class="btn" type="button" @click="loadLastApproval">回查上次批准层级</button>
      </form>
      <div v-if="consumption" class="result-box">
        <p>组合只读页面：<strong>{{ consumption.组合只读页面 }}</strong>
          <span class="muted">（组合可接收最高级别 {{ consumption.组合可接收最高级别 }}）</span>
        </p>
        <table class="data-table compact">
          <thead><tr><th>数据域</th><th>可读最高级别</th><th>只读页面</th><th>含撤回</th></tr></thead>
          <tbody>
            <tr v-for="d in consumption.各数据域消费范围" :key="d.数据域编号">
              <td>{{ d.数据域编号 }} {{ d.数据域名称 }}</td>
              <td>{{ d.可读取最高级别 }}</td><td>{{ d.只读页面 }}</td><td>{{ d.是否含撤回 ? '是' : '否' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="lastApproval" class="result-box">
        <template v-if="lastApproval.是否有历史签收">
          <p>上次签收 {{ lastApproval.上次签收编号 }}（{{ lastApproval.上次签收时间 }}）：
            发布方式 <strong>{{ lastApproval.上次发布方式 }}</strong>，
            组合级别 <strong>{{ lastApproval.上次批准组合级别 }}</strong></p>
          <p class="muted">解除共享后再次申请可对照此数据层级；各域范围：
            {{ formatDeliver(lastApproval.上次各域交付范围) }}</p>
        </template>
        <p v-else class="muted">该分组对该看板暂无历史签收。</p>
      </div>
    </div>

    <h3 class="section-title">⑤ 已签收发布记录（只追加不改写）</h3>
    <div class="panel">
      <table class="data-table compact">
        <thead>
          <tr><th>签收编号</th><th>看板</th><th>分组</th><th>发布方式</th><th>组合级别</th><th>各域交付范围</th><th>含撤回</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in signoffs" :key="s.签收编号">
            <td>{{ s.签收编号 }}</td><td>{{ s.看板编号 }}</td><td>{{ s.授权分组编号 }}</td>
            <td>{{ s.发布方式 }}</td><td>{{ s.组合交付级别 }}</td>
            <td class="muted">{{ formatDeliver(s.各域交付范围) }}</td>
            <td>{{ s.是否含撤回许可 ? '是' : '否' }}</td><td>{{ s.签收时间 }}</td>
          </tr>
          <tr v-if="!signoffs.length"><td colspan="8" class="empty-state">暂无签收记录</td></tr>
        </tbody>
      </table>
    </div>

    <footer class="page-foot">
      <span>发布授权预检：来源许可与请求人分组双重校验，撤回结果在组合看板显式可见</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

const ENDPOINT = '/api/publish_auth'

type Row = Record<string, string | number | boolean | null>
interface EvalItem { 许可编号: string; 来源团队: string; 命中情况: string; 是否可用: boolean; 最高汇总级别: string }
interface DomainCalc {
  数据域编号: string
  数据域名称: string
  归属团队: string
  有效汇总级别: string
  请求汇总级别: string
  该域是否满足请求: boolean
  是否存在撤回: boolean
  阻断原因: string[]
  归属团队命中许可: EvalItem[]
  非归属团队许可留痕: EvalItem[]
  命中许可明细: EvalItem[]
}
interface PrecheckResult {
  看板编号: string
  组合有效汇总级别: string
  请求汇总级别: string
  组合是否满足请求: boolean
  是否存在撤回许可: boolean
  是否硬阻断: boolean
  建议发布方式: string
  建议说明: string
  数据域核算: DomainCalc[]
}
interface SignoffBasisItem { 数据域编号: string; 依据许可: string[] }
interface SignoffBasis {
  签收编号: string
  看板编号: string
  组合交付级别: string
  发布方式: string
  签收时间: string
  签收依据: SignoffBasisItem[]
}
interface VerifyResult {
  读取结论: string
  当前有效汇总级别: string
  是否因撤回拒绝: boolean
  阻断原因: string[]
  旧签收依据: SignoffBasis[]
}
interface ConsumptionScope {
  数据域编号: string
  数据域名称: string
  可读取最高级别: string
  只读页面: string
  是否含撤回: boolean
}
interface Consumption {
  组合只读页面: string
  组合可接收最高级别: string
  各数据域消费范围: ConsumptionScope[]
}
interface LastApproval {
  是否有历史签收: boolean
  上次签收编号?: string
  上次签收时间?: string
  上次发布方式?: string
  上次批准组合级别?: string
  上次各域交付范围?: Array<Record<string, string>>
}

const domains = ref<Row[]>([])
const groups = ref<Row[]>([])
const licenses = ref<Row[]>([])
const signoffs = ref<Row[]>([])
const errorMessage = ref('')

const today = new Date().toISOString().slice(0, 10)
const precheckForm = ref({
  看板编号: 'DASH-COMBO-01',
  请求人分组编号: 'GROUP-PARTNER-A',
  核对日期: today,
  请求汇总级别: '明细',
})
const verifyForm = ref({
  请求人分组编号: 'GROUP-PARTNER-A',
  数据域编号: 'DOMAIN-ORDER',
  请求汇总级别: '明细',
  核对日期: today,
})
const precheckResult = ref<PrecheckResult | null>(null)
const verifyResult = ref<VerifyResult | null>(null)
const consumption = ref<Consumption | null>(null)
const consumptionGroup = ref('GROUP-PARTNER-A')
const lastApproval = ref<LastApproval | null>(null)

const activeLicenseCount = computed(() => licenses.value.filter((l) => l.许可状态 === '生效中').length)
const revokedLicenseCount = computed(() => licenses.value.filter((l) => l.许可状态 === '已撤回').length)

async function getJson(path: string): Promise<Record<string, unknown>> {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return response.json()
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    const [d, g, l, s] = await Promise.all([
      getJson(`${ENDPOINT}/domains`),
      getJson(`${ENDPOINT}/groups`),
      getJson(`${ENDPOINT}/licenses`),
      getJson(`${ENDPOINT}/signoffs`),
    ])
    domains.value = (d.items as Row[]) ?? []
    groups.value = (g.items as Row[]) ?? []
    licenses.value = (l.items as Row[]) ?? []
    signoffs.value = (s.items as Row[]) ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '基础数据加载失败'
  }
}

async function runPrecheck() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/precheck`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          ...precheckForm.value,
          数据域: domains.value.map((d) => ({
            数据域编号: d.数据域编号 as string,
            请求汇总级别: precheckForm.value.请求汇总级别,
          })),
        },
      }),
    })
    const data = await response.json()
    if (!data.ok) throw new Error(data.message)
    precheckResult.value = data.result as PrecheckResult
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '预检失败'
  }
}

async function signoff(method: string) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/signoffs`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          ...precheckForm.value,
          发布方式: method,
          数据域: domains.value.map((d) => ({
            数据域编号: d.数据域编号 as string,
            请求汇总级别: precheckForm.value.请求汇总级别,
          })),
        },
      }),
    })
    const data = await response.json()
    if (!data.ok) throw new Error(data.message)
    await reloadAll()
    await runPrecheck()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '签收失败'
  }
}

async function revoke(lic: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/licenses/${lic.id}/revoke`, {
      method: 'POST',
      body: JSON.stringify({ values: { 撤回原因: '发布授权预检页面撤回' } }),
    })
    const data = await response.json()
    if (!data.ok) throw new Error(data.message)
    await reloadAll()
    if (precheckResult.value) await runPrecheck()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '撤回失败'
  }
}

async function runVerify() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/verify`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...verifyForm.value } }),
    })
    const data = await response.json()
    if (!data.ok) throw new Error(data.message)
    verifyResult.value = data.result as VerifyResult
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '访问核验失败'
  }
}

async function loadConsumption() {
  errorMessage.value = ''
  try {
    consumption.value = (await getJson(`${ENDPOINT}/groups/${consumptionGroup.value}/consumption`)) as unknown as Consumption
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消费范围计算失败'
  }
}

async function loadLastApproval() {
  errorMessage.value = ''
  try {
    lastApproval.value = (await getJson(
      `${ENDPOINT}/groups/${consumptionGroup.value}/last_approval?dashboard_no=${encodeURIComponent(precheckForm.value.看板编号)}`,
    )) as unknown as LastApproval
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '上次批准层级回查失败'
  }
}

function formatEvals(items: EvalItem[] | undefined): string {
  if (!items || !items.length) return '无命中'
  return items.map((i) => `${i.许可编号}(${i.来源团队}/${i.命中情况}/${i.最高汇总级别})`).join('，')
}

function formatBasis(basis: SignoffBasisItem[]): string {
  if (!basis.length) return '—'
  return basis.map((b) => `${b.数据域编号}:${b.依据许可.join('+') || '无许可'}`).join('；')
}

function formatDeliver(scope: unknown): string {
  if (!Array.isArray(scope)) return '—'
  const list = scope as Array<Record<string, string>>
  if (!list.length) return '—'
  return list.map((d) => `${d.数据域编号}→${d.交付级别}（${d.交付形态}）`).join('；')
}

onMounted(() => {
  void reloadAll()
})
</script>

<style scoped>
.section-title { font-size: 15px; margin: 18px 0 8px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.panel h4 { margin: 0 0 8px; font-size: 14px; }
.data-table.compact th, .data-table.compact td { padding: 6px 8px; font-size: 12px; vertical-align: top; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.tag-ok { background: #e7f6ec; color: #1a7f37; }
.tag-warn { background: #fff4e0; color: #b25e09; }
.tag-danger { background: #fde8e8; color: #b42318; }
.row-revoked { background: #fcf3f3; }
.result-box { border: 1px dashed var(--border); border-radius: 8px; padding: 12px; margin-top: 10px; background: #fbfdff; }
.result-head { display: flex; justify-content: space-between; align-items: center; }
.result-title { font-size: 14px; }
.recommend { font-size: 13px; margin: 8px 0; }
.text-ok { color: #1a7f37; }
.text-danger { color: #b42318; }
.muted { color: var(--muted); font-size: 12px; }
.blocker { color: #b42318; font-size: 12px; }
.detail-cell { min-width: 280px; }
.filter-item select { padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; min-width: 160px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
</style>
