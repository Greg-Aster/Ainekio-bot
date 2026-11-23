import {
	type MultiplayerSession,
	type MultiplayerSnapshot,
	createMultiplayerSession,
	normalizeRoomName,
	sanitizeDisplayName,
} from "@ainekio/engine/multiplayer";

const DEFAULT_ROOM_DIRECTORY_URL =
	"https://megameal-room-directory.greggles.workers.dev";
const DISPLAY_NAME_STORAGE_KEY = "ainekio.sim.mp.displayName.v1";

export type BrowserMultiplayerClient = MultiplayerSession & {
	hostRoom(roomName: string): Promise<void>;
	joinRoom(roomName: string): Promise<void>;
};

export function createBrowserMultiplayerClient(
	options: {
		readonly enabled?: boolean;
		readonly roomDirectoryUrl?: string;
		readonly displayName?: string;
	} = {},
): BrowserMultiplayerClient {
	const initialDisplayName =
		options.displayName ?? loadSavedDisplayName() ?? "";
	const session = createMultiplayerSession({
		enabled: options.enabled ?? multiplayerEnabledFromEnv(),
		displayName: initialDisplayName,
	});
	const roomDirectoryUrl =
		options.roomDirectoryUrl ?? multiplayerRoomDirectoryUrlFromEnv();

	return {
		...session,
		setDisplayName(name) {
			const clean = sanitizeDisplayName(name);
			saveDisplayName(clean);
			session.setDisplayName(clean);
		},
		async hostRoom(roomName) {
			const normalizedRoomName = normalizeRoomName(roomName);

			if (!canStartConnection(session.snapshot(), normalizedRoomName)) {
				return;
			}

			session.markConnecting("host", normalizedRoomName);

			try {
				// Lazy-load PeerJS & room directory only when the user actually starts multiplayer
				const [{ createPeerHostTransport }, { createHttpRoomDirectory }] =
					await Promise.all([
						import(
							"@ainekio/engine/adapters/browser/networking/peer-transport"
						),
						import(
							"@ainekio/engine/adapters/browser/networking/room-directory"
						),
					]);
				const transport = await createPeerHostTransport();
				const directory = createHttpRoomDirectory({
					baseUrl: roomDirectoryUrl,
				});

				try {
					await directory.register(normalizedRoomName, transport.peerId);
				} catch (error) {
					transport.dispose();
					throw error;
				}

				session.attachTransport({
					transport,
					roomName: normalizedRoomName,
				});
			} catch (error) {
				session.setError(
					errorMessage(error, "Failed to create multiplayer room."),
				);
			}
		},
		async joinRoom(roomName) {
			const normalizedRoomName = normalizeRoomName(roomName);

			if (!canStartConnection(session.snapshot(), normalizedRoomName)) {
				return;
			}

			session.markConnecting("client", normalizedRoomName);

			try {
				const [{ createPeerClientTransport }, { createHttpRoomDirectory }] =
					await Promise.all([
						import(
							"@ainekio/engine/adapters/browser/networking/peer-transport"
						),
						import(
							"@ainekio/engine/adapters/browser/networking/room-directory"
						),
					]);
				const directory = createHttpRoomDirectory({
					baseUrl: roomDirectoryUrl,
				});
				const hostPeerId = await directory.lookup(normalizedRoomName);
				const transport = await createPeerClientTransport(hostPeerId);

				session.attachTransport({
					transport,
					roomName: normalizedRoomName,
				});
			} catch (error) {
				session.setError(
					errorMessage(error, "Failed to join multiplayer room."),
				);
			}
		},
	};
}

function canStartConnection(
	snapshot: MultiplayerSnapshot,
	roomName: string,
): boolean {
	return (
		snapshot.enabled &&
		roomName.length >= 3 &&
		snapshot.status !== "connecting" &&
		snapshot.status !== "connected"
	);
}

function readImportMetaEnv(): Record<string, string | undefined> {
	const meta = import.meta as ImportMeta & {
		readonly env?: Record<string, string | undefined>;
	};
	return meta.env ?? {};
}

function multiplayerEnabledFromEnv(): boolean {
	const env = readImportMetaEnv();
	return (
		env.PUBLIC_SIMULATOR_MULTIPLAYER_ENABLED !== "0" &&
		env.PUBLIC_MEGAMEAL_MULTIPLAYER_ENABLED !== "0"
	);
}

function multiplayerRoomDirectoryUrlFromEnv(): string {
	const env = readImportMetaEnv();
	const envUrl =
		env.PUBLIC_SIMULATOR_ROOM_DIRECTORY_URL ||
		env.PUBLIC_MEGAMEAL_ROOM_DIRECTORY_URL;

	return typeof envUrl === "string" && envUrl.trim().length > 0
		? envUrl.trim()
		: DEFAULT_ROOM_DIRECTORY_URL;
}

function loadSavedDisplayName(): string | undefined {
	if (typeof window === "undefined") {
		return undefined;
	}
	try {
		const raw = window.localStorage.getItem(DISPLAY_NAME_STORAGE_KEY);
		return raw ? sanitizeDisplayName(raw) : undefined;
	} catch {
		return undefined;
	}
}

function saveDisplayName(name: string): void {
	if (typeof window === "undefined") {
		return;
	}
	try {
		if (name) {
			window.localStorage.setItem(DISPLAY_NAME_STORAGE_KEY, name);
		} else {
			window.localStorage.removeItem(DISPLAY_NAME_STORAGE_KEY);
		}
	} catch {
		// Ignore storage restrictions
	}
}

function errorMessage(error: unknown, fallback: string): string {
	return error instanceof Error ? error.message : fallback;
}
