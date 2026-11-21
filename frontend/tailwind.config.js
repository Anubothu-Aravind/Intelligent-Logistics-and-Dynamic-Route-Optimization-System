import { colors, fonts } from './src/theme/tokens.js';

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors,
      fontFamily: fonts,
      borderRadius: { panel: '22px', card: '14px' },
      boxShadow: {
        panel: '0 8px 30px rgba(20,22,26,0.08), 0 1px 2px rgba(20,22,26,0.06)',
        float: '0 4px 16px rgba(20,22,26,0.10)',
      },
      fontSize: { '2xs': ['10.5px', '14px'] },
    },
  },
  plugins: [],
};
