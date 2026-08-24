import { animate } from "motion/mini";

interface PlaybackControl {
  pause: () => void;
  play: () => void;
}

export function startHeroMotion(motionRoot: HTMLElement): void {
  const controls: PlaybackControl[] = [];

  motionRoot.querySelectorAll<HTMLElement>("[data-orbit-node]").forEach((node) => {
    const orbitName = node.dataset.orbitNode;
    const orbitPath = motionRoot.querySelector<SVGPathElement>(
      `[data-orbit-path="${orbitName}"]`,
    );
    const pathData = orbitPath?.getAttribute("d");
    if (!pathData) return;

    node.style.offsetPath = `path("${pathData}")`;
    controls.push(
      animate(
        node,
        { offsetDistance: ["0%", "100%"], opacity: [0.45, 1, 0.55] },
        {
          duration: Number(node.dataset.duration ?? 18),
          delay: Number(node.dataset.delay ?? 0),
          ease: "linear",
          repeat: Infinity,
        },
      ),
    );
  });

  motionRoot.querySelectorAll<SVGPathElement>(".hero-orbit-path").forEach((path, index) => {
    controls.push(
      animate(
        path,
        { opacity: [0.24, 0.58, 0.24] },
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
