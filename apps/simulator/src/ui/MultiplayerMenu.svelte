<script lang="ts">
import type { MultiplayerSnapshot } from "../multiplayer/index.js";
import { normalizeRoomName } from "../multiplayer/index.js";
import type { SimulatorLevelId } from "../sim/contracts";
import { getSimulatorLevel } from "../sim/levels";

type Props = {
	readonly snapshot: MultiplayerSnapshot;
	readonly localLevelId: SimulatorLevelId;
	readonly isMobile: boolean;
	readonly onCreateRoom: (roomName: string, displayName: string) => void;
	readonly onJoinRoom: (roomName: string, displayName: string) => void;
	readonly onLeaveRoom: () => void;
	readonly onSendChat: (text: string) => void;
	readonly onSwitchLevel: (levelId: SimulatorLevelId) => void;
	readonly onClose: () => void;
};

const {
	snapshot,
	localLevelId,
	isMobile,
	onCreateRoom,
	onJoinRoom,
	onLeaveRoom,
	onSendChat,
	onSwitchLevel,
	onClose,
}: Props = $props();

let roomInput = $state("");
let nameInput = $state("");
let chatInput = $state("");
let copiedLink = $state(false);
let nameInitialized = $state(false);

$effect(() => {
	if (!nameInitialized && snapshot.displayName) {
		nameInput = snapshot.displayName;
		nameInitialized = true;
	}
});

$effect(() => {
	if (!roomInput && snapshot.roomName) {
		roomInput = snapshot.roomName;
	}
});

const normalizedRoom = $derived(normalizeRoomName(roomInput));
const canSubmitRoom = $derived(
	normalizedRoom.length >= 3 && snapshot.status !== "connecting",
);
const totalPeers = $derived(
	Math.max(snapshot.connectedPeers.length, snapshot.remotePlayers.length) + 1,
);

function handleCreate(): void {
	if (!canSubmitRoom) {
		return;
	}
	onCreateRoom(normalizedRoom, nameInput);
}

function handleJoin(): void {
	if (!canSubmitRoom) {
		return;
	}
	onJoinRoom(normalizedRoom, nameInput);
}

function handleSendChat(event: Event): void {
	event.preventDefault();
	const text = chatInput.trim();
	if (!text) {
		return;
	}
	onSendChat(text);
	chatInput = "";
}

async function copyInviteLink(): Promise<void> {
	if (!snapshot.roomName || typeof window === "undefined") {
		return;
	}
	const url = `${window.location.origin}${window.location.pathname}?room=${encodeURIComponent(snapshot.roomName)}`;
	try {
		await navigator.clipboard.writeText(url);
		copiedLink = true;
		window.setTimeout(() => {
			copiedLink = false;
		}, 2000);
	} catch {
		window.prompt("Copy room invite link:", url);
	}
}

function shortPeer(peerId: string): string {
	return peerId.length > 10 ? `${peerId.slice(0, 6)}…` : peerId;
}

function levelShortName(levelId: SimulatorLevelId): string {
	return getSimulatorLevel(levelId).name.split("(")[0]?.trim() || levelId;
}
</script>

<div
	class="mp-popover"
	class:mobile={isMobile}
	role="dialog"
	aria-label="Multiplayer Room Menu"
	data-testid="multiplayer-popover"
