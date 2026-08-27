const CHAT_STYLES = `.chat-preview{position:fixed;inset:1rem 1rem 1rem auto;width:min(460px,calc(100% - 2rem));max-width:none;height:calc(100dvh - 2rem);max-height:none;margin:0;padding:0;overflow:hidden;border:1px solid var(--line);border-radius:24px;color:var(--ink);background:var(--surface-raised);box-shadow:0 24px 80px rgb(0 0 0/.24)}.chat-preview::backdrop{background:rgb(8 6 14/.46);backdrop-filter:blur(3px)}body:has(.chat-preview[open]){overflow:hidden}.chat-layout{display:grid;height:100%;grid-template-rows:auto minmax(0,1fr) auto;background:var(--surface-raised)}.chat-head{display:flex;align-items:center;gap:.75rem;padding:1rem 1.1rem;border-bottom:1px solid var(--line)}.chat-head strong{display:block;line-height:1.2}.chat-badge{margin-left:auto;padding:.2rem .55rem;border-radius:999px;color:var(--purple-dark);background:var(--purple-soft);font-size:.72rem;font-weight:800}.chat-close{display:grid;width:42px;height:42px;padding:0;border:1px solid var(--line);border-radius:50%;color:var(--ink);background:var(--surface);font-size:1.4rem;cursor:pointer;place-items:center}.chat-log{display:flex;overflow-y:auto;overscroll-behavior:contain;flex-direction:column;gap:.75rem;padding:1.15rem}.chat-message{max-width:86%;padding:.75rem .9rem;border-radius:16px;background:var(--surface-soft);line-height:1.45;text-align:left}.chat-message[data-role=user]{align-self:flex-end;color:var(--on-accent);background:var(--button-accent);border-bottom-right-radius:5px}.chat-message[data-role=agent]{align-self:flex-start;border:1px solid var(--line);border-bottom-left-radius:5px}.chat-message p{margin:0}.chat-suggestions{display:flex;flex-wrap:wrap;gap:.45rem}.chat-suggestions button{min-height:38px;padding:.45rem .7rem;border:1px solid var(--line);border-radius:999px;color:var(--ink);background:var(--surface);font:inherit;font-size:.78rem;cursor:pointer}.chat-compose{padding:.9rem 1rem max(.9rem,env(safe-area-inset-bottom));border-top:1px solid var(--line);background:var(--surface)}.chat-compose label{display:block;margin-bottom:.45rem;color:var(--muted);font-size:.75rem}.chat-row{display:flex;align-items:flex-end;gap:.55rem}.chat-row textarea{width:100%;min-height:48px;max-height:120px;padding:.7rem .8rem;border:1px solid var(--line);border-radius:14px;color:var(--ink);background:var(--surface-raised);font:inherit;line-height:1.35;resize:vertical}.chat-actions{display:flex;justify-content:space-between;align-items:center;gap:.65rem;margin-top:.65rem}.chat-actions a{color:var(--purple-dark);font-size:.78rem;font-weight:750}.chat-send-demo{min-height:42px;padding:.6rem 1rem;border:0;border-radius:999px;color:var(--on-accent);background:var(--button-accent);font:inherit;font-weight:800;cursor:pointer}.chat-send-demo:disabled{cursor:wait;opacity:.6}@media(max-width:620px){.chat-preview{inset:0;width:100%;height:100dvh;border:0;border-radius:0}.chat-head{padding-top:max(1rem,env(safe-area-inset-top))}.chat-message{max-width:92%}}`;

const INITIAL_MESSAGE =
  "Hola. Esta es una vista previa del asistente de SaltaCode. Podés probar cómo sería una conversación, sin enviar ni guardar información.";
const DEMO_RESPONSE =
  "En la versión conectada voy a analizar tu necesidad, hacerte preguntas breves y orientarte hacia el servicio o próximo paso más conveniente.";

