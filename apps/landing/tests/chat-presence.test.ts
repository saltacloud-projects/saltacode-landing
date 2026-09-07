import assert from "node:assert/strict";
import test from "node:test";

import {
  createOperatorPresence,
  createVisitorPresence,
  operatorTypingExpiry,
  operatorTypingLabel,
  postVisitorPresence,
  type VisitorPresenceSignal,
} from "../src/scripts/chat-presence.ts";

function clock() {
  let now = 0;
  let id = 0;
  const pending = new Map<number, { callback: () => void; at: number }>();
  return {
    now: () => now,
    schedule: (callback: () => void, delay: number) => {
      pending.set(++id, { callback, at: now + delay });
      return id;
    },
    cancel: (timer: number) => { pending.delete(timer); },
    advance: (time: number) => {
      while (true) {
        const next = [...pending.entries()].filter(([, item]) => item.at <= time)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        now = next[1].at;
        pending.delete(next[0]);
        next[1].callback();
      }
      now = time;
    },
  };
}

test("operator typing requires a live explicit snapshot and remains distinct from automated activity", () => {
  const now = Date.now();
  for (const value of [undefined, null, {}, { operator: { typing: "true" } },
    { operator: { typing: true, expires_at: "invalid" } },
    { operator: { typing: true, expires_at: new Date(now - 1).toISOString() } }]) {
    assert.equal(operatorTypingExpiry(value, now), null);
  }
  assert.equal(operatorTypingExpiry({ operator: { typing: true,
    expires_at: new Date(now + 60_000).toISOString() } }, now), now + 8_000);
  assert.match(operatorTypingLabel(true, "human"), /persona.*escribiendo/);
  for (const mode of ["automated", "paused", "closed"] as const) {
    assert.equal(operatorTypingLabel(true, mode), "");
  }
  assert.equal(operatorTypingLabel(false, "human"), "");
});

test("operator renewals do not repeat announcements and expiry/disconnection remove presence", () => {
  const timer = clock();
  const changes: boolean[] = [];
  const receiver = createOperatorPresence((typing) => changes.push(typing), timer);
  receiver.receive({ operator: { typing: true, expires_at: new Date(8_000).toISOString() } });
  timer.advance(3_000);
  receiver.receive({ operator: { typing: true, expires_at: new Date(11_000).toISOString() } });
  timer.advance(8_000);
  assert.deepEqual(changes, [true]);
  timer.advance(11_000);
  assert.deepEqual(changes, [true, false]);
  receiver.receive({ operator: { typing: true, expires_at: new Date(19_000).toISOString() } });
  receiver.clear();
  timer.advance(30_000);
  assert.deepEqual(changes, [true, false, true, false]);
});

test("visitor presence requires existing enabled session and active nonempty editing; never sends draft content", () => {
  const timer = clock();
  let allowed = false;
  const signals: VisitorPresenceSignal[] = [];
  const sender = createVisitorPresence({ instanceId: "instance", clock: timer,
    canSend: () => allowed, send: async (signal) => { signals.push(signal); } });
  sender.edit(true);
  allowed = true;
  sender.edit(false);
  assert.equal(signals.length, 0);
  sender.edit(true);
  assert.deepEqual(signals, [{ client_instance_id: "instance", sequence: 1, typing: true }]);
  timer.advance(100);
  sender.edit(true);
  timer.advance(2_999);
  assert.equal(signals.length, 1);
  timer.advance(3_000);
  assert.deepEqual(signals.map((item) => item.typing), [true, true]);
  timer.advance(4_100);
  assert.deepEqual(signals.map((item) => item.typing), [true, true, false]);
  assert.deepEqual(signals.map((item) => item.sequence), [1, 2, 3]);
  timer.advance(100_000);
  assert.equal(signals.length, 3);
});

test("clear on blur, send, close or hide cancels delayed renewals and does not repeatedly signal false", () => {
  const timer = clock();
  const signals: VisitorPresenceSignal[] = [];
  const sender = createVisitorPresence({ instanceId: "tab", clock: timer,
    canSend: () => true, send: async (signal) => { signals.push(signal); } });
  sender.edit(true);
  timer.advance(100);
  sender.edit(true);
  sender.stop();
  sender.stop();
  timer.advance(30_000);
  assert.deepEqual(signals.map((item) => item.typing), [true, false]);
});

test("queued renewals recheck current focus/session and late failures cannot undo a newer signal", async () => {
  const timer = clock();
  let allowed = true;
  const signals: VisitorPresenceSignal[] = [];
  let rejectFirst: (reason: Error) => void = () => {};
  const sender = createVisitorPresence({ instanceId: "tab", clock: timer,
    canSend: () => allowed, send: (signal) => {
      signals.push(signal);
      return signal.sequence === 1 ? new Promise<void>((_, reject) => { rejectFirst = reject; }) : Promise.resolve();
    } });
  sender.edit(true);
  timer.advance(100);
  sender.edit(true);
  allowed = false;
  timer.advance(3_000);
  rejectFirst(new Error("old disconnected request"));
  await Promise.resolve();
  timer.advance(8_000);
  assert.deepEqual(signals.map((item) => item.typing), [true, false]);
});

test("presence transport sends only boolean identity metadata; stop uses keepalive without leaking fields", async () => {
  for (const typing of [true, false]) {
    let captured: RequestInit | undefined;
    await postVisitorPresence({ client_instance_id: "tab", sequence: 2, typing, draft: "must stay local" } as VisitorPresenceSignal,
      (async (path, init) => {
        assert.equal(path, "/api/v2/chat/presence");
        captured = init;
        return new Response(null, { status: 200 });
      }) as typeof fetch);
    assert.equal(captured?.credentials, "same-origin");
    assert.equal(captured?.keepalive, !typing);
    assert.deepEqual(JSON.parse(String(captured?.body)), { client_instance_id: "tab", sequence: 2, typing });
  }
});
