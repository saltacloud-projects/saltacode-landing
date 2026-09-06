import chatStyleUrl from "../styles/chat-preview.css?url";
import {
  ChatApiError,
  loadOrUpgradeServerHistory,
  mapServerMessage,
  postChatMessage,
  resetServerChat,
  type ChatHistory,
} from "./chat-api";
import { createClientMessageId } from "./client-message-id";
import { reconnectChatEvents, type ChatEvent } from "./chat-stream";
import { chatMarkup, chatResumeMarkup } from "./chat-template";
import {
  applyChatEvent,
  clearChatTranscript,
  emptyChatTranscript,
  loadChatTranscript,
  saveChatTranscript,
  type ChatControlMode,
  type ChatTranscriptMessage,
  type PendingChatMessage,
} from "./chat-transcript";

const PRIVACY_VERSION = "saltacode-chat-privacy-2026-08-28";
const CONSENT_STORAGE_KEY = "saltacode-chat-consent";
const PRIVACY_RESET_EVENT = "saltacode:privacy-reset";
const INITIAL_MESSAGE = "Hola, soy el asistente de SaltaCode. Contame qué necesitás resolver.";

interface PendingLaunch extends PendingChatMessage {
  input: HTMLInputElement | null;
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
let streamController: AbortController | undefined;
let transcript = emptyChatTranscript();
let synchronization: Promise<ChatHistory | null> | undefined;
let stylesReady: Promise<void> | undefined;
let stylesApplied = false;
let posting = false;
let acceptedForPage = false;
let resettingPrivacy = false;
let hasServerSession = false;

function applyStyles(): Promise<void> {
  if (stylesApplied) return Promise.resolve();
  stylesReady ??= new Promise((resolve) => {
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = chatStyleUrl;
    stylesheet.addEventListener("load", () => {
      stylesApplied = true;
      resolve();
    }, { once: true });
    stylesheet.addEventListener("error", () => resolve(), { once: true });
    document.head.append(stylesheet);
  });
  return stylesReady;
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
    // Consent remains valid for this page when storage is unavailable.
  }
}

function persistTranscript(): void {
  if (!hasCurrentConsent()) return;
  if (!transcript.messages.length && !transcript.pending.length) {
    clearChatTranscript(localStorage);
    return;
  }
  saveChatTranscript(localStorage, transcript);
}

function controlStatus(mode: ChatControlMode): string {
  if (mode === "human") return "Una persona del equipo está atendiendo esta conversación.";
  if (mode === "paused") return "La respuesta automática está pausada. El equipo puede intervenir.";
  if (mode === "closed") return "Esta conversación está cerrada. Iniciá una nueva para continuar.";
  return "Conversación conectada.";
}

function setPosting(value: boolean): void {
  posting = value;
  sendButton.disabled = value || transcript.controlMode === "closed";
  composer.disabled = transcript.controlMode === "closed";
  sendLabel.textContent = value ? "Enviando…" : "Enviar";
  sendButton.setAttribute("aria-label", value ? "Enviando mensaje" : "Enviar mensaje");
}

function renderMessage(message: ChatTranscriptMessage): HTMLElement {
  const element = document.createElement("article");
  const paragraph = document.createElement("p");
  element.className = "chat-message";
  element.dataset.role = message.role;
  element.dataset.state = message.state;
  element.dataset.messageId = message.id;
  element.dataset.serverMessage = "true";
  paragraph.textContent = message.text;
  element.append(paragraph);
  return element;
}

function visibleMessages(): ChatTranscriptMessage[] {
  const serverClientIds = new Set(transcript.messages.map((message) => message.clientMessageId));
  const optimistic = transcript.pending
    .filter((message) => !serverClientIds.has(message.clientMessageId))
    .map((message) => ({
      id: `pending:${message.clientMessageId}`,
      clientMessageId: message.clientMessageId,
      role: "user" as const,
      text: message.text,
      state: message.status === "accepted" ? "accepted" as const : "pending" as const,
      createdAt: new Date().toISOString(),
    }));
  return [...transcript.messages, ...optimistic];
}

