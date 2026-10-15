import { useEffect, useRef, useState } from 'react'


export function useToast() {
    const [message, setMessage] = useState<string | null>(null)
    const timerRef = useRef<number | null>(null)

    const showToast = (message: string) => {
        if (timerRef.current !== null) {
            window.clearTimeout(timerRef.current)
        }

        setMessage(message)

        timerRef.current =
            window.setTimeout(() => {
                setMessage(null)
                timerRef.current = null
            }, 2500)
    }

    useEffect(() => {
        return () => {
            if (timerRef.current !== null) {
                window.clearTimeout(timerRef.current)
            }
        }
    }, [])

    return {
        message,
        showToast,
    }
}


export function Toast({ message }: {
    readonly message: string | null
}) {
    if (!message) {
        return null
    }

    return (
        <div
            role="alert"
            className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-800 px-4 py-3 text-sm text-slate-100 shadow-lg"
        >
            {message}
        </div>
    )
}
