import { randomUUID } from "node:crypto";
import type { WebContents } from "electron";
import { IPC, sanitizeMessage, validateExperimentId, validateLastEventId } from "./security";
import type { SettingsStore } from "./settings";
import { consumeSseBuffer, parseSseData } from "./sse-parser";

interface Subscription {
  id: string;
  sender: WebContents;
  experimentId: string;
  lastEventId: number;
  controller: AbortController | null;
  stopped: boolean;
  onDestroyed: () => void;
}

const MAX_SUBSCRIPTIONS_PER_SENDER = 4;
const IDLE_TIMEOUT_MS = 60_000;

export class SseBridge {
  private readonly settings: SettingsStore;
  private readonly subscriptions = new Map<string, Subscription>();

  constructor(settings: SettingsStore) {
    this.settings = settings;
  }

  subscribe(sender: WebContents, experimentRaw: unknown, lastRaw: unknown): string {
    const experiment = validateExperimentId(experimentRaw);
    if (!experiment.ok || !experiment.value) throw new Error(experiment.reason ?? "Invalid experiment");
    const last = validateLastEventId(lastRaw);
    if (!last.ok || last.value === undefined) throw new Error(last.reason ?? "Invalid Last-Event-ID");
    const existing = [...this.subscriptions.values()].filter((item) => item.sender.id === sender.id);
    if (existing.length >= MAX_SUBSCRIPTIONS_PER_SENDER) {
      throw new Error("Too many event subscriptions for this window");
    }
    const id = randomUUID();
    const subscription: Subscription = {
      id,
      sender,
      experimentId: experiment.value,
      lastEventId: last.value,
      controller: null,
      stopped: false,
      onDestroyed: () => undefined,
    };
    subscription.onDestroyed = () => this.unsubscribe(id);
    this.subscriptions.set(id, subscription);
    sender.once("destroyed", subscription.onDestroyed);
    void this.run(subscription);
    return id;
  }

  unsubscribe(idRaw: unknown, owner?: WebContents): void {
    if (typeof idRaw !== "string") return;
    const subscription = this.subscriptions.get(idRaw);
    if (!subscription) return;
    if (owner && subscription.sender.id !== owner.id) return;
    subscription.stopped = true;
    subscription.controller?.abort();
    this.subscriptions.delete(idRaw);
    if (!subscription.sender.isDestroyed()) {
      subscription.sender.removeListener("destroyed", subscription.onDestroyed);
    }
  }

  closeForSender(senderId: number): void {
    for (const subscription of this.subscriptions.values()) {
      if (subscription.sender.id === senderId) this.unsubscribe(subscription.id);
    }
  }

  shutdown(): void {
    for (const id of [...this.subscriptions.keys()]) this.unsubscribe(id);
  }

  private async run(subscription: Subscription): Promise<void> {
    let attempt = 0;
    while (!subscription.stopped && !subscription.sender.isDestroyed()) {
      const controller = new AbortController();
      subscription.controller = controller;
      let idleTimer: ReturnType<typeof setTimeout> | null = null;
      const resetIdle = () => {
        if (idleTimer) clearTimeout(idleTimer);
        idleTimer = setTimeout(() => controller.abort(), IDLE_TIMEOUT_MS);
      };
      resetIdle();
      try {
        const url = new URL(
          `/api/v1/experiments/${encodeURIComponent(subscription.experimentId)}/events`,
          this.settings.baseUrl,
        );
        url.searchParams.set("last_event_id", String(subscription.lastEventId));
        const headers: Record<string, string> = {
          Accept: "text/event-stream",
          "Cache-Control": "no-cache",
          "Last-Event-ID": String(subscription.lastEventId),
        };
        const token = this.settings.getToken();
        if (token) headers.Authorization = `Bearer ${token}`;
        const response = await fetch(url, {
          headers,
          redirect: "error",
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`Controller event stream returned HTTP ${response.status}`);
        }
        attempt = 0;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!subscription.stopped) {
          const { done, value } = await reader.read();
          if (done) break;
          resetIdle();
          buffer += decoder.decode(value, { stream: true });
          const parsed = consumeSseBuffer(buffer);
          buffer = parsed.rest;
          for (const message of parsed.messages) {
            if (message.id !== null) subscription.lastEventId = Math.max(subscription.lastEventId, message.id);
            this.send(subscription, message.event, message.id, parseSseData(message.data));
          }
        }
        if (!subscription.stopped) {
          this.send(subscription, "transport.error", null, {
            message: "Controller event stream closed; reconnecting.",
            retry_in_ms: 1_000,
          });
        }
      } catch (error) {
        if (subscription.stopped) return;
        const message = sanitizeMessage(error);
        this.send(subscription, "transport.error", null, {
          message: message.toLowerCase().includes("abort")
            ? "Event stream timed out; reconnecting."
            : message,
          retry_in_ms: Math.min(15_000, 500 * 2 ** attempt),
        });
      } finally {
        if (idleTimer) clearTimeout(idleTimer);
      }
      if (subscription.stopped) return;
      attempt += 1;
      await new Promise((resolve) => setTimeout(resolve, Math.min(15_000, 500 * 2 ** attempt)));
    }
  }

  private send(subscription: Subscription, event: string, id: number | null, data: unknown): void {
    if (subscription.stopped || subscription.sender.isDestroyed()) return;
    subscription.sender.send(IPC.eventsEvent, {
      subscription_id: subscription.id,
      event,
      id,
      data,
    });
  }
}
