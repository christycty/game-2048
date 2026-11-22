async function initMermaid() {
  const { default: mermaid } = await import(
    "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"
  );
  mermaid.initialize({
    startOnLoad: false,
    theme: "neutral",
    securityLevel: "strict",
    themeVariables: {
      fontFamily: "Figtree, system-ui, sans-serif",
      primaryColor: "#ffffff",
      primaryTextColor: "#1c1917",
      primaryBorderColor: "#a8a29e",
      lineColor: "#57534e",
      secondaryColor: "#f5f5f4",
      tertiaryColor: "#fef3c7",
    },
  });
  await mermaid.run({ nodes: document.querySelectorAll("pre.mermaid") });
}

function initActiveNav() {
  const links = [...document.querySelectorAll(".sidebar nav a")];
  const sections = links
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  if (!links.length || !("IntersectionObserver" in window)) return;

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
      if (!visible.length) return;
      const id = `#${visible[0].target.id}`;
      links.forEach((link) => {
        link.classList.toggle("is-active", link.getAttribute("href") === id);
      });
    },
    { rootMargin: "-20% 0px -55% 0px", threshold: [0.1, 0.25, 0.5] },
  );

  sections.forEach((section) => observer.observe(section));
}

initActiveNav();
initMermaid().catch(() => {});
