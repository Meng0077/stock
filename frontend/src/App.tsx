function App() {
  return (
    <main className="grid min-h-screen place-items-center bg-slate-950 px-6 text-slate-100">
      <section className="w-full max-w-2xl rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl shadow-cyan-950/30 backdrop-blur sm:p-12">
        <div className="mb-8 flex items-center gap-3 text-sm text-cyan-300">
          <span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_18px] shadow-emerald-400" />
          工程初始化完成
        </div>
        <p className="text-sm font-semibold tracking-[0.2em] text-slate-400 uppercase">
          Stock Agent Frontend
        </p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight text-white sm:text-5xl">
          React、TypeScript、Vite 与 Tailwind CSS 已就绪
        </h1>
        <p className="mt-6 max-w-xl leading-7 text-slate-300">
          当前只包含工程基础设施。研究表单、结构化结果、证据与运行状态将在对应前端步骤中实现。
        </p>
        <dl className="mt-10 grid gap-3 text-sm sm:grid-cols-2">
          {['React 19', 'TypeScript 6', 'Vite 8', 'Tailwind CSS 4'].map(
            (item) => (
              <div
                key={item}
                className="rounded-xl border border-white/10 bg-slate-900/70 px-4 py-3 text-slate-300"
              >
                {item}
              </div>
            ),
          )}
        </dl>
      </section>
    </main>
  )
}

export default App
