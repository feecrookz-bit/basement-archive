import { EventEmitter } from "node:events";

export interface BasementEvent {
  type:
    | "safety.transition"
    | "rain_delay.set"
    | "rain_delay.clear"
    | "match_interval.set"
    | "geofence.alarm";
  /** Wall-clock ISO timestamp the event was emitted. */
  at: string;
  data: Record<string, unknown>;
}

class Bus extends EventEmitter {
  emitEvent(ev: BasementEvent): void {
    this.emit("event", ev);
  }
  onEvent(handler: (ev: BasementEvent) => void): () => void {
    this.on("event", handler);
    return () => this.off("event", handler);
  }
}

// Singleton in-process bus. Sprint 6 fans out via SSE; a future Redis pub/sub
// adapter would replace this without route changes.
export const bus = new Bus();
bus.setMaxListeners(0);
