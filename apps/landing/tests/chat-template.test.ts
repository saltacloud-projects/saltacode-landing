import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { chatMarkup } from "../src/scripts/chat-template.ts";

test("chat controls expose native mobile-friendly semantics", async () => {
  const markup = chatMarkup("Hola");
  const styles = await readFile(new URL("../src/styles/chat-preview.css", import.meta.url), "utf8");

  assert.match(markup, /<dialog|chat-layout/);
  assert.match(markup, /class="chat-close" type="button" aria-label="Cerrar chat"/);
  assert.match(markup, /data-chat-reset type="button">Nueva conversación/);
  assert.match(markup, /class="chat-send" type="submit" aria-label="Enviar mensaje"/);
  assert.match(markup, /role="log" aria-label="Conversación con el asistente"/);
  assert.match(markup, /role="status" aria-live="polite" aria-atomic="true"/);
  assert.match(styles, /@media\(max-width:620px\)/);
  assert.match(styles, /\.chat-send\{width:48px;flex:0 0 48px;padding:0\}/);
  assert.match(styles, /\.chat-send-label\{position:absolute;width:1px/);
  assert.match(styles, /\.chat-close\{[^}]*width:44px[^}]*height:44px/);
  assert.match(styles, /\.chat-row textarea\{[^}]*overflow-y:hidden/);
});