function renderTranscript(): void {
  log.querySelectorAll("[data-server-message], [data-transient]").forEach((element) => element.remove());
  const suggestions = log.querySelector<HTMLElement>(".chat-suggestions");
  const messages = visibleMessages();
  for (const message of messages) log.insertBefore(renderMessage(message), suggestions ?? null);
  if (suggestions) suggestions.hidden = messages.length > 0;
  log.scrollTop = log.scrollHeight;
  setPosting(posting);
}

function showTransientError(text: string, retry?: PendingChatMessage): void {
  const element = document.createElement("article");
  const paragraph = document.createElement("p");
  element.className = "chat-message";
  element.dataset.role = "assistant";
  element.dataset.state = "error";
  element.dataset.transient = "true";
  paragraph.textContent = text;
  element.append(paragraph);
  if (retry) {
    const button = document.createElement("button");
    button.className = "chat-retry";
    button.type = "button";
    button.textContent = "Reintentar";
    button.addEventListener("click", () => {
      element.remove();
      void deliverMessage(retry, false);
    }, { once: true });
    element.append(button);
  }
  log.append(element);
  log.scrollTop = log.scrollHeight;
}

function reconcilePending(history: ChatHistory): void {
  const serverByClientId = new Map(history.messages.map((message) => [message.client_message_id, message]));
  transcript.pending = transcript.pending.filter((pending) => {
    const inbound = serverByClientId.get(pending.clientMessageId);
    const output = serverByClientId.get(`${pending.clientMessageId}:assistant`);
    if (output) return false;
    if (inbound) pending.status = "accepted";
    return true;
  });
}

async function synchronizeHistory(): Promise<ChatHistory | null> {
  synchronization ??= loadOrUpgradeServerHistory().finally(() => { synchronization = undefined; });
  const history = await synchronization;
  if (!history) {
    hasServerSession = false;
    transcript.messages = [];
    transcript.pending = transcript.pending.filter((message) => message.status === "sending");
    transcript.latestEventId = 0;
    transcript.controlMode = "automated";
    persistTranscript();
    renderTranscript();
    return null;
  }
  hasServerSession = true;
  transcript.messages = history.messages.map(mapServerMessage);
  transcript.latestEventId = history.latest_event_id;
  transcript.controlMode = history.control_mode;
  reconcilePending(history);
  persistTranscript();
  renderTranscript();
  status.textContent = controlStatus(history.control_mode);
  return history;
}

function applyEvent(event: ChatEvent): void {
  const result = applyChatEvent(transcript, event);
  if (result.receivedRole) {
    status.textContent = result.receivedRole === "assistant" ? "Respuesta recibida." : "Mensaje recibido.";
  }
  if (result.failed) status.textContent = "No fue posible completar la respuesta.";
  if (event.event_type === "chat.error") {
    status.textContent = "La conexión se interrumpió. Intentando reconectar…";
  }
  if (result.controlChanged) {
    status.textContent = controlStatus(transcript.controlMode);
    if (transcript.controlMode === "closed") streamController?.abort();
  }
  if (event.event_type?.includes("control")) void synchronizeHistory().catch(() => undefined);
  persistTranscript();
  renderTranscript();
}

function startEventStream(): void {
  if (!dialog?.open || !hasServerSession || transcript.controlMode === "closed") return;
  streamController?.abort();
  const controller = new AbortController();
  streamController = controller;
  void reconnectChatEvents({
    initialCursor: transcript.latestEventId,
    signal: controller.signal,
    isActive: () => Boolean(dialog?.open) && streamController === controller,
    onEvent: applyEvent,
    onCursorExpired: async () => (await synchronizeHistory())?.latest_event_id ?? 0,
    onRetry: () => { status.textContent = "Reconectando la conversación…"; },
  });
}

