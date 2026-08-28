# Privacy compliance engineering baseline

This document records the public site's current technical posture as of 2026-08-28. It is an engineering control set, not a legal opinion or a claim that one implementation automatically satisfies every jurisdiction.

## Current public posture

- Controller disclosure: Oscar Vargas, CUIT 20-38213561-0, holder of the SaltaCode trade name.
- Necessary storage only: theme preference, privacy-preference acknowledgement, versioned chat consent, and the anonymous HttpOnly chat-session cookie after an accepted message.
- No analytics, advertising, cross-context behavioural tracking, or marketing storage is enabled.
- The first-visit notice describes the actual configuration; it does not mislabel necessary storage as optional consent.
- The persistent privacy center exposes inactive optional categories, Global Privacy Control status, local reset, the chat-specific consent boundary, and the rights contact.
- The browser cannot send a chat message before accepting the current chat privacy version, and the BFF rejects obsolete versions before rate limiting or session creation.
- Public policies disclose AI processing, human review for proposals and contracts, provider categories, international-transfer risk, retention, data-subject rights, minors, sensitive-data warnings, and the absence of sale or behavioural-advertising sharing.

## Regulatory references used for the baseline

- Argentina: [Personal Data Protection Law 25.326](https://www.argentina.gob.ar/normativa/nacional/ley-25326-64790/actualizacion), [AAIP data-subject rights](https://www.argentina.gob.ar/aaip/datospersonales/derechos), and [AAIP international transfers](https://www.argentina.gob.ar/transferencias-internacionales).
- European Union: [GDPR](https://eur-lex.europa.eu/eli/reg/2016/679/oj), [ePrivacy Directive](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX%3A02002L0058-20091219), and [EDPB consent guidance](https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-052020-consent-under-regulation-2016679_en).
- United Kingdom: [ICO guidance on cookies and similar technologies](https://ico.org.uk/media/for-organisations/guide-to-pecr/guidance-on-the-use-of-cookies-and-similar-technologies-1-0.pdf).
- Brazil: [ANPD cookies and personal-data guide](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia_orientativo_cookies_e_protecao_de_dados_pessoais).
- California: [Attorney General CCPA guidance and Global Privacy Control explanation](https://oag.ca.gov/privacy/ccpa).

The common engineering rule is fail-closed: any future analytics, marketing, or other non-essential storage must remain blocked until the applicable choice is available and recorded. Necessary storage remains documented and limited to its stated purpose.

## Operational gates before a production compliance claim

1. Determine which jurisdictions actually apply from customers, visitors, targeting, contracts, and establishment—not only from public reachability.
2. Maintain a current data-flow and subprocessor register with provider names, purposes, countries, retention, security terms, and signed processing agreements.
3. Select and document valid international-transfer mechanisms where required, including transfer-impact assessment and supplementary safeguards.
4. Operate a verified request workflow for access, correction, portability, objection, consent withdrawal, and deletion across the BFF, Agent Platform, email, WhatsApp, logs, backups, and every processor.
5. Document retention per data category and prove scheduled deletion plus backup expiry; a browser reset is not server-side deletion.
6. Maintain incident-response, breach-assessment, notification, access-review, secret-rotation, and audit-log procedures.
7. Re-run a storage/network audit before every analytics, advertising, chat-provider, CRM, or embedded-media change. Update policies and consent versions before activation.
8. Obtain jurisdiction-specific legal review before representing the site as universally compliant or before materially changing AI, sales, profiling, children, or sensitive-data processing.

## Release evidence

For each candidate, retain the built policies and version identifiers, browser storage inventory, GPC test, fresh-user notice test, consent rejection test, provider/subprocessor diff, deletion-path evidence, console/CSP result, and public response headers. Code review alone is insufficient.
