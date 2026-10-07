import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // Recharts is large; raise the warning threshold for this portfolio project
    chunkSizeWarningLimit: 800,
  },
})
