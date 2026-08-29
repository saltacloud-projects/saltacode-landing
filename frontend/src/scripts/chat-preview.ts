import chatStyles from "../styles/chat-preview.css?inline";
import { createClientMessageId } from "./client-message-id";
import { consumeChatStream } from "./chat-stream";
import { chatMarkup } from "./chat-template";

const PRIVACY_VERSION = "saltacode-chat-privacy-2026-08-28";
const CONSENT_STORAGE_KEY = "saltacode-chat-consent";
const INITIAL_MESSAGE = "Hola, soy el asistente de SaltaCode. Contame qué necesitás resolver.";

interface PendingMessage {
  text: string;
  clientMessageId: string;
}

interface PendingLaunch extends PendingMessage {
  input: HTMLInputElement | null;
}

let dialog: HTMLDialogElement | undefined;
let composer: HTMLTextAreaElement;
let sendButton: HTMLButtonElement;
let log: HTMLElement;
let status: HTMLElement;
let gate: HTMLElement;
let gateAccept: HTMLButtonElement;
let gateQuestion: HTMLElement;
let interactiveBody: HTMLElement[];
let returnFocus: HTMLElement | null;
let pendingLaunch: PendingLaunch | undefined;
let currentController: AbortController | undefined;
let stylesApplied = false;
let sending = false;
let generation = 0;
let acceptedForPage = false;

function applyStyles(): void {
  if (stylesApplied) return;
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(chatStyles);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  stylesApplied = true;
}

function hasCurrentConsent(): boolean {
  if (acceptedForPage) return true;
  try {
    const value = JSON.parse(localStorage.getItem(CONSENT_STORAGE_KEY) ?? "null") as unknown;
    if (!value || typeof value !== "object") return false;
    const record = value as { version?: unknown; acceptedAt?: unknown };
    return record.version === PRIVACY_VERSION &&
      typeof record.acceptedAt === "string" &&
      Number.isFinite(Date.parse(record.acceptedAt));
  } catch {
    return false;
  }
}

function rememberConsent(): void {
  acceptedForPage = true;
  try {
    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify({
      version: PRIVACY_VERSION,
      acceptedAt: new Date().toISOString(),
    }));
  } catch {
    // Consent remains valid for this page when local storage is unavailable.
  }
}

function addMessage(role: "agent" | "user", text: string): HTMLElement {
  const message = document.createElement("article");
  const paragraph = document.createElement("p");
  message.className = "chat-message";
  message.dataset.role = role;
  paragraph.textContent = text;
  message.append(paragraph);
  log.append(message);
  log.scrollTop = log.scrollHeight;
  return message;
}

function setBusy(value: boolean): void {
  sending = value;
  composer.disabled = value;
  sendButton.disabled = value;
  sendButton.textContent = value ? "Enviando…" : "Enviar";
}

function addRetry(response: HTMLElement, request: PendingMessage): void {
  if (response.querySelector("button")) return;
  const retry = document.createElement("button");
  retry.className = "chat-retry";
  retry.type = "button";
  retry.textContent = "Reintentar";
  retry.addEventListener("click", () => {
    response.remove();
    void sendMessage(request, false);
  }, { once: true });
  response.append(retry);
}

async function sendMessage(request: PendingMessage, addUser = true): Promise<void> {
  const cleanText = request.text.trim();
  if (!cleanText || sending || !hasCurrentConsent()) return;

  if (addUser) addMessage("user", cleanText);
  composer.value = "";
  setBusy(true);
  const responseMessage = addMessage("agent", "Preparando una respuesta…");
  responseMessage.dataset.empty = "true";
  status.textContent = "Conectando con el asistente.";
  const requestGeneration = ++generation;
  const controller = new AbortController();
  currentController = controller;

  try {
    const response = await fetch("/api/v1/chat", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        client_message_id: request.clientMessageId,
        message: cleanText,
        locale: document.documentElement.lang === "en" ? "en" : "es-AR",
        transcript_consent: true,
        privacy_version: PRIVACY_VERSION,
      }),
    });
    if (!response.ok || !response.body) throw new Error(`http_${response.status}`);
    const paragraph = responseMessage.querySelector("p")!;
    await consumeChatStream(response.body, {
      isActive: () => requestGeneration === generation && Boolean(dialog?.open),
      onDelta: (delta) => {
        if (responseMessage.dataset.empty === "true") paragraph.textContent = "";
        responseMessage.dataset.empty = "false";
        paragraph.textContent += delta;
        status.textContent = "El asistente está respondiendo.";
        log.scrollTop = log.scrollHeight;
      },
      onError: (retryable) => {
        responseMessage.dataset.state = "error";
        paragraph.textContent = retryable
          ? "No pude responder ahora. Podés reintentar o contactarnos."
          : "No pude procesar la consulta. Revisala e intentá otra vez.";
        status.textContent = "No fue posible completar la respuesta.";
        log.scrollTop = log.scrollHeight;
      },
      onDone: (outcome) => {
        if (outcome === "completed") status.textContent = "Respuesta recibida.";
        else if (responseMessage.dataset.state !== "error") throw new Error("stream_failed");
      },
    });
  } catch (error) {
    if (requestGeneration !== generation || (error instanceof DOMException && error.name === "AbortError")) return;
    responseMessage.dataset.state = "error";
    responseMessage.querySelector("p")!.textContent =
      "El asistente no está disponible. Podés reintentar o escribirnos.";
    addRetry(responseMessage, request);
    status.textContent = "El asistente no está disponible.";
  } finally {
    if (requestGeneration !== generation) return;
    currentController = undefined;
    setBusy(false);
    composer.focus();
    log.scrollTop = log.scrollHeight;
  }
}

