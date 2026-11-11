/** @type {import('tailwindcss').Config} */
module.exports = {
	content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
	theme: {
		extend: {
			animation: { 'pulse-slow': 'pulse-glow 2.4s ease-in-out infinite' },
			keyframes: {
				'pulse-glow': {
					'0%, 100%': { boxShadow: '0 0 0 0 rgba(250, 204, 21, 0.55)' },
					'50%': { boxShadow: '0 0 0 12px rgba(250, 204, 21, 0)' },
				},
			},
		},
	},
	plugins: [],
}
