import assert from "node:assert/strict";
import test from "node:test";

import {
  chatAuthorLabel,
  chatMessageStatus,
  chatMessageTime,
  parseChatAuthor,
} from "../src/scripts/chat-presentation.ts";

test("message authors use actual metadata rather than current conversation control", () => {
  assert.equal(chatAuthorLabel({ role: "user" }), "Vos");
  assert.equal(chatAuthorLabel({ role: "assistant", authorType: "agent" }), "Asistente IA");
  assert.equal(chatAuthorLabel({ role: "assistant", authorType: "operator" }), "Operador");
  assert.equal(chatAuthorLabel({ role: "assistant", authorType: "system" }), "Sistema");
  assert.equal(chatAuthorLabel({ role: "assistant" }), "SaltaCode");
  assert.equal(chatAuthorLabel({ role: "assistant", authorType: "unknown" }), "SaltaCode");
  assert.equal(parseChatAuthor("<script>"), undefined);
});

test("received messages never claim to have been read", () => {
  assert.equal(chatMessageStatus({ role: "user", state: "pending" }), "Enviando…");
  assert.equal(chatMessageStatus({ role: "user", state: "accepted" }), "Recibido");
  assert.equal(chatMessageStatus({ role: "user", state: "completed" }), "Recibido");
  assert.equal(chatMessageStatus({ role: "assistant", state: "completed" }), "");
  assert.equal(chatMessageStatus({ role: "assistant", state: "error" }), "No completado");
});

test("message time formats an actual timestamp and omits missing or invalid evidence", () => {
  const timestamp = "2026-09-07T12:40:00Z";
  assert.equal(chatMessageTime(timestamp)?.label,
    new Date(timestamp).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" }));
  assert.ok(chatMessageTime(timestamp)?.title.includes("2026"));
  assert.equal(chatMessageTime(""), null);
  assert.equal(chatMessageTime("invalid"), null);
});
