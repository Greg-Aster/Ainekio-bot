import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";

const site = process.env.SITE_URL || "https://simulator.ainek.io";
const base = process.env.SITE_BASE || "/";

export default defineConfig({
	site,
	base,
	trailingSlash: "always",
	integrations: [svelte()],
	vite: {
		worker: {
			format: "es",
		},
		optimizeDeps: {
			exclude: ["mujoco-js"],
		},
	},
});
