# Official sources that cannot be fetched automatically

Checked 14 October 2026 from a standard Linux client using the pipeline's user agent. These sources are
**not** replaced with secondary sources: a dossier fact needs an official source the pipeline can snapshot. Where an official
alternative exists, it is used instead (and noted here).

| Source | Problem | What we do instead |
|---|---|---|
| EUR-Lex (`eur-lex.europa.eu`) | Returns an empty HTTP 202 (bot challenge) to every automated request | The same documents come from the EU Publications Office (CELLAR): `publications.europa.eu/resource/celex/<CELEX>` and its SPARQL endpoint (source `eu-cellar`). EUR-Lex links are kept in `official_links` for readers. |
| ECHA (`echa.europa.eu`) | HTTP 403 | REACH Annex XVII amendments (e.g. microplastics) are picked up from CELLAR. |
| Légifrance (`legifrance.gouv.fr`) | HTTP 403. The official PISTE API needs a registered OAuth client | Ministry of Ecological Transition (`ecologie.gouv.fr`) documents and the Citeo tariff guide. **To do:** register a PISTE API key to follow the Journal officiel directly. |
| CalRecycle (`calrecycle.ca.gov`) | HTTP 403 | CalRecycle public notices on `www2.calrecycle.ca.gov` work and are watched. |
| California Legislative Information (`leginfo.legislature.ca.gov`) | HTTP 403 | — |
| Minnesota Pollution Control Agency (`pca.state.mn.us`) | Radware bot challenge | Minnesota Statutes on `revisor.mn.gov` (static). The MN dossier has no verified update yet. |
| Colorado CDPHE (`cdphe.colorado.gov`) and legislature (`leg.colorado.gov`) | 404 for the EPR pages tried; HTTP 403/406 for the legislature | None yet. The CO dossier has no verified update. |
| Maryland Department of the Environment (`mde.maryland.gov`) | HTTP 403 | Maryland General Assembly bill page and fiscal note (`mgaleg.maryland.gov`). |
| CONAI (`conai.org`) | HTTP 403 | — |
| Normattiva / Gazzetta Ufficiale: Italian budget laws (Law 160/2019 art. 1 paras 634–658; Law 199/2025 art. 1 para 125) | Article 1 of these laws has hundreds of paragraphs, loaded dynamically; the static pages contain only the article head | None yet. The Italy plastic tax dossier has no verified update. **To do:** use the Gazzetta Ufficiale PDF of the issue. |
| WTO ePing (`epingalert.org`) | JavaScript application with no public feed | Configured as an `email-alert` source: subscribe to e-mail alerts and forward relevant notifications. |
| Plastics Europe (`plasticseurope.org`) | HTTP 403 | Lead source only; not needed for facts. |
| Packaging Europe RSS (`packagingeurope.com/feed`) | HTTP 404 | Lead source only. |
| Washington Ecology Recycling Reform page | URL tried returned 404 | Session law text from `lawfilesext.leg.wa.gov`. |
| Verpact news pages (`verpact.nl/nl/actueel/...`) | Rendered client-side; static HTML has only the title | Verpact's rates and fee-modulation pages, which are static. |
| European Parliament documents (`www.europarl.europa.eu/doceo/...`) | Pages and PDFs fetched fine early in the day, then returned HTTP 202 (bot challenge) to every request. The RSS teaser text is still captured, but the HTTP 200 check fails, so such items are quarantined for a human | The Legislative Observatory (`oeil.secure.europarl.europa.eu`) answers normally and the relevant procedures are page-watched. |
