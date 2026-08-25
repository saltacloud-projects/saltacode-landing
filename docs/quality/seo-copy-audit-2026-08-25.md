# SEO textual: claridad primero, keywords después

La página ya explica con precisión qué hace SaltaCode, para quién y cómo iniciar una conversación. El cambio principal fue reemplazar slogans y categorías internas por problemas, servicios y próximos pasos que un posible cliente puede reconocer. Esto mejora la comprensión y la coherencia semántica; no garantiza posiciones en Google.

## Alcance y límite de evidencia

Este análisis cubre el HTML local, el contenido visible, los metadatos y la jerarquía de encabezados de la única landing. No incluye datos actuales de Search Console, volumen de búsquedas, competidores, conversiones ni resultados de campo. Por eso, “desarrollo de software a medida en Salta”, “consultoría IT”, “equipos IT” y “productos SaaS” son hipótesis de intención basadas en la oferta existente, no keywords validadas por demanda.

Google recomienda que el título y el encabezado principal describan la página, que el contenido ayude primero a las personas y que la descripción resuma con precisión lo que encontrarán. También aclara que el snippet puede salir del contenido visible y que no existe una fórmula que garantice el primer puesto:

- [Contenido útil y centrado en las personas](https://developers.google.com/search/docs/fundamentals/creating-helpful-content)
- [Buenas prácticas para title links](https://developers.google.com/search/docs/appearance/title-link)
- [Buenas prácticas para meta descriptions](https://developers.google.com/search/docs/appearance/snippet)
- [Guía de introducción a SEO](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)

## Diagnóstico

| Momento del interesado | Antes | Resultado actual | Estado |
|---|---|---|---|
| Entender la oferta en cinco segundos | “Tecnología que impulsa tu crecimiento” no identificaba el servicio principal. | El `h1` dice “Software a medida para tu empresa” y el texto explica sistemas, integraciones y equipos IT. | Corregido |
| Reconocer su necesidad | La introducción enumeraba categorías y prometía crecimiento de forma genérica. | La sección explica cuatro puntos de partida: construir, sumar capacidad, decidir o evolucionar SaaS. | Corregido |
| Entender cada servicio | “Software Factory” y “Outsourcing” priorizaban jerga del proveedor; varias características no correspondían claramente con el servicio. | Los títulos y beneficios usan lenguaje del cliente: software a medida, equipos IT, consultoría y productos SaaS. | Corregido |
| Confiar en las afirmaciones | Había absolutos no demostrados: “al instante”, “sin límites”, “sin demoras”, “garantizando” y reducción de costos. | Se reemplazaron por alcance, proceso y decisiones verificables sin prometer resultados no probados. | Corregido |
| Saber cómo avanzar | El hero simulaba una respuesta inmediata aunque la integración del agente todavía no está activa. | La consulta pide el problema y conduce al contacto sin prometer una capacidad inexistente. | Corregido |
| Confirmar presencia y contacto | La dirección existía, pero el footer no reforzaba identidad ni rutas de contacto. | Título, descripción, sección Nosotros, footer y datos estructurados mantienen Salta, email, WhatsApp y oficina. | Correcto |
| Encontrar profundidad por servicio | Toda la oferta vive en una sola URL. | La landing diferencia los servicios, pero todavía no puede responder búsquedas o dudas profundas por separado. | Pendiente |
| Evaluar experiencia demostrable | Los logos aportan confianza visual, pero no explican problema, trabajo ni resultado. | No se inventaron casos de éxito ni métricas. Falta evidencia publicable aprobada por cada cliente. | Pendiente |

## Copy implementado

| Elemento | Texto |
|---|---|
| `<title>` | `Desarrollo de software a medida en Salta | SaltaCode` |
| Meta description | `Creamos software a medida, integramos sistemas y sumamos equipos IT para empresas. Consultoría y soluciones SaaS desde Salta, Argentina.` |
| `h1` | `Software a medida para tu empresa` |
| CTA conversacional | `¿Qué necesitás resolver en tu empresa?` |
| Servicios | `Servicios IT según lo que tu empresa necesita` |
| Nosotros | `Un equipo de Salta para acompañar tu proyecto de punta a punta` |
| Contacto | `Contanos qué necesitás resolver` |

El título tiene 52 caracteres y la descripción 136, pero esos números son evidencia descriptiva, no un objetivo de ranking: Google puede truncar o reconstruir ambos según el dispositivo y la consulta.

## Próximos contenidos, en orden

1. **Validar intención real:** exportar consultas, páginas y países desde Search Console; cruzarlas con contactos recibidos y clics de email/WhatsApp.
2. **Publicar casos verificables:** problema, alcance, intervención y resultado autorizado para dos o tres clientes. No deducir resultados desde sus logos.
3. **Crear páginas de servicio sólo con contenido suficiente:** una URL por servicio cuando pueda responder para quién es, qué incluye, proceso, entregables, límites y preguntas comerciales reales.
4. **Explicar cómo trabajan:** diagnóstico, propuesta, inicio, seguimiento y evolución. Esa información reduce incertidumbre antes del contacto.
5. **Reforzar quién está detrás:** incorporar empresa, equipo o liderazgo únicamente con datos públicos aprobados y evidencia, sin fabricar credenciales.

## Criterio de medición

- Comparar impresiones, clics, CTR y consultas por página en Search Console antes y después de la recrawl.
- Medir clics hacia email, WhatsApp y el futuro chat, separando dispositivo y fuente.
- Revisar en móvil si el interesado llega a servicios y contacto sin volver atrás para entender la propuesta.
- Mantener como desconocidos ranking, conversión y Core Web Vitals de campo hasta contar con evidencia del origen público.