async function deliverMessage(message: PendingChatMessage, isNew: boolean): Promise<void> {
  if (posting || !hasCurrentConsent() || transcript.controlMode === "closed") return;
  if (isNew) {
    transcript.pending = [...transcript.pending, message].slice(-8);
    persistTranscript();
    renderTranscript();
  }
  composer.value = "";
  composer.style.height = "48px";
  composer.style.overflowY = "hidden";
  setPosting(true);
  status.textContent = "Enviando mensaje.";

  try {
    const accepted = await postChatMessage(
      message,
      PRIVACY_VERSION,
      document.documentElement.lang === "en" ? "en" : "es-AR",
    );
    if (accepted.client_message_id !== message.clientMessageId) throw new Error("message_identity_changed");
    const inbound: ChatTranscriptMessage = {
      id: accepted.message_id,
      clientMessageId: message.clientMessageId,
      role: "user",
      text: message.text,
      state: "accepted",
      createdAt: new Date().toISOString(),
    };
    const inboundIndex = transcript.messages.findIndex((item) => item.id === accepted.message_id);
    if (inboundIndex >= 0) transcript.messages[inboundIndex] = inbound;
    else transcript.messages.push(inbound);
    const pending = transcript.pending.find((item) => item.clientMessageId === message.clientMessageId);
    if (pending) pending.status = "accepted";
    hasServerSession = true;
    persistTranscript();
    renderTranscript();
    status.textContent = accepted.duplicate
      ? "Mensaje recuperado sin duplicarlo."
      : "Mensaje recibido por el asistente.";
    startEventStream();
  } catch (error) {
    if (error instanceof ChatApiError && error.status === 409) {
      await synchronizeHistory().catch(() => null);
      const persisted = transcript.messages.some((item) => item.clientMessageId === message.clientMessageId);
      if (persisted) {
        const pending = transcript.pending.find((item) => item.clientMessageId === message.clientMessageId);
        if (pending) pending.status = "accepted";
        status.textContent = "Mensaje recuperado sin duplicarlo.";
        startEventStream();
        return;
      }
    }
    if (error instanceof ChatApiError && error.status === 423) {
      transcript.pending = transcript.pending.filter((item) => item.clientMessageId !== message.clientMessageId);
      persistTranscript();
      renderTranscript();
      showTransientError("El equipo está atendiendo esta conversación. Esperá su respuesta o contactanos.");
    } else {
      showTransientError("No pude confirmar el envío. Reintentá sin duplicar tu mensaje.", message);
    }
    status.textContent = "No fue posible confirmar el mensaje.";
  } finally {
    setPosting(false);
    if (dialog?.open) composer.focus();
  }
}