>
	<div class="mp-head">
		<div class="mp-title-wrap">
			<span class="mp-eyebrow">MULTIPLAYER ROOMS</span>
			<span
				class="mp-status-pill"
				class:connected={snapshot.status === "connected"}
				class:connecting={snapshot.status === "connecting"}
				class:error={snapshot.status === "error"}
			>
				{#if snapshot.status === "connected"}
					{snapshot.mode === "host" ? "HOSTING" : "CONNECTED"}
				{:else if snapshot.status === "connecting"}
					CONNECTING…
				{:else if snapshot.status === "error"}
					ERROR
				{:else}
					OFFLINE
				{/if}
			</span>
		</div>
		<button
			type="button"
			class="mp-close"
			aria-label="Close multiplayer menu"
			onclick={onClose}
		>
			✕
		</button>
	</div>

	{#if snapshot.status === "connected"}
		<div class="mp-room-banner">
			<div class="mp-room-meta">
				<strong data-testid="mp-room-name">{snapshot.roomName}</strong>
				<span>{totalPeers} {totalPeers === 1 ? "peer" : "peers"} online</span>
			</div>
			<button
				type="button"
				class="mp-mini-btn"
				data-testid="mp-copy-invite"
				onclick={copyInviteLink}
			>
				{copiedLink ? "Copied!" : "Copy Link"}
			</button>
		</div>

		<div class="mp-section">
			<div class="mp-section-label">PEERS IN ROOM</div>
			<ul class="mp-peer-list" data-testid="mp-peer-list">
				<li class="mp-peer-item self">
					<span class="mp-peer-name">
						{snapshot.displayName || "You"} <small>(you)</small>
					</span>
					<span class="mp-peer-badge">
						{snapshot.mode === "host" ? "HOST" : "LOCAL"}
					</span>
				</li>
				{#each snapshot.remotePlayers as remote (remote.peerId)}
					<li class="mp-peer-item">
						<span class="mp-peer-name">
							{remote.pose.displayName || shortPeer(remote.peerId)}
						</span>
						<div class="mp-peer-tags">
							<span class="mp-peer-badge" class:robot={Boolean(remote.pose.robotModel)}>
								{remote.pose.robotModel ? remote.pose.robotModel.toUpperCase() : "PLAYER"}
							</span>
							{#if remote.pose.levelId && remote.pose.levelId !== localLevelId}
								<button
									type="button"
									class="mp-world-jump"
									title={`Switch to ${levelShortName(remote.pose.levelId)}`}
									onclick={() => {
										if (remote.pose.levelId) {
											onSwitchLevel(remote.pose.levelId);
										}
									}}
								>
									→ {levelShortName(remote.pose.levelId)}
								</button>
							{/if}
						</div>
					</li>
				{/each}
			</ul>
			{#if snapshot.remotePlayers.length === 0}
				<p class="mp-hint">
					Share the room name or invite link so friends can join with their robot or from game.megameal.
				</p>
			{/if}
		</div>

		<div class="mp-section">
			<div class="mp-section-label">ROOM CHAT</div>
			<div class="mp-chat-feed" data-testid="mp-chat-feed">
				{#if snapshot.chatMessages.length === 0}
					<p class="mp-chat-empty">No messages yet.</p>
				{:else}
					{#each snapshot.chatMessages.slice(-20) as msg (msg.id)}
						<p class="mp-chat-line">
							<strong>
								{msg.senderId === snapshot.localPeerId
									? snapshot.displayName || "You"
									: msg.senderName || shortPeer(msg.senderId)}:
							</strong>
							<span>{msg.text}</span>
						</p>
					{/each}
				{/if}
			</div>
			<form class="mp-chat-form" onsubmit={handleSendChat}>
				<input
					type="text"
					class="mp-input"
					data-testid="mp-chat-input"
					bind:value={chatInput}
					maxlength="200"
					placeholder="Say something..."
				/>
				<button
					type="submit"
					class="mp-mini-btn primary"
					data-testid="mp-chat-send"
					disabled={chatInput.trim().length === 0}
				>
					Send
				</button>
			</form>
		</div>

		<button
			type="button"
			class="mp-leave-btn"
			data-testid="mp-leave-btn"
			onclick={onLeaveRoom}
		>
			Leave Room
		</button>
	{:else}
		<form
			class="mp-form"
			onsubmit={(event) => {
				event.preventDefault();
				handleJoin();
			}}
		>
			<label class="mp-field">
				<span>Callsign (optional)</span>
				<input
					type="text"
					class="mp-input"
					data-testid="mp-name-input"
					bind:value={nameInput}
					maxlength="24"
					placeholder="e.g. Rover-1"
				/>
			</label>
			<label class="mp-field">
				<span>Room name (3+ chars)</span>
				<input
					type="text"
					class="mp-input"
					data-testid="mp-room-input"
					bind:value={roomInput}
					minlength="3"
					maxlength="40"
					placeholder="e.g. ainekio-lab"
				/>
			</label>
			<div class="mp-actions">
				<button
					type="button"
					class="mp-action-btn primary"
					data-testid="mp-create-btn"
					disabled={!canSubmitRoom}
					onclick={handleCreate}
				>
					{snapshot.status === "connecting" && snapshot.mode === "host"
						? "Creating…"
						: "Create Room"}
				</button>
				<button
					type="submit"
					class="mp-action-btn"
					data-testid="mp-join-btn"
					disabled={!canSubmitRoom}
				>
					{snapshot.status === "connecting" && snapshot.mode === "client"
						? "Joining…"
						: "Join Room"}
				</button>
			</div>
		</form>
		<p class="mp-hint">
			Peer-to-peer WebRTC rooms (loaded only when you join). Works across simulator.ainek.io robots and game.megameal.
		</p>
	{/if}

	{#if snapshot.error}
		<p class="mp-error" data-testid="mp-error">{snapshot.error}</p>
	{/if}
</div>

<style>
	.mp-popover {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		width: 304px;
		max-height: min(76vh, 520px);
		overflow-y: auto;
		padding: 12px;
		border-radius: 12px;
		background: rgba(9, 14, 26, 0.96);
		border: 1px solid rgba(56, 189, 248, 0.34);
		box-shadow: 0 18px 44px rgba(0, 0, 0, 0.62);
		backdrop-filter: blur(14px);
		display: flex;
		flex-direction: column;
		gap: 10px;
		z-index: 35;
		color: #e2e8f0;
	}
	.mp-popover.mobile {
		position: fixed;
		top: 52px;
		left: 8px;
		right: 8px;
		width: auto;
		max-height: calc(100dvh - 120px);
	}
	.mp-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.mp-title-wrap {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.mp-eyebrow {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: #94a3b8;
	}
	.mp-status-pill {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.06em;
		padding: 2px 7px;
		border-radius: 999px;
		border: 1px solid rgba(148, 163, 184, 0.28);
		color: #94a3b8;
	}
	.mp-status-pill.connected {
		border-color: rgba(34, 197, 94, 0.5);
		background: rgba(21, 128, 61, 0.28);
		color: #86efac;
	}
	.mp-status-pill.connecting {
		border-color: rgba(56, 189, 248, 0.45);
		background: rgba(14, 116, 144, 0.25);
		color: #7dd3fc;
	}
	.mp-status-pill.error {
		border-color: rgba(248, 113, 113, 0.45);
		background: rgba(127, 29, 29, 0.35);
		color: #fca5a5;
	}
	.mp-close {
		border: none;
		background: transparent;
		color: #94a3b8;
		font-size: 13px;
		cursor: pointer;
		padding: 2px 5px;
		border-radius: 6px;
	}
	.mp-close:hover {
		color: #f8fafc;
		background: rgba(148, 163, 184, 0.16);
	}
	.mp-room-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		padding: 8px 10px;
		border-radius: 9px;
		background: rgba(15, 23, 42, 0.85);
		border: 1px solid rgba(56, 189, 248, 0.24);
	}
	.mp-room-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.mp-room-meta strong {
		font-size: 13px;
		color: #f8fafc;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.mp-room-meta span {
		font-size: 11px;
		color: #7dd3fc;
	}
	.mp-section {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.mp-section-label {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.07em;
		color: #94a3b8;
	}
	.mp-peer-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 5px;
		max-height: 110px;
		overflow-y: auto;
	}
	.mp-peer-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 6px;
		padding: 5px 8px;
		border-radius: 7px;
		background: rgba(15, 23, 42, 0.65);
		font-size: 11px;
	}
	.mp-peer-item.self {
		border: 1px solid rgba(56, 189, 248, 0.2);
	}
	.mp-peer-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: #e2e8f0;
	}
	.mp-peer-name small {
		color: #94a3b8;
	}
	.mp-peer-tags {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}
	.mp-peer-badge {
		font-size: 9px;
		font-weight: 700;
		padding: 2px 6px;
		border-radius: 999px;
		background: rgba(148, 163, 184, 0.16);
		color: #cbd5e1;
	}
	.mp-peer-badge.robot {
		background: rgba(14, 165, 233, 0.22);
		color: #7dd3fc;
	}
	.mp-world-jump {
		font-size: 9px;
		font-weight: 600;
		padding: 2px 6px;
		border-radius: 6px;
		border: 1px solid rgba(56, 189, 248, 0.35);
		background: rgba(14, 116, 144, 0.25);
		color: #bae6fd;
		cursor: pointer;
	}
	.mp-chat-feed {
		max-height: 120px;
		overflow-y: auto;
		padding: 7px 8px;
		border-radius: 8px;
		background: rgba(4, 8, 16, 0.72);
		border: 1px solid rgba(148, 163, 184, 0.16);
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.mp-chat-empty {
		margin: 0;
		font-size: 11px;
		color: #64748b;
	}
	.mp-chat-line {
		margin: 0;
		font-size: 11px;
		line-height: 1.35;
		overflow-wrap: anywhere;
	}
	.mp-chat-line strong {
		color: #7dd3fc;
		margin-right: 4px;
	}
	.mp-chat-form {
		display: flex;
		gap: 6px;
	}
	.mp-form {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.mp-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 11px;
		color: #cbd5e1;
	}
	.mp-input {
		width: 100%;
		min-width: 0;
		box-sizing: border-box;
		height: 32px;
		padding: 0 9px;
		border-radius: 7px;
		border: 1px solid rgba(148, 163, 184, 0.26);
		background: rgba(4, 8, 16, 0.82);
		color: #f8fafc;
		font-size: 12px;
	}
	.mp-input:focus {
		outline: none;
		border-color: rgba(56, 189, 248, 0.65);
	}
	.mp-actions {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
		margin-top: 2px;
	}
	.mp-action-btn,
	.mp-mini-btn,
	.mp-leave-btn {
		height: 32px;
		padding: 0 10px;
		border-radius: 7px;
		border: 1px solid rgba(148, 163, 184, 0.26);
		background: rgba(30, 41, 59, 0.85);
		color: #e2e8f0;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
	}
	.mp-action-btn.primary,
	.mp-mini-btn.primary {
		border-color: rgba(56, 189, 248, 0.5);
		background: rgba(14, 116, 144, 0.52);
		color: #e0f2fe;
	}
	.mp-action-btn:disabled,
	.mp-mini-btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.mp-leave-btn {
		border-color: rgba(248, 113, 113, 0.42);
		background: rgba(127, 29, 29, 0.35);
		color: #fecaca;
	}
	.mp-hint {
		margin: 0;
		font-size: 11px;
		line-height: 1.4;
		color: #94a3b8;
	}
	.mp-error {
		margin: 0;
		padding: 7px 9px;
		border-radius: 7px;
		background: rgba(127, 29, 29, 0.35);
		border: 1px solid rgba(248, 113, 113, 0.4);
		color: #fecaca;
		font-size: 11px;
		overflow-wrap: anywhere;
	}
</style>
