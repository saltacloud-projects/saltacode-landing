import { animate } from "motion/mini";

interface PlaybackControl {
  pause: () => void;
  play: () => void;
}

export function startHeroMotion(motionRoot: HTMLElement): void {
  const controls: PlaybackControl[] = [];

  motionRoot.querySelectorAll<HTMLElement>("[data-circuit-node]").forEach((node) => {
    const circuitName = node.dataset.circuitNode;
    const circuitPath = motionRoot.querySelector<SVGPathElement>(
      `[data-circuit-path="${circuitName}"]`,
    );
    const pathData = circuitPath?.getAttribute("d");
    if (!pathData) return;

    node.style.offsetPath = `path("${pathData}")`;
    controls.push(
      animate(
        node,
        { offsetDistance: ["0%", "100%"], opacity: [0.62, 1, 0.68] },
        {
          duration: Number(node.dataset.duration ?? 18),
          delay: Number(node.dataset.delay ?? 0),
          ease: "linear",
          repeat: Infinity,
        },
      ),
    );
  });

  motionRoot.querySelectorAll<SVGPathElement>(".hero-circuit-path").forEach((path, index) => {
    controls.push(
      animate(
        path,
        { opacity: [0.38, 0.72, 0.4] },
        { duration: 8 + index * 2, ease: "easeInOut", repeat: Infinity },
      ),
    );
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
