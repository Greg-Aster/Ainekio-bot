import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";

const site = process.env.SITE_URL || "https://simulator.ainek.io";
const base = process.env.SITE_BASE || "/";

function buildStaticAssetHashes() {
	const publicDir = fileURLToPath(new URL("./public", import.meta.url));
	const roots = ["sim", path.join("assets", "robots")];
	const entries = [];

	const walk = (absDir) => {
		if (!fs.existsSync(absDir)) {
			return;
		}
		for (const entry of fs.readdirSync(absDir, { withFileTypes: true })) {
			const fullPath = path.join(absDir, entry.name);
			if (entry.isDirectory()) {
				walk(fullPath);
			} else if (entry.isFile()) {
				const relPath = `/${path.relative(publicDir, fullPath).replaceAll(path.sep, "/")}`;
				const hash = crypto
					.createHash("sha256")
					.update(fs.readFileSync(fullPath))
					.digest("hex")
					.slice(0, 12);
				entries.push([relPath, hash]);
			}
		}
	};

	for (const root of roots) {
		walk(path.join(publicDir, root));
	}
	entries.sort(([a], [b]) => a.localeCompare(b));
	return Object.fromEntries(entries);
}

export default defineConfig({
	site,
	base,
	trailingSlash: "always",
	integrations: [svelte()],
	vite: {
		define: {
			__SIM_ASSET_HASHES__: JSON.stringify(buildStaticAssetHashes()),
		},
		worker: {
			format: "es",
		},
		optimizeDeps: {
			exclude: ["mujoco-js"],
		},
	},
});
