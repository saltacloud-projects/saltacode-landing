import chatStyles from "../styles/chat-preview.css?inline";
import { createClientMessageId } from "./client-message-id";
import { consumeChatStream } from "./chat-stream";
import { chatMarkup, chatResumeMarkup } from "./chat-template";
import {
  clearChatTranscript,
  loadChatTranscript,
  saveChatTranscript,
  type ChatTranscriptMessage,
  type ChatTranscriptState,
} from "./chat-transcript";

const PRIVACY_VERSION = "saltacode-chat-privacy-2026-08-28";
const CONSENT_STORAGE_KEY = "saltacode-chat-consent";
const PRIVACY_RESET_EVENT = "saltacode:privacy-reset";
const INITIAL_MESSAGE = "Hola, soy el asistente de SaltaCode. Contame qué necesitás resolver.";

interface PendingMessage {
  text: string;
  clientMessageId: string;
}

interface PendingLaunch extends PendingMessage {
  input: HTMLInputElement | null;
}

interface RenderedMessage {
  element: HTMLElement;
  paragraph: HTMLParagraphElement;
  record: ChatTranscriptMessage;
}

let dialog: HTMLDialogElement | undefined;
let composer: HTMLTextAreaElement;
let sendButton: HTMLButtonElement;
let sendLabel: HTMLElement;
let log: HTMLElement;
let status: HTMLElement;
let gate: HTMLElement;
let gateAccept: HTMLButtonElement;
let gateQuestion: HTMLElement;
let interactiveBody: HTMLElement[];
let returnFocus: HTMLElement | null;
let resumeButton: HTMLButtonElement | undefined;
let resumeLauncher: HTMLFormElement | undefined;
let pendingLaunch: PendingLaunch | undefined;
let currentController: AbortController | undefined;
let activeResponse: RenderedMessage | undefined;
let transcriptMessages: ChatTranscriptMessage[] = [];
let persistTimer: number | undefined;
let stylesApplied = false;
let sending = false;
let generation = 0;
let acceptedForPage = false;
let resettingPrivacy = false;

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

function saveCurrentTranscript(): void {
  if (!hasCurrentConsent()) return;
  if (!transcriptMessages.length) {
    clearChatTranscript(localStorage);
    return;
  }
  saveChatTranscript(localStorage, transcriptMessages);
}

function flushTranscript(): void {
  if (persistTimer !== undefined) window.clearTimeout(persistTimer);
  persistTimer = undefined;
  saveCurrentTranscript();
}

function scheduleTranscriptSave(): void {
  if (persistTimer !== undefined) return;
  persistTimer = window.setTimeout(flushTranscript, 300);
}

function setMessageState(rendered: RenderedMessage, text: string, state: ChatTranscriptState): void {
  rendered.record.text = text;
  rendered.record.state = state;
  rendered.paragraph.textContent = text;
  rendered.element.dataset.state = state;
  rendered.element.querySelector(".chat-message-note")?.remove();
  if (state === "interrupted") {
    const note = document.createElement("small");
    note.className = "chat-message-note";
    note.textContent = "Respuesta interrumpida. No se reenvió automáticamente.";
    rendered.element.append(note);
  }
}

function addMessage(
  role: "agent" | "user",
  text: string,
  state: ChatTranscriptState = "completed",
  remember = true,
): RenderedMessage {
  const element = document.createElement("article");
  const paragraph = document.createElement("p");
  const record = { role, text, state } satisfies ChatTranscriptMessage;
  element.className = "chat-message";
  element.dataset.role = role;
  paragraph.textContent = text;
  element.append(paragraph);
  log.append(element);
  const rendered = { element, paragraph, record };
  setMessageState(rendered, text, state);
  if (remember) {
    transcriptMessages.push(record);
    saveCurrentTranscript();
  }
  log.scrollTop = log.scrollHeight;
  return rendered;
}

function removeMessage(rendered: RenderedMessage): void {
  const index = transcriptMessages.indexOf(rendered.record);
  if (index >= 0) transcriptMessages.splice(index, 1);
  rendered.element.remove();
  saveCurrentTranscript();
}

function restoreTranscript(): void {
  transcriptMessages = [];
  if (!hasCurrentConsent()) {
    clearChatTranscript(localStorage);
    return;
  }
  const transcript = loadChatTranscript(localStorage);
  if (!transcript) return;
  transcriptMessages = transcript.messages.map((message) => ({ ...message }));
  for (const message of transcriptMessages) addMessage(message.role, message.text, message.state, false);
  const suggestions = log.querySelector<HTMLElement>(".chat-suggestions");
  if (suggestions) suggestions.hidden = true;
  status.textContent = "Conversación anterior restaurada en este dispositivo.";
}

function setBusy(value: boolean): void {
  sending = value;
  composer.disabled = value;
  sendButton.disabled = value;
  sendLabel.textContent = value ? "Enviando…" : "Enviar";
  sendButton.setAttribute("aria-label", value ? "Enviando mensaje" : "Enviar mensaje");
}

function addRetry(response: RenderedMessage, request: PendingMessage): void {
  if (response.element.querySelector("button")) return;
  const retry = document.createElement("button");
  retry.className = "chat-retry";
  retry.type = "button";
  retry.textContent = "Reintentar";
  retry.addEventListener("click", () => {
    removeMessage(response);
    void sendMessage(request, false);
  }, { once: true });
  response.element.append(retry);
}

