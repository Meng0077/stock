import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <main className="grid min-h-screen place-items-center bg-slate-950 px-6 text-slate-100">
      <section className="text-center">
        <p className="text-sm font-semibold tracking-[0.2em] text-cyan-300 uppercase">
          404
        </p>
        <h1 className="mt-3 text-4xl font-semibold">页面不存在</h1>
        <Link
          to="/research"
          className="mt-6 inline-flex rounded-xl bg-cyan-400 px-5 py-2.5 font-medium text-slate-950"
        >
          返回研究页面
        </Link>
      </section>
    </main>
  )
}
