const email = import.meta.env.VITE_DEMO_EMAIL?.trim()
const password = import.meta.env.VITE_DEMO_PASSWORD

export const DEMO_CREDENTIALS = email && password ? { email, password } : null