function showConsent(request: PendingLaunch): void {
  gate.hidden = false;
  gateQuestion.hidden = !request.text;
  gateQuestion.textContent = request.text ? `“${request.text}”` : "";
  gateAccept.textContent = request.text ? "Aceptar y enviar" : "Aceptar y continuar";
  interactiveBody.forEach((element) => { element.inert = true; });
  requestAnimationFrame(() => gateAccept.focus());
}

function hideConsent(): void {
  gate.hidden = true;
  interactiveBody.forEach((element) => { element.inert = false; });
}

function acceptPendingLaunch(): void {
  rememberConsent();
  hideConsent();
  const request = pendingLaunch;
  pendingLaunch = undefined;
  if (!request) {
    composer.focus();
    return;
  }
  if (request.input) request.input.value = "";
  if (request.text) void sendMessage(request);
  else composer.focus();
}

function abortCurrentRequest(): void {
  generation += 1;
  currentController?.abort();
  currentController = undefined;
  if (sending) setBusy(false);
}

function createDialog(): HTMLDialogElement {
  applyStyles();
  const element = document.createElement("dialog");
  element.className = "chat-preview";
  element.setAttribute("aria-labelledby", "chat-preview-title");
  element.innerHTML = chatMarkup(INITIAL_MESSAGE);
  document.body.append(element);

  composer = element.querySelector("textarea")!;
  sendButton = element.querySelector(".chat-send")!;
  log = element.querySelector(".chat-log")!;
  status = element.querySelector('[role="status"]')!;
  gate = element.querySelector(".chat-consent-gate")!;
  gateAccept = element.querySelector(".chat-consent-accept")!;
  gateQuestion = element.querySelector(".chat-consent-question")!;
  interactiveBody = [log, element.querySelector(".chat-compose")!];

  element.querySelector<HTMLButtonElement>(".chat-close")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLButtonElement>(".chat-consent-cancel")!.addEventListener("click", () => element.close());
  gateAccept.addEventListener("click", acceptPendingLaunch);
  element.querySelector<HTMLAnchorElement>(".chat-actions a")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLFormElement>(".chat-compose")!.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendMessage({ text: composer.value, clientMessageId: createClientMessageId() });
  });
  composer.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void sendMessage({ text: composer.value, clientMessageId: createClientMessageId() });
    }
  });
  element.querySelector(".chat-suggestions")!.addEventListener("click", (event) => {
    const suggestion = (event.target as HTMLElement).closest<HTMLButtonElement>("button");
    if (suggestion) {
      composer.value = suggestion.textContent ?? "";
      composer.focus();
    }
  });
  element.addEventListener("close", () => {
    abortCurrentRequest();
    pendingLaunch = undefined;
    hideConsent();
    returnFocus?.focus();
  });
  return element;
}

export function openChatPreview(launcher: HTMLFormElement): void {
  const question = launcher.elements.namedItem("question");
  const input = question instanceof HTMLInputElement ? question : null;
  const text = input?.value.trim() ?? "";
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : launcher;
  dialog ??= createDialog();
  if (dialog.open) {
    composer.focus();
    return;
  }

  pendingLaunch = { text, clientMessageId: createClientMessageId(), input };
  dialog.showModal();
  if (!hasCurrentConsent()) {
    showConsent(pendingLaunch);
    return;
  }

  hideConsent();
  const request = pendingLaunch;
  pendingLaunch = undefined;
  if (request.input) request.input.value = "";
  if (request.text) void sendMessage(request);
  else composer.focus();
}
