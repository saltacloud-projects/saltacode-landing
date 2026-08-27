export function initializeClientCarousel(): void {
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
