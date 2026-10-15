import { afterEach, describe, expect, it, vi } from 'vitest'

import { SSETaskQueue, TextBuffer, TextTask } from './sseTaskQueue'


let frames: FrameRequestCallback[] = []


afterEach(() => {
  frames = []
  vi.unstubAllGlobals()
})


function installAnimationFrame() {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frames.push(callback)
    return frames.length
  })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
}


function runNextFrame() {
  const frame = frames.shift()
  if (!frame) throw new Error('animation frame was not scheduled')
  frame(0)
}


describe('SSETaskQueue', () => {
  it('按动画帧逐字消费完整 Unicode 字符', async () => {
    installAnimationFrame()
    const controller = new AbortController()
    const buffer = new TextBuffer()
    const committed: string[] = []

    buffer.append('A😀')
    buffer.seal()
    const consuming = buffer.consume(text => committed.push(text), controller.signal)

    expect(committed).toEqual(['A'])
    runNextFrame()
    await Promise.resolve()
    expect(committed).toEqual(['A', '😀'])
    runNextFrame()
    await consuming
  })

  it('等待新 delta 时可以通过 signal 停止', async () => {
    const controller = new AbortController()
    const buffer = new TextBuffer()
    const consuming = buffer.consume(() => undefined, controller.signal)

    controller.abort()

    await expect(consuming).resolves.toBeUndefined()
  })

  it('新 delta 到达后唤醒等待中的 TextTask', async () => {
    installAnimationFrame()
    const controller = new AbortController()
    const buffer = new TextBuffer()
    const committed: string[] = []
    const consuming = buffer.consume(text => committed.push(text), controller.signal)

    buffer.append('新')
    await Promise.resolve()
    expect(committed).toEqual(['新'])

    buffer.seal()
    runNextFrame()
    await consuming
  })

  it('文字展示完成后才执行后续任务', async () => {
    installAnimationFrame()
    const controller = new AbortController()
    const queue = new SSETaskQueue(controller.signal)
    const buffer = new TextBuffer()
    const output: string[] = []

    buffer.append('AB')
    buffer.seal()
    queue.enqueue(new TextTask(buffer, text => output.push(text)))
    queue.enqueue({ run: () => { output.push('completed') } })

    await Promise.resolve()
    expect(output).toEqual(['A'])
    runNextFrame()
    await Promise.resolve()
    expect(output).toEqual(['A', 'B'])
    runNextFrame()
    await queue.flush()
    expect(output).toEqual(['A', 'B', 'completed'])
  })

  it('多个任务严格按入队顺序执行', async () => {
    const queue = new SSETaskQueue(new AbortController().signal)
    const output: number[] = []

    queue.enqueue({ run: async () => { output.push(1); await Promise.resolve(); output.push(2) } })
    queue.enqueue({ run: () => { output.push(3) } })

    await queue.flush()
    expect(output).toEqual([1, 2, 3])
  })

  it('任务失败后由 flush 抛出原始错误', async () => {
    const queue = new SSETaskQueue(new AbortController().signal)
    const error = new Error('display failed')

    queue.enqueue({ run: () => { throw error } })

    await expect(queue.flush()).rejects.toBe(error)
  })

  it('abort 停止当前文字任务并跳过后续任务', async () => {
    installAnimationFrame()
    const controller = new AbortController()
    const queue = new SSETaskQueue(controller.signal)
    const buffer = new TextBuffer()
    const output: string[] = []

    buffer.append('AB')
    buffer.seal()
    queue.enqueue(new TextTask(buffer, text => output.push(text)))
    queue.enqueue({ run: () => { output.push('completed') } })

    await Promise.resolve()
    expect(output).toEqual(['A'])
    controller.abort()
    await queue.flush()

    expect(output).toEqual(['A'])
    expect(cancelAnimationFrame).toHaveBeenCalled()
  })
})