async function resumeConversation(launch?: PendingLaunch): Promise<void> {
  try {
    const history = await synchronizeHistory();
    const persistedClientIds = new Set(history?.messages.map((message) => message.client_message_id) ?? []);
    for (const pending of transcript.pending) {
      if (persistedClientIds.has(pending.clientMessageId)) pending.status = "accepted";
      else if (pending.status === "sending") await deliverMessage(pending, false);
    }
    if (launch?.text) {
      if (launch.input) launch.input.value = "";
      await deliverMessage(launch, true);
    }
    if (hasServerSession) startEventStream();
  } catch {
    if (launch?.text) await deliverMessage(launch, true);
    else showTransientError("No pude recuperar la conversación. Podés reintentar en unos segundos.");
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
  void resumeConversation(request);
}

function ensureResumeButton(launcher: HTMLFormElement): HTMLButtonElement {
  resumeLauncher = launcher;
  if (resumeButton) return resumeButton;
  const button = document.createElement("button");
  button.className = "chat-resume";
  button.type = "button";
  button.setAttribute("aria-haspopup", "dialog");
  button.setAttribute("aria-label", "Continuar conversación con el asistente SaltaCode");
  button.innerHTML = chatResumeMarkup;
  button.hidden = true;
  button.addEventListener("click", () => openDialog(launcher, null, ""));
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

async function resetConversation(): Promise<void> {
  if (!window.confirm("¿Querés cerrar esta conversación e iniciar una nueva?")) return;
  setPosting(true);
  try {
    let cursor = 0;
    const existing = hasServerSession ? true : Boolean(await loadOrUpgradeServerHistory());
    if (existing) {
      try {
        cursor = await resetServerChat(PRIVACY_VERSION);
        hasServerSession = true;
      } catch (error) {
        if (!(error instanceof ChatApiError && error.status === 404)) throw error;
        hasServerSession = false;
      }
    } else {
      hasServerSession = false;
    }
    streamController?.abort();
    transcript = emptyChatTranscript();
    transcript.latestEventId = cursor;
    clearChatTranscript(localStorage);
    renderTranscript();
    status.textContent = "Nueva conversación lista.";
  } catch {
    status.textContent = "No fue posible iniciar una nueva conversación.";
  } finally {
    setPosting(false);
    composer.focus();
  }
}

function createDialog(): HTMLDialogElement {
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
  transcript = hasCurrentConsent() ? loadChatTranscript(localStorage) ?? emptyChatTranscript() : emptyChatTranscript();
  renderTranscript();

  function resizeComposer(): void {
    composer.style.height = "48px";
    const maxHeight = window.matchMedia("(max-width: 620px)").matches ? 96 : 120;
    composer.style.height = `${Math.min(composer.scrollHeight, maxHeight)}px`;
    composer.style.overflowY = composer.scrollHeight > maxHeight ? "auto" : "hidden";
  }

  element.querySelector<HTMLButtonElement>(".chat-close")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLButtonElement>(".chat-consent-cancel")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLButtonElement>("[data-chat-reset]")!.addEventListener("click", () => {
    void resetConversation();
  });
  gateAccept.addEventListener("click", acceptPendingLaunch);
  element.querySelectorAll<HTMLAnchorElement>(".chat-actions a").forEach((link) => {
    link.addEventListener("click", () => element.close());
  });
  element.querySelector<HTMLFormElement>(".chat-compose")!.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = composer.value.trim();
    if (text) void deliverMessage({ text, clientMessageId: createClientMessageId(), status: "sending" }, true);
  });
  composer.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      const text = composer.value.trim();
      if (text) void deliverMessage({ text, clientMessageId: createClientMessageId(), status: "sending" }, true);
    }
  });
  composer.addEventListener("input", resizeComposer);
  element.querySelector(".chat-suggestions")!.addEventListener("click", (event) => {
    const suggestion = (event.target as HTMLElement).closest<HTMLButtonElement>("button");
    if (suggestion) {
      composer.value = suggestion.textContent ?? "";
      composer.focus();
    }
  });
  element.addEventListener("close", () => {
    streamController?.abort();
    streamController = undefined;
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
  pendingLaunch = { text, clientMessageId: createClientMessageId(), status: "sending", input };
  dialog.showModal();
  if (!hasCurrentConsent()) {
    showConsent(pendingLaunch);
    return;
  }

  hideConsent();
  const request = pendingLaunch;
  pendingLaunch = undefined;
  void resumeConversation(request).finally(() => {
    if (dialog?.open && !request.text) composer.focus();
  });
}

function resetChatPrivacy(): void {
  resettingPrivacy = true;
  acceptedForPage = false;
  pendingLaunch = undefined;
  streamController?.abort();
  streamController = undefined;
  clearChatTranscript(localStorage);
  transcript = emptyChatTranscript();
  hasServerSession = false;
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
  if (loadChatTranscript(localStorage)) void applyStyles().then(() => {
    ensureResumeButton(launcher).hidden = false;
  });
}

export async function openChatPreview(launcher: HTMLFormElement): Promise<void> {
  await applyStyles();
  const question = launcher.elements.namedItem("question");
  const input = question instanceof HTMLInputElement ? question : null;
  openDialog(launcher, input, input?.value.trim() ?? "");
}
