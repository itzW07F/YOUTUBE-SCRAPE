import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      lib: {
        entry: 'src/main/index.ts',
        formats: ['cjs'],
        fileName: () => 'index.js'
      },
      rollupOptions: {
        external: ['electron']
      }
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@main': path.resolve(__dirname, './src/main'),
        '@preload': path.resolve(__dirname, './src/preload')
      }
    }
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      lib: {
        entry: 'src/preload/index.ts',
        formats: ['cjs'],
        fileName: () => 'index.js'
      }
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@preload': path.resolve(__dirname, './src/preload')
      }
    }
  },
  renderer: {
    plugins: [react()],
    root: '.',
    build: {
      outDir: 'out/renderer',
      rollupOptions: {
        input: {
          index: path.resolve(__dirname, 'index.html')
        }
      }
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@renderer': path.resolve(__dirname, './src/renderer'),
        '@components': path.resolve(__dirname, './src/renderer/components'),
        '@hooks': path.resolve(__dirname, './src/renderer/hooks'),
        '@stores': path.resolve(__dirname, './src/renderer/stores'),
        '@services': path.resolve(__dirname, './src/renderer/services')
      }
    },
    server: {
      port: 5173
    }
  }
})