let dialog: HTMLDialogElement | undefined;
let composer: HTMLTextAreaElement;
let sendButton: HTMLButtonElement;
let log: HTMLElement;
let status: HTMLElement;
let returnFocus: HTMLElement | null;
let stylesApplied = false;

function applyStyles(): void {
  if (stylesApplied) return;
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(CHAT_STYLES);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  stylesApplied = true;
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

function demoReply(text: string): void {
  const cleanText = text.trim();
  if (!cleanText || sendButton.disabled) return;
  addMessage("user", cleanText);
  composer.value = "";
  composer.disabled = true;
  sendButton.disabled = true;
  const typing = addMessage("agent", "Preparando una respuesta…");
  status.textContent = "El asistente está preparando una respuesta.";

  globalThis.setTimeout(() => {
    typing.querySelector("p")!.textContent = DEMO_RESPONSE;
    composer.disabled = false;
    sendButton.disabled = false;
    status.textContent = "Respuesta de demostración disponible.";
    log.scrollTop = log.scrollHeight;
    composer.focus();
  }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 650);
}

function createDialog(): HTMLDialogElement {
  applyStyles();
  const element = document.createElement("dialog");
  element.className = "chat-preview";
  element.setAttribute("aria-labelledby", "chat-preview-title");
  element.innerHTML = `<section class="chat-layout"><header class="chat-head"><span aria-hidden="true">✦</span><div><strong id="chat-preview-title">Asistente SaltaCode</strong><small>Demo local · sin conexión</small></div><span class="chat-badge">Vista previa</span><button class="chat-close" type="button" aria-label="Cerrar chat">×</button></header><div class="chat-log" role="log" aria-label="Conversación de demostración"><article class="chat-message" data-role="agent"><p>${INITIAL_MESSAGE}</p></article><div class="chat-suggestions" aria-label="Consultas sugeridas"><button type="button">Necesito software a medida</button><button type="button">Quiero mejorar un proceso</button><button type="button">Busco un equipo IT</button></div></div><form class="chat-compose"><label for="chat-preview-message">Escribí una consulta para probar la experiencia</label><div class="chat-row"><textarea id="chat-preview-message" maxlength="800" rows="1" placeholder="Contanos qué necesitás…"></textarea><button class="chat-send-demo" type="submit">Enviar</button></div><div class="chat-actions"><a href="#contacto">Contactar a una persona</a><small>No se envían ni guardan datos.</small></div></form><p class="visually-hidden" role="status" aria-live="polite" aria-atomic="true"></p></section>`;
  document.body.append(element);

  composer = element.querySelector("textarea")!;
  sendButton = element.querySelector(".chat-send-demo")!;
  log = element.querySelector(".chat-log")!;
  status = element.querySelector('[role="status"]')!;
  element.querySelector<HTMLButtonElement>(".chat-close")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLAnchorElement>('.chat-actions a')!.addEventListener("click", () => element.close());
  element.querySelector<HTMLFormElement>(".chat-compose")!.addEventListener("submit", (event) => {
    event.preventDefault();
    demoReply(composer.value);
  });
  composer.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      demoReply(composer.value);
    }
  });
  element.querySelector(".chat-suggestions")!.addEventListener("click", (event) => {
    const suggestion = (event.target as HTMLElement).closest<HTMLButtonElement>("button");
    if (suggestion) demoReply(suggestion.textContent ?? "");
  });
  element.addEventListener("close", () => returnFocus?.focus());
  return element;
}

export function openChatPreview(launcher: HTMLFormElement): void {
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : launcher;
  dialog ??= createDialog();
  if (!dialog.open) dialog.showModal();

  const question = launcher.elements.namedItem("question");
  const initialQuestion = question instanceof HTMLInputElement ? question.value : "";
  if (question instanceof HTMLInputElement) question.value = "";
  if (initialQuestion.trim()) demoReply(initialQuestion);
  else composer.focus();
}
