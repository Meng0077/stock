import { useId, type FormEvent } from 'react'
import type { CreateResearchRunRequest } from '../../api/contracts'

interface ResearchComposerProps {
  readonly disabled: boolean
  readonly onSubmit: (request: CreateResearchRunRequest) => void | Promise<void>
}

export function ResearchComposer({ disabled, onSubmit }: ResearchComposerProps) {
  const inputId = useId()

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (disabled) {
      return
    }

    const form = event.currentTarget
    const message = String(new FormData(form).get('message') ?? '').trim()

    if (!message) {
      return
    }

    form.reset()
    await onSubmit({ message })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <label htmlFor={inputId} className="block text-sm font-medium text-slate-200">
        研究问题
      </label>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <textarea
          id={inputId}
          name="message"
          placeholder="例如：查询 NVDA 教学报价"
          disabled={disabled}
          rows={2}
          className="min-h-20 max-h-[300px] min-w-0 flex-1 resize-none overflow-y-auto rounded-xl border border-white/10 bg-slate-900 p-3 text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-400 disabled:cursor-not-allowed disabled:opacity-60 [field-sizing:content]"
        />
        <button
          type="submit"
          disabled={disabled}
          className="shrink-0 rounded-xl bg-cyan-400 px-5 py-3 font-medium text-slate-950 hover:bg-cyan-300 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {disabled ? '研究中…' : '发送'}
        </button>
      </div>
    </form>
  )
}
