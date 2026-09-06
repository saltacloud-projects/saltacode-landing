export function startHeroMotion(motionRoot: HTMLElement): void {
  const controls: Animation[] = [];

  motionRoot.querySelectorAll<HTMLElement>("[data-circuit-node]").forEach((node) => {
    const circuitName = node.dataset.circuitNode;
    const circuitPath = motionRoot.querySelector<SVGPathElement>(
      `[data-circuit-path="${circuitName}"]`,
    );
    const pathData = circuitPath?.getAttribute("d");
    if (!pathData) return;

    node.style.offsetPath = `path("${pathData}")`;
    controls.push(node.animate(
      { offsetDistance: ["0%", "100%"], opacity: [0.62, 1, 0.68] },
      {
        duration: Number(node.dataset.duration ?? 18) * 1_000,
        delay: Number(node.dataset.delay ?? 0) * 1_000,
        easing: "linear",
        iterations: Infinity,
      },
    ));
  });

  motionRoot.querySelectorAll<SVGPathElement>(".hero-circuit-path").forEach((path, index) => {
    controls.push(path.animate(
      { opacity: [0.56, 0.86, 0.6] },
      { duration: (8 + index * 2) * 1_000, easing: "ease-in-out", iterations: Infinity },
    ));
  });

  motionRoot.dataset.motionActive = "true";
  const syncPlayback = () => {
    controls.forEach((control) => {
      if (document.hidden || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        control.pause();
      } else {
        control.play();
      }
    });
  };

  document.addEventListener("visibilitychange", syncPlayback);
  window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", syncPlayback);
}
