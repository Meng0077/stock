import type { RunResponse } from '../../api/contracts'

const ResearchResponse = ({ response }: { response?: RunResponse }) => {
  return (
    <section aria-live="polite" className="min-w-0 flex-1 rounded-3xl border border-white/10 bg-white/5 p-4 text-slate-300 sm:p-6">
      {!response ? (
        <p className="text-slate-500">提交问题后，研究结果会显示在这里。</p>
      ) : (
        <article className="space-y-5">
          <header>
            <p className="text-sm text-cyan-300">Agent</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-100">
              {response.status === 'completed'
                ? '研究结果'
                : response.status === 'insufficient_information'
                  ? '资料不足'
                  : response.status === 'cancelled'
                    ? '任务已取消'
                    : '研究失败'}
            </h2>
            <p className="mt-2 break-all text-xs text-slate-500">
              Run ID: {response.run_id}
            </p>
          </header>

          {response.status === 'completed' || response.status === 'insufficient_information' ? (
            <>
              <p className="text-sm">
                数据模式：{response.result.data_mode}
                {response.result.data_mode === 'fixture' && '（本地教学模拟数据，不是实时行情）'}
              </p>

              <section>
                <h3 className="font-semibold text-slate-100">事实</h3>
                {response.result.facts.length === 0 ? (
                  <p className="mt-2 text-slate-500">暂无可展示的事实。</p>
                ) : (
                  <ul className="mt-2 space-y-3">
                    {response.result.facts.map((claim, index) => (
                      <li key={`${index}-${claim.text}`}>
                        <p className="whitespace-pre-wrap break-words">{claim.text}</p>
                        <p className="mt-1 text-xs text-cyan-300">
                          {claim.evidence_ids.map((id) => `[${id}]`).join(' ')}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <h3 className="font-semibold text-slate-100">推断</h3>
                {response.result.inferences.length === 0 ? (
                  <p className="mt-2 text-slate-500">暂无可展示的推断。</p>
                ) : (
                  <ul className="mt-2 space-y-3">
                    {response.result.inferences.map((claim, index) => (
                      <li key={`${index}-${claim.text}`}>
                        <p className="whitespace-pre-wrap break-words">{claim.text}</p>
                        <p className="mt-1 text-xs text-cyan-300">
                          {claim.evidence_ids.map((id) => `[${id}]`).join(' ')}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {response.result.missing_information.length > 0 && (
                <section className="rounded-2xl bg-amber-400/10 p-4 text-amber-100">
                  <h3 className="font-semibold">缺失信息</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5">
                    {response.result.missing_information.map((item, index) => (
                      <li key={`${index}-${item}`}>{item}</li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          ) : (
            <section className="rounded-2xl bg-red-400/10 p-4 text-red-100">
              <p>{response.error.message}</p>
              <p className="mt-2 text-xs opacity-70">
                错误代码：{response.error.code} · 阶段：{response.error.stage}
              </p>
            </section>
          )}
        </article>
      )}
    </section>
  )
}

export { ResearchResponse }
