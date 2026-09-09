import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
    plugins: [react()],
    build: {
        // Split the vendor libraries out of the application bundle. They change
        // far less often than our own code, so a returning operator re-downloads
        // only what we edited rather than the whole 830 kB.
        //
        // Leaflet and Recharts are separated from each other deliberately: the
        // map page needs one and the dashboard the other, and neither should
        // pull in the other's weight.
        rollupOptions: {
            output: {
                manualChunks: {
                    react: ['react', 'react-dom', 'react-router-dom'],
                    leaflet: ['leaflet', 'react-leaflet'],
                    charts: ['recharts'],
                    video: ['hls.js'],
                },
            },
        },
        // Raised because the chunks below are now deliberate and measured; the
        // default 500 kB warning was about the single monolithic bundle we
        // have just removed.
        chunkSizeWarningLimit: 600,
    },
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src'),
        },
    },
    server: {
        port: 5173,
        proxy: {
            '/api': 'http://localhost:8000',
            '/ws': { target: 'ws://localhost:8000', ws: true },
            '/evidence': 'http://localhost:8000',
        },
    },
})
