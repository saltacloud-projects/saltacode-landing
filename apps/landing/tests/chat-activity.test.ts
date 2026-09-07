import assert from "node:assert/strict";
import test from "node:test";

import { chatActivityLabel, parseChatActivity } from "../src/scripts/chat-activity.ts";

test("activity requires an explicit server snapshot and ignores receipt or unknown phases", () => {
  assert.equal(parseChatActivity(undefined), null);
  assert.equal(parseChatActivity(null), null);
  assert.equal(parseChatActivity({ status: "accepted" }), null);
  assert.equal(parseChatActivity({ status: "completed" }), null);
  assert.deepEqual(parseChatActivity({ status: "queued" }), { status: "queued" });
  assert.deepEqual(parseChatActivity({ status: "running" }), { status: "running" });
  assert.equal(chatActivityLabel(null, "automated"), "");
});

test("queued and running mean different things and human control suppresses both", () => {
  assert.match(chatActivityLabel({ status: "queued" }, "automated"), /en espera/);
  assert.match(chatActivityLabel({ status: "running" }, "automated"), /preparando/);
  for (const mode of ["human", "paused", "closed"] as const) {
    assert.equal(chatActivityLabel({ status: "running" }, mode), "");
    assert.equal(chatActivityLabel({ status: "queued" }, mode), "");
  }
});
