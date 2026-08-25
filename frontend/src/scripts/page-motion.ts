const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function initializeClientCarousel(): void {
  const carousel = document.querySelector<HTMLElement>("[data-client-carousel]");
  if (!carousel || carousel.dataset.animated !== undefined) return;

  const track = carousel.querySelector<HTMLElement>("[data-client-track]");
  const group = carousel.querySelector<HTMLElement>("[data-client-group]");
  if (!track || !group) return;

  const clone = group.cloneNode(true) as HTMLElement;
  clone.removeAttribute("data-client-group");
  clone.removeAttribute("aria-label");
  clone.setAttribute("aria-hidden", "true");
  clone.querySelectorAll<HTMLImageElement>("img").forEach((image) => {
    image.alt = "";
  });
  track.append(clone);
  carousel.dataset.animated = "";
}

async function initializeHeroMotion(): Promise<void> {
  const motionRoot = document.querySelector<HTMLElement>("[data-hero-motion]");
  if (!motionRoot || !motionRoot.isConnected || reducedMotion.matches) return;

  const { startHeroMotion } = await import("./hero-motion");
  if (!reducedMotion.matches) startHeroMotion(motionRoot);
}

if (!reducedMotion.matches) {
  initializeClientCarousel();

  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(initializeHeroMotion, { timeout: 1_200 });
  } else {
    globalThis.setTimeout(initializeHeroMotion, 0);
  }
}

reducedMotion.addEventListener("change", ({ matches }) => {
  if (!matches) initializeClientCarousel();
});
