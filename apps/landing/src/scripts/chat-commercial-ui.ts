import commercialStyleUrl from "../styles/chat-commercial.css?url";
import {
  CommercialContactApiError,
  applyCommercialEventCorrelation,
  commercialContactMarkup,
  isValidCommercialContact,
  parseCommercialContactPrompt,
  postCommercialContact,
  type CommercialContactPayload,
  type CommercialContactPrompt,
  type CommercialDeliveryChannel,
  type CommercialEventCorrelation,
} from "./chat-commercial";
import { createClientMessageId } from "./client-message-id";
import type { ChatEvent } from "./chat-stream";

export interface CommercialContactController {
  clearSensitiveValue: () => void;
  handleEvent: (event: ChatEvent) => void;
  reset: () => void;
}

interface CommercialContactControllerOptions {
  log: HTMLElement;
  privacyVersion: string;
  setChatStatus: (message: string) => void;
}

interface ActiveCommercialRequest {
  accepted: boolean;
  clientRequestId: string;
  correlation: CommercialEventCorrelation;
  prompt: CommercialContactPrompt;
  submitting: boolean;
}
function applyContactMode(element: HTMLElement, channel: CommercialDeliveryChannel, clear: boolean): void {
  const input = element.querySelector<HTMLInputElement>("[data-commercial-contact]")!;
  const label = element.querySelector<HTMLElement>("[data-commercial-contact-label]")!;
  input.setCustomValidity("");
  if (clear) input.value = "";
  if (channel === "email") {
    label.textContent = "Email";
    input.type = "email";
    input.inputMode = "email";
    input.autocomplete = "email";
    input.placeholder = "nombre@empresa.com";
    input.removeAttribute("pattern");
    return;
  }
  label.textContent = "Número de WhatsApp";
  input.type = "tel";
  input.inputMode = "tel";
  input.autocomplete = "tel";
  input.placeholder = "+549387...";
  input.pattern = "\\+[1-9][0-9]{7,14}";
}

function setControlsDisabled(element: HTMLElement, disabled: boolean): void {
  element.querySelectorAll<HTMLInputElement>("input").forEach((input) => { input.disabled = disabled; });
}

function markAccepted(
  element: HTMLElement,
  active: ActiveCommercialRequest,
  setChatStatus: (message: string) => void,
): void {
  if (active.accepted) return;
  active.accepted = true;
  active.submitting = false;
  element.querySelector<HTMLInputElement>("[data-commercial-contact]")!.value = "";
  setControlsDisabled(element, true);
  element.querySelector<HTMLButtonElement>(".chat-commercial-submit")!.hidden = true;
  element.querySelector<HTMLElement>(".chat-commercial-status")!.textContent =
    "Solicitud recibida. El equipo continuará por el canal elegido.";
  setChatStatus("Solicitud de presupuesto recibida.");
}

