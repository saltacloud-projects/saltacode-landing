const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const chatLauncher = document.querySelector<HTMLFormElement>("[data-chat-launcher]");
if (chatLauncher) chatLauncher.onsubmit = (event) => {
  event.preventDefault();
  void import("./chat-preview").then(({ openChatPreview }) => openChatPreview(chatLauncher));
};

function initializeClientCarousel(): void {
  void import("./client-carousel").then(({ initializeClientCarousel: startClientCarousel }) => {
    startClientCarousel();
  });
}

function initializeHeroMotion(): void {
  const motionRoot = document.querySelector<HTMLElement>("[data-hero-motion]");
  if (!motionRoot || reducedMotion.matches) return;

  void import("./hero-motion").then(({ startHeroMotion }) => {
    if (!reducedMotion.matches) startHeroMotion(motionRoot);
  });
}

if (!reducedMotion.matches) {
  initializeClientCarousel();

  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(initializeHeroMotion, { timeout: 1_200 });
  } else {
    setTimeout(initializeHeroMotion, 0);
  }
}

reducedMotion.addEventListener("change", ({ matches }) => {
  if (!matches) initializeClientCarousel();
});
