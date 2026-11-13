import type { EngineInterface, Register } from 'claude-code'

// 宠物文件夹 = 插件文件夹（mod）的上一级。
// Windows 上 $.plugin.root 用的是反斜杠，所以两种分隔符都要认；统一换成正斜杠返回。
function petDir($: EngineInterface): string {
  const root = $.plugin.root.replace(/\\/g, '/').replace(/\/+$/, '')
  return root.slice(0, root.lastIndexOf('/'))
}

async function writeJson($: EngineInterface, name: string, value: unknown) {
  try {
    await $.fs.write(`${petDir($)}/${name}`, JSON.stringify(value))
  } catch {
    // 写不进去就算了，不影响会话
  }
}

type Limit = { kind: string; percentUsed: number; resetsAt?: string }

const pick = (l: Limit): Limit => ({ kind: l.kind, percentUsed: l.percentUsed, resetsAt: l.resetsAt })

async function readQuota($: EngineInterface): Promise<Limit[]> {
  try {
    const data = JSON.parse(await $.fs.read(`${petDir($)}/quota.json`)) as { rateLimits?: unknown }
    if (!Array.isArray(data.rateLimits)) return []
    return (data.rateLimits as Limit[]).filter(
      l => l && typeof l.kind === 'string' && typeof l.percentUsed === 'number',
    )
  } catch {
    return []
  }
}

// 这条读数是否比文件里的更新：换了更晚的窗口，或者同一个窗口里用得更多（同一窗口内用量只增不减）
export function isNewerReading(next: Limit, prev: Limit | undefined): boolean {
  if (!prev) return true
  const a = Date.parse(next.resetsAt ?? '')
  const b = Date.parse(prev.resetsAt ?? '')
  if (!Number.isNaN(a) && !Number.isNaN(b) && Math.abs(a - b) > 60_000) return a > b
  return next.percentUsed > prev.percentUsed
}

let lastQuotaKey = ''
let lastQuotaAt = 0

// isFresh = 读数来自刚收到的回复，直接以它为准。
// 会话刚开始时手里的读数可能是很久以前留下的，这时只补上文件里没有的、或确实更新的部分，
// 不去覆盖别的对话刚写进去的新数据（否则面板上的额度会突然"倒退"）。
async function writeQuota($: EngineInterface, limits: readonly Limit[], isFresh: boolean) {
  try {
    if (limits.length === 0) return
    let out = limits.map(pick)
    if (!isFresh) {
      const old = await readQuota($)
      if (old.length > 0) {
        const byKind = new Map(old.map(l => [l.kind, l] as const))
        const newer = out.filter(l => isNewerReading(l, byKind.get(l.kind)))
        if (newer.length === 0) return
        for (const l of newer) byKind.set(l.kind, l)
        out = [...byKind.values()].map(pick)
      }
    }
    const at = await $.clock.now()
    const key = JSON.stringify(out)
    // 数字没变就不反复重写；隔一分钟再写一次，让面板上的"更新时间"保持准确
    if (key === lastQuotaKey && at - lastQuotaAt < 60_000) return
    lastQuotaKey = key
    lastQuotaAt = at
    await writeJson($, 'quota.json', { at, rateLimits: out })
  } catch {
    // 额度写不出去不影响会话
  }
}

// session.measure 只在回合结束或额度跨过整数点时才触发，长任务中间会有明显延迟。
// 每次工具调用都紧跟在一次回复之后，这时顺手读一次最新读数，面板不用等回合结束就能跟上。
async function refreshQuota($: EngineInterface) {
  try {
    const usage = await $.session.usage()
    await writeQuota($, usage.rateLimits, true)
  } catch {
    // 读不到就等下一次
  }
}

let seq = 0
async function writeActivity($: EngineInterface, kind: string, extra: Record<string, unknown> = {}) {
  const at = await $.clock.now()
  seq += 1
  await writeJson($, 'activity.json', { at, seq, kind, ...extra })
}

async function launchPet($: EngineInterface) {
  try {
    const dir = petDir($)
    const config = JSON.parse(await $.fs.read(`${dir}/config.json`)) as { pythonw?: string }
    if (!config.pythonw) return
    // --spawn 模式会把宠物以独立进程启动后立刻返回；已经在运行就什么也不做
    await $.process.run([config.pythonw, `${dir}/pet.pyw`, '--spawn'], { cwd: dir, timeoutMs: 15_000 })
  } catch (err) {
    // 启动失败不影响会话，但把原因记下来，方便排查
    await writeJson($, 'launch-error.json', { at: await $.clock.now(), error: String(err) })
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    try {
      // 心跳：说明插件已在这个会话里加载（排查用）
      await writeJson($, 'bridge.json', { startedAt: await $.clock.now(), root: $.plugin.root })
      const usage = await $.session.usage()
      await writeQuota($, usage.rateLimits, false)
    } catch {}
    void launchPet($)
    return result
  })

  on('session.measure', async ($, e, next) => {
    void writeQuota($, e.rateLimits, true)
    return next(e)
  })

  // 只是旁观：出错时照常放行，绝不拦截用户的消息
  on('prompt.submit', async ($, e, next) => {
    void writeActivity($, 'prompt')
    return next(e)
  }).catch(($, e, next) => next(e))

  // 只是旁观：出错时照常放行，绝不拦截工具调用
  on('tool.call', async ($, e, next) => {
    void writeActivity($, 'tool', { tool: e.tool })
    void refreshQuota($)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    if (!e.agentId) {
      void writeActivity($, e.reason === 'answer' ? 'done' : 'stopped', { reason: e.reason })
    }
    void refreshQuota($)
    return next(e)
  })
}