export function createCommercialContactController(
  options: CommercialContactControllerOptions,
): CommercialContactController {
  let element: HTMLElement | undefined;
  let active: ActiveCommercialRequest | undefined;

  function render(prompt: CommercialContactPrompt, correlation: CommercialEventCorrelation): void {
    element?.remove();
    const wrapper = document.createElement("div");
    wrapper.innerHTML = commercialContactMarkup();
    element = wrapper.firstElementChild as HTMLElement;
    active = {
      accepted: false,
      clientRequestId: createClientMessageId(),
      correlation,
      prompt,
      submitting: false,
    };
    element.querySelector<HTMLElement>("#chat-commercial-title")!.textContent = prompt.title;
    element.querySelector<HTMLElement>("[data-commercial-summary]")!.textContent = prompt.summary;
    const radios = [...element.querySelectorAll<HTMLInputElement>('[name="delivery-channel"]')];
    const preferred = radios.find((radio) => radio.value === prompt.preferredDeliveryChannel)!;
    preferred.checked = true;
    applyContactMode(element, prompt.preferredDeliveryChannel, false);
    for (const radio of radios) {
      radio.addEventListener("change", () => applyContactMode(element!, radio.value as CommercialDeliveryChannel, true));
    }
    element.querySelector<HTMLFormElement>("[data-commercial-form]")!.addEventListener("submit", submit);
    options.log.append(element);
    options.log.scrollTop = options.log.scrollHeight;
    options.setChatStatus("Podés elegir cómo recibir el presupuesto y compartir tus datos.");
    element.querySelector<HTMLElement>("#chat-commercial-title")!.focus({ preventScroll: true });
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!element || !active || active.submitting || active.accepted) return;
    const form = event.currentTarget as HTMLFormElement;
    const contact = element.querySelector<HTMLInputElement>("[data-commercial-contact]")!;
    const selected = element.querySelector<HTMLInputElement>('[name="delivery-channel"]:checked')!;
    const channel = selected.value as CommercialDeliveryChannel;
    const contactValue = contact.value.trim();
    const isValid = isValidCommercialContact(channel, contactValue);
    contact.setCustomValidity(isValid ? "" : channel === "email"
      ? "Ingresá un email válido."
      : "Ingresá el número en formato internacional, por ejemplo +5493871234567.");
    if (!form.reportValidity()) return;

    const payload: CommercialContactPayload = {
      client_request_id: active.clientRequestId,
      locale: document.documentElement.lang === "en" ? "en" : "es-AR",
      title: active.prompt.title,
      summary: active.prompt.summary,
      contact_kind: channel === "email" ? "email" : "phone",
      contact_value: contactValue,
      preferred_delivery_channel: channel,
      quote_delivery_consent: true,
      commercial_follow_up_consent: element.querySelector<HTMLInputElement>("[data-commercial-follow-up]")!.checked,
      privacy_version: options.privacyVersion,
    };
    active.submitting = true;
    active.correlation = {
      ...active.correlation,
      attemptedClientRequestIds: [...active.correlation.attemptedClientRequestIds, active.clientRequestId],
    };
    const submittedRequest = active;
    const submittedElement = element;
    const submittedClientRequestId = active.clientRequestId;
    setControlsDisabled(submittedElement, true);
    const button = submittedElement.querySelector<HTMLButtonElement>(".chat-commercial-submit")!;
    const formStatus = submittedElement.querySelector<HTMLElement>(".chat-commercial-status")!;
    button.disabled = true;
    button.textContent = "Enviando…";
    formStatus.textContent = "Enviando tus datos de contacto de forma segura.";

    try {
      await postCommercialContact(payload);
      if (active !== submittedRequest || element !== submittedElement) return;
      markAccepted(submittedElement, submittedRequest, options.setChatStatus);
    } catch (error) {
      if (
        active !== submittedRequest ||
        element !== submittedElement ||
        submittedRequest.accepted
      ) return;
      submittedRequest.submitting = false;
      button.disabled = false;
      const requestWasCleared = submittedRequest.clientRequestId !== submittedClientRequestId;
      button.textContent = requestWasCleared ? "Compartir datos" : "Reintentar";
      if (requestWasCleared) {
        setControlsDisabled(submittedElement, false);
        formStatus.textContent = "Volvé a ingresar el dato cuando quieras continuar.";
        options.setChatStatus("Volvé a ingresar el dato.");
        return;
      }
      if (error instanceof CommercialContactApiError && error.status === 422) {
        submittedRequest.clientRequestId = createClientMessageId();
        setControlsDisabled(submittedElement, false);
        formStatus.textContent = "Revisá el dato ingresado antes de volver a enviarlo.";
      } else {
        formStatus.textContent = "No pudimos confirmar la recepción. Reintentá; no duplicaremos la solicitud.";
      }
      options.setChatStatus("No fue posible confirmar los datos de contacto.");
    }
  }

  return {
    clearSensitiveValue: () => {
      if (!element || !active || active.accepted) return;
      element.querySelector<HTMLInputElement>("[data-commercial-contact]")!.value = "";
      active.clientRequestId = createClientMessageId();
      const button = element.querySelector<HTMLButtonElement>(".chat-commercial-submit")!;
      if (active.submitting) {
        button.disabled = true;
        button.textContent = "Confirmando…";
        element.querySelector<HTMLElement>(".chat-commercial-status")!.textContent =
          "Estamos confirmando el envío anterior.";
      } else {
        setControlsDisabled(element, false);
        button.disabled = false;
        button.textContent = "Compartir datos";
        element.querySelector<HTMLElement>(".chat-commercial-status")!.textContent =
          "Volvé a ingresar el dato cuando quieras continuar.";
      }
    },
    handleEvent: (event) => {
      const prompt = parseCommercialContactPrompt(event);
      const correlation = applyCommercialEventCorrelation(active?.correlation, event);
      if (prompt && prompt.requestId !== active?.prompt.requestId && correlation) render(prompt, correlation);
      else if (active && correlation) active.correlation = correlation;
      if (element && active && active.correlation.accepted) {
        markAccepted(element, active, options.setChatStatus);
      }
    },
    reset: () => {
      element?.remove();
      element = undefined;
      active = undefined;
    },
  };
}

export function loadCommercialStyles(): Promise<void> {
  const existing = document.querySelector<HTMLLinkElement>('link[data-chat-commercial-styles]');
  if (existing) return Promise.resolve();
  return new Promise((resolve) => {
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = commercialStyleUrl;
    stylesheet.dataset.chatCommercialStyles = "true";
    stylesheet.addEventListener("load", () => resolve(), { once: true });
    stylesheet.addEventListener("error", () => resolve(), { once: true });
    document.head.append(stylesheet);
  });
}
