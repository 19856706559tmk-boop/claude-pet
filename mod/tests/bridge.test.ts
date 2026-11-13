import { expect, test } from 'claude-code/testing'
import { isNewerReading } from '../hooks/register'

test('writes quota and activity next to the mod folder', async ($, on) => {
  const writes: { path: string; text: string }[] = []
  on('fs.write', (_, e) => {
    writes.push({ path: e.path, text: e.text })
    return { value: undefined }
  })
  on('clock.now', () => ({ value: 1000 }))
  on('session.measure', (_, e) => ({ changed: e.changed }))
  on('prompt.submit', (_, e) => ({ text: e.text }) as never)
  on('tool.call', () => ({ result: {} }))

  await $.session.measure({
    context: {} as never,
    rateLimits: [{ kind: 'five_hour', percentUsed: 40, resetsAt: '2026-11-10T12:00:00Z' }],
    changed: ['rateLimits'],
  })
  await $.tool.call({ tool: 'Bash', command: 'ls' } as never)
  await new Promise(r => setTimeout(r, 50))

  const quota = writes.find(w => /quota\.json$/.test(w.path))
  expect(quota).toBeDefined()
  expect(JSON.parse(quota!.text).rateLimits[0].percentUsed).toBe(40)
  expect(quota!.path).not.toMatch(/[\\/]mod[\\/]quota\.json$/)

  const act = writes.find(w => /activity\.json$/.test(w.path))
  expect(act).toBeDefined()
  expect(JSON.parse(act!.text)).toMatchObject({ kind: 'tool', tool: 'Bash' })
})

test('isNewerReading: later window or higher use in the same window wins', () => {
  const at = (percentUsed: number, resetsAt: string) => ({ kind: 'five_hour', percentUsed, resetsAt })
  expect(isNewerReading(at(10, '2026-11-12T17:30:00Z'), undefined)).toBe(true)
  // 同一个窗口：用得更多才算新
  expect(isNewerReading(at(22, '2026-11-12T17:30:00Z'), at(36, '2026-11-12T17:30:00Z'))).toBe(false)
  expect(isNewerReading(at(40, '2026-11-12T17:30:00Z'), at(36, '2026-11-12T17:30:00Z'))).toBe(true)
  // 换了更晚的窗口：哪怕数字更小也是新的；更早的窗口永远是旧的
  expect(isNewerReading(at(1, '2026-11-12T22:30:00Z'), at(90, '2026-11-12T17:30:00Z'))).toBe(true)
  expect(isNewerReading(at(90, '2026-11-12T17:30:00Z'), at(1, '2026-11-12T22:30:00Z'))).toBe(false)
})

// 会话开始时手里的旧读数不能盖掉别的对话刚写的新数据
async function startWith(
  $: Parameters<Parameters<typeof test>[1]>[0],
  on: Parameters<Parameters<typeof test>[1]>[1],
  existing: unknown,
  reading: { kind: string; percentUsed: number; resetsAt: string }[],
) {
  const writes: { path: string; text: string }[] = []
  on('fs.write', (_, e) => {
    writes.push({ path: e.path, text: e.text })
    return { value: undefined }
  })
  on('fs.read', (_, e) => {
    if (/quota\.json$/.test(e.path)) return { value: JSON.stringify(existing) }
    throw new Error('no such file')
  })
  on('clock.now', () => ({ value: 5000 }))
  on('session.usage', () => ({ value: { startedAt: 0, context: {}, rateLimits: reading } }) as never)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: 'D:/work', surface: null, isInteractive: false })
  await new Promise(r => setTimeout(r, 50))
  return writes.filter(w => /quota\.json$/.test(w.path)).map(w => JSON.parse(w.text))
}

const fresh = {
  at: 4000,
  rateLimits: [
    { kind: 'five_hour', percentUsed: 36, resetsAt: '2026-11-12T17:30:00Z' },
    { kind: 'seven_day', percentUsed: 5, resetsAt: '2026-11-18T01:00:00Z' },
  ],
}

test('session.start keeps newer quota written by another session', async ($, on) => {
  const quota = await startWith($, on, fresh, [
    { kind: 'five_hour', percentUsed: 22, resetsAt: '2026-11-12T17:30:00Z' },
    { kind: 'seven_day', percentUsed: 3, resetsAt: '2026-11-18T01:00:00Z' },
  ])
  expect(quota).toEqual([])
})

test('session.start still moves the quota forward', async ($, on) => {
  const quota = await startWith($, on, fresh, [
    { kind: 'five_hour', percentUsed: 41, resetsAt: '2026-11-12T17:30:00Z' },
    { kind: 'seven_day', percentUsed: 3, resetsAt: '2026-11-18T01:00:00Z' },
  ])
  expect(quota).toHaveLength(1)
  expect(quota[0].rateLimits).toEqual([
    { kind: 'five_hour', percentUsed: 41, resetsAt: '2026-11-12T17:30:00Z' },
    { kind: 'seven_day', percentUsed: 5, resetsAt: '2026-11-18T01:00:00Z' },
  ])
})
