/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './src/renderer/**/*.{js,ts,jsx,tsx}',
    './index.html'
  ],
  theme: {
    extend: {
      colors: {
        // Dark surfaces 900–700 unchanged; 600–300 are foreground-muted (neutral grays, higher luminance — old blue-violet mid-tones failed contrast on dark BG).
        space: {
          900: '#0a0a0f',
          800: '#12121a',
          700: '#1a1a2e',
          600: '#8f8f9e',
          500: '#a6a6b4',
          400: '#c4c4d0',
          300: '#dcdce6',
          200: '#e8e8ef',
          100: '#cacada',
          50: '#eaeafa',
        },
        // Accents avoid cyan/teal/emerald (ambiguous for blue–green deficiency): fuchsia + amber + orange.
        neon: {
          blue: '#d946ef',
          purple: '#7c3aed',
          cyan: '#fb923c',
          pink: '#f472b6',
          green: '#f59e0b',
        },
        glass: {
          light: 'rgba(255, 255, 255, 0.05)',
          DEFAULT: 'rgba(255, 255, 255, 0.08)',
          heavy: 'rgba(255, 255, 255, 0.12)',
          border: 'rgba(255, 255, 255, 0.1)',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
        display: ['Space Grotesk', 'Inter', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'slide-up': 'slideUp 0.3s ease-out',
        'fade-in': 'fadeIn 0.3s ease-out',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(217, 70, 239, 0.35)' },
          '100%': { boxShadow: '0 0 20px rgba(217, 70, 239, 0.65)' },
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
      backdropBlur: {
        xs: '2px',
      },
      boxShadow: {
        'neon-blue': '0 0 10px rgba(217, 70, 239, 0.45), 0 0 20px rgba(217, 70, 239, 0.28)',
        'neon-purple': '0 0 10px rgba(124, 58, 237, 0.5), 0 0 20px rgba(124, 58, 237, 0.3)',
        'glass': '0 8px 32px rgba(0, 0, 0, 0.3)',
      },
    },
  },
  plugins: [
    require('tailwindcss-animate'),
  ],
}
