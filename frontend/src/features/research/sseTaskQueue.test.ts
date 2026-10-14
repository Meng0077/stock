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
})