async function sendMessage(request: PendingMessage, addUser = true): Promise<void> {
  const cleanText = request.text.trim();
  if (!cleanText || sending || !hasCurrentConsent()) return;

  if (addUser) addMessage("user", cleanText);
  composer.value = "";
  setBusy(true);
  const responseMessage = addMessage("agent", "Preparando una respuesta…", "pending");
  activeResponse = responseMessage;
  responseMessage.element.dataset.empty = "true";
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
    await consumeChatStream(response.body, {
      isActive: () => requestGeneration === generation && Boolean(dialog?.open),
      onDelta: (delta) => {
        const currentText = responseMessage.element.dataset.empty === "true"
          ? delta
          : responseMessage.paragraph.textContent + delta;
        responseMessage.element.dataset.empty = "false";
        setMessageState(responseMessage, currentText, "pending");
        scheduleTranscriptSave();
        status.textContent = "El asistente está respondiendo.";
        log.scrollTop = log.scrollHeight;
      },
      onError: (retryable) => {
        const text = retryable
          ? "No pude responder ahora. Podés reintentar o contactarnos."
          : "No pude procesar la consulta. Revisala e intentá otra vez.";
        setMessageState(responseMessage, text, "error");
        flushTranscript();
        status.textContent = "No fue posible completar la respuesta.";
        log.scrollTop = log.scrollHeight;
      },
      onDone: (outcome) => {
        if (outcome === "completed") {
          setMessageState(responseMessage, responseMessage.paragraph.textContent ?? "", "completed");
          flushTranscript();
          status.textContent = "Respuesta recibida.";
        } else if (responseMessage.record.state !== "error") throw new Error("stream_failed");
      },
    });
  } catch (error) {
    if (requestGeneration !== generation || (error instanceof DOMException && error.name === "AbortError")) return;
    setMessageState(responseMessage, "El asistente no está disponible. Podés reintentar o escribirnos.", "error");
    flushTranscript();
    addRetry(responseMessage, request);
    status.textContent = "El asistente no está disponible.";
  } finally {
    if (requestGeneration !== generation) return;
    activeResponse = undefined;
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
  if (activeResponse?.record.state === "pending") {
    const partial = activeResponse.element.dataset.empty === "true"
      ? "La respuesta se interrumpió al cerrar el chat."
      : activeResponse.paragraph.textContent ?? "La respuesta se interrumpió.";
    setMessageState(activeResponse, partial, "interrupted");
    activeResponse = undefined;
    flushTranscript();
  }
  generation += 1;
  currentController?.abort();
  currentController = undefined;
  if (sending) setBusy(false);
}

function ensureResumeButton(launcher: HTMLFormElement): HTMLButtonElement {
  resumeLauncher = launcher;
  if (resumeButton) return resumeButton;
  applyStyles();
  const button = document.createElement("button");
  button.className = "chat-resume";
  button.type = "button";
  button.setAttribute("aria-haspopup", "dialog");
  button.setAttribute("aria-label", "Continuar conversación con el asistente SaltaCode");
  button.innerHTML = chatResumeMarkup;
  button.hidden = true;
  button.addEventListener("click", () => {
    if (resumeLauncher) openDialog(resumeLauncher, null, "");
  });
  document.body.append(button);
  resumeButton = button;
  return button;
}

function configureWhatsappLink(element: HTMLDialogElement): void {
  const link = element.querySelector<HTMLAnchorElement>("[data-chat-whatsapp]");
  const canonical = document.querySelector<HTMLAnchorElement>('a[href^="https://wa.me/"]');
  if (!link || !canonical) {
    if (link) link.hidden = true;
    return;
  }
  link.href = canonical.href;
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
  sendLabel = element.querySelector(".chat-send-label")!;
  log = element.querySelector(".chat-log")!;
  status = element.querySelector('[role="status"]')!;
  gate = element.querySelector(".chat-consent-gate")!;
  gateAccept = element.querySelector(".chat-consent-accept")!;
  gateQuestion = element.querySelector(".chat-consent-question")!;
  interactiveBody = [log, element.querySelector(".chat-compose")!];
  configureWhatsappLink(element);
  restoreTranscript();

  element.querySelector<HTMLButtonElement>(".chat-close")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLButtonElement>(".chat-consent-cancel")!.addEventListener("click", () => element.close());
  gateAccept.addEventListener("click", acceptPendingLaunch);
  element.querySelectorAll<HTMLAnchorElement>(".chat-actions a").forEach((link) => {
    link.addEventListener("click", () => element.close());
  });
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
    if (!resettingPrivacy && resumeLauncher) ensureResumeButton(resumeLauncher).hidden = false;
    returnFocus?.focus();
  });
  return element;
}

function openDialog(launcher: HTMLFormElement, input: HTMLInputElement | null, text: string): void {
  resumeLauncher = launcher;
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : launcher;
  dialog ??= createDialog();
  if (dialog.open) {
    composer.focus();
    return;
  }

  ensureResumeButton(launcher).hidden = true;
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

function resetChatPrivacy(): void {
  resettingPrivacy = true;
  acceptedForPage = false;
  pendingLaunch = undefined;
  abortCurrentRequest();
  clearChatTranscript(localStorage);
  transcriptMessages = [];
  if (dialog?.open) dialog.close();
  dialog?.remove();
  dialog = undefined;
  resumeButton?.remove();
  resumeButton = undefined;
  resettingPrivacy = false;
}

window.addEventListener(PRIVACY_RESET_EVENT, resetChatPrivacy);

export function initializeChatResume(launcher: HTMLFormElement): void {
  if (!hasCurrentConsent()) {
    clearChatTranscript(localStorage);
    return;
  }
  if (loadChatTranscript(localStorage)) ensureResumeButton(launcher).hidden = false;
}

export function openChatPreview(launcher: HTMLFormElement): void {
  const question = launcher.elements.namedItem("question");
  const input = question instanceof HTMLInputElement ? question : null;
  openDialog(launcher, input, input?.value.trim() ?? "");
}
