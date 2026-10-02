import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  base: './',
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        mobile: resolve(__dirname, 'mobile.html'),
      },
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'framer-motion'],
          'vendor-three': ['three', '@react-three/fiber', '@react-three/drei'],
          'vendor-utils': ['zustand', 'lucide-react', 'clsx', 'tailwind-merge'],
          'vendor-markdown': ['react-markdown', 'rehype-katex', 'remark-gfm', 'remark-math', 'react-syntax-highlighter', 'katex'],
        }
      }
    },
  },
  server: {
    host: '0.0.0.0',
    // 前端开发/公网 Tunnel 的唯一规范端口。ai.example.icu -> localhost:3000。
    port: 3000,
    strictPort: true,
    allowedHosts: ['ai.example.icu'],
    proxy: {
      '/api/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
        timeout: 120000,
        ws: true
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
        timeout: 120000
      },
      '/static': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false
      },
      // /output 包含上传/生成媒体，后端现在要求 Bearer 或短期媒体 cookie。
      // 通过同源 Vite 代理转发，浏览器 <img>/<video> 会自动携带 HttpOnly cookie，
      // 不需要把主 API Token 暴露在媒体 URL 查询参数里。
      '/output': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
        timeout: 120000
      }
    }
  }
})
