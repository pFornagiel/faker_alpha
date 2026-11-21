# 04 — Prior art, feature design, LLM feature augmentation, similarity fusion & clustering

Research date: 2026-11-21. Scope: NASK HackNation 2026 "Kolekcjoner Fejków / Follow the Fake".

**How to read the source markers**

- **[V]** — verified in this session against the primary document (PDF/text downloaded and read, or page fetched).
- **[S]** — seen only in search-result summaries or secondary coverage; plausible, not read in full.
- **[M]** — from background knowledge of the literature, *not* re-checked in this session (arXiv IDs, venue details and repo paths marked [M] should be confirmed before they go on a slide).

GitHub repos listed as "exists" returned HTTP 200/301 on 2026-11-21; stars, licences and last-commit dates were **not** checked (API rate-limited), so treat licence statements as [M] unless stated.

---

## 0. TL;DR

1. **Nobody has published an open, reusable "scam-ad campaign clustering" system or a campaign-labelled scam-ad dataset.** Vendors (Bitdefender, Gen/Norton, ESET, Infoblox) and CSIRTs (CSIRT KNF, CERT Polska) do exactly this linking, but publish only narrative reports and a few IOCs. What *is* open are building blocks: perceptual hashing (Meta PDQ/vPDQ/TMK), copy-detection embeddings (SSCD), coordinated-text detection (VIGINUM D3lta), coordination networks (CooRnet/CooRTweet, IUNetSci), brand/logo matching (Phishpedia/KnowPhish), record-linkage with explainable weights (Splink), LLM-clustering code (few-shot-clustering, ClusterLLM, GoalEx, TopicGPT, LLooM).
2. **The published investigations all link campaigns the same way**: hard infrastructure identifiers first (pixel/tracker IDs, domains, redirect chains, URL parameters, DGA patterns, HTML/CSS similarity), then template/narrative reuse, then impersonated persons. Celebrity identity alone is never treated as sufficient.
3. **Polish ground truth exists for a reference DB**: NASK's list of 121 deepfaked persons (July 2024, with social group), CSIRT KNF's category shares, CERT Polska's 2025 table of most-spoofed brands by domain count, and the CSIRT KNF 2026 campaign note with a domain-generation pattern and 36 rotating fake-platform names.
4. **Recommended method**: evidence-graph + Fellegi–Sunter-style additive log-weights per signal (rarity-adjusted), union-find on near-certain links for "campaign cores", Leiden on the weighted ad–ad graph for campaigns, HDBSCAN only as a *feature generator* (narrative / template clusters), every edge carrying an itemised evidence list. New ads are assigned by indexed candidate lookup + the same scoring function.
5. **LLM augmentation** is well supported by literature (CAAFE, FeatLLM, LLM-FE for tabular; Viswanathan et al., ClusterLLM, GoalEx, TnT-LLM, LLooM, Text Bottleneck Models for text). The practical recipe is *closed-vocabulary structured extraction* + set-Jaccard / one-hot / embedded-value features + a propose-test-keep loop for new attributes.

---

## 1. Prior art

### 1.1 Academic work

| Work | What it does that we can reuse | Open code/data |
|---|---|---|
| Edelson, Lauinger, McCoy — *A Security Analysis of the Facebook Ad Library*, IEEE S&P 2020 [S] | First clustering of Ad Library advertisers for **undeclared coordinated activity**; found 16 clusters of likely inauthentic communities. Political ads, 2018–19. | Paper: https://damonmccoy.com/papers/ad_library2020sp.pdf — NYU said the algorithm would be shared with researchers; no public repo found. |
| Bouchaud — *On Meta's Political Ad Policy Enforcement*, 2024 (HAL hal-04541571), basis of AI Forensics "No Embargo in Sight" [S] | Coordinated campaign = "multiple advertisers running the same or highly similar ad content across multiple pages"; text classifier + near-duplicate text across pages; found a 3,826-page pro-Russian network; tolerant to tiny text variations. | Report: https://aiforensics.org/uploads/No_Embargo_in_Sight_AI_Forensics_Report.pdf — no code release found. |
| Kotzias et al. — *Ctrl+Alt+Deceive: Quantifying User Exposure to Online Scams*, NDSS 2025 [V] | 607K scam domains, 7 scam types (shopping, financial, crypto, gambling, dating, funds recovery, employment); ≥13.3% of scam observations followed an ad, 59% of those ads on social media (Facebook first); median scam-domain lifetime 11 days. Useful scam-type taxonomy and the "short-lived domain" prior. | https://ndss-symposium.org/wp-content/uploads/2025-1816-paper.pdf — no dataset. |
| Roongta et al. (NYU/Radboud) — *AdLens*, CCS 2026 [S] | Closest pipeline analogue: **cheap similarity search to flag candidates, then a panel of open-weight LLMs to confirm**; 188k Google Ads Transparency creatives; ran on a 4-core VM + one L40S GPU, LLM annotation <12 h. | Code: https://github.com/Racro/ccs-2026-AdLens (per Help Net Security; repo not opened). Paper: https://racro.github.io/papers/adlens.pdf |
| Vadrevu & Perdisci — *What You See is NOT What You Get: Discovering and Tracking Social Engineering Attack Campaigns*, IMC 2019 [S, method M] | Discovers SE-ad campaigns by clustering landing-page screenshots and requiring a cluster to span multiple domains — the "same visual, many domains" campaign definition. | No public repo found. |
| Zannettou et al. — *On the Origins of Memes by Means of Fringe Web Communities*, IMC 2018 [S] | **pHash + DBSCAN** pipeline over 160M images to group image variants; canonical recipe for visual-template clustering. | arXiv 1805.12512; repo `memespaper/memes_pipeline` (exists, redirected). |
| Starov et al. — *Betrayed by Your Dashboard: Discovering Malicious Campaigns via Web Analytics*, WWW 2018 [S] | **Analytics/tracker IDs as campaign keys**: 9,395 analytics IDs tied to malicious pages; clustering malicious sites into campaigns and attributing WHOIS-protected domains. Direct justification for pixel/GA/GTM-ID edges. | https://securitee.org/files/malanalytics_www2018.pdf |
| Drew & Moore — *Automatic identification of replicated criminal websites using combined clustering*, EURASIP J. Info. Sec. 2014 [S] | Per-feature clustering (text, HTML structure, etc.) then **combined/consensus clustering** to link replicated scam sites despite evasion — the academic precedent for late fusion (option e below). | https://link.springer.com/article/10.1186/s13635-014-0014-4 |
| Der et al. — *Knock It Off: Profiling the Online Storefronts of Counterfeit Merchandise*, KDD 2014 [S] | Bag-of-words over raw HTML attributes storefronts to affiliate programs because templates leave signatures. Supports "HTML template = operator" for fake shops. | https://cseweb.ucsd.edu/~mfder/papers/knockoff_kdd14.pdf |
| Pacheco et al. — *Uncovering Coordinated Networks on Social Media*, ICWSM 2021 [S] | General unsupervised recipe: build a bipartite account–trace graph (images, hashtags, links, timing), project to an account–account similarity graph, threshold, take components. Our ad–entity–ad graph is the same construction. | arXiv 2001.05658; repo `IUNetSci/coordination-detection` (exists, redirected). |
| Cinus et al. — *Exposing Cross-Platform Coordinated Inauthentic Activity…*, 2024/25 [S] | Similarity networks across X/Facebook/Telegram; cross-platform linking. | arXiv 2410.22716 |
| Giglietto et al. — CooRnet; Righetti & Balluff — CooRTweet [S] | Coordinated link/image sharing within a time window → entity network. R packages. | `fabiogiglietto/CooRnet`, `nicolarighetti/CooRTweet` (both exist). |
| Phishpedia (USENIX Sec 2021), PhishIntention (2022), KnowPhish (2024) [S] | Reference-based brand identification from logos/screenshots; KnowPhish auto-builds a multimodal brand knowledge base. Reusable for "impersonated brand/media outlet" on landing pages and creatives. | `lindsey98/Phishpedia`, `lindsey98/PhishIntention`, `imethanlee/KnowPhish` (exist). |
| Li et al. — *Double and Nothing: Crypto Giveaway Scams*, NDSS 2023; Acharya et al. — *Conning the Crypto Conman*, IEEE S&P 2024; Bitaab et al. — *Beyond Phish* (fraudulent e-commerce), IEEE S&P 2023; Kharraz et al. — *Surveylance* (survey scams), IEEE S&P 2018 [M] | Scam-type-specific campaign measurement; all cluster by shared infrastructure (wallets, domains, templates). | Not checked. |
| Zeng, Kohno, Roesner — *What Makes a "Bad" Ad?*, CHI 2021 [M] | Taxonomy + labelled dataset of problematic ads (US, display ads). Labels are ad *types*, not campaigns. | `eric-zeng/chi-bad-ads-data` (exists). |

**Finding:** I found no peer-reviewed paper (2022–2026) that clusters *social-media scam ads* into campaigns with a multimodal method and releases code + labels. AdLens is the nearest open pipeline (Google ads, detection rather than campaign linking). This is a genuine gap the hackathon solution can claim to fill — phrase it as "no open implementation found", not "none exists".

### 1.2 Industry / NGO / CSIRT investigations (methodology, no code)

| Source | Linking signals they actually used | Scale / notes |
|---|---|---|
| **Bitdefender Labs**, "Global investment scam network using Meta ads", Mar 2026 [V] https://www.bitdefender.com/en-us/blog/labs/global-investment-scam-network-using-meta-ads | Shared **pixel + token identifiers**, UTM/pixel signatures, dynamic URL parameters referencing the same ad account, redirect/landing infrastructure, coordinated launch timing, identical script with localised names, Russian strings in campaign/ad-set names ("крео", "лиды"). | 310 campaigns, 26k+ ad sightings, 25 countries; **Poland is the #1 target (18–20%, ~40 campaigns)**. Archetypes: Celebrity Will/Testament ~40%, Banking Scandal ~35%, Political Exposure ~25%. Sub-campaigns "Banker Mic-Drop", "Celebrity Will", "Romanian Live Studio". Only 11 domains published. |
| **Gen Digital / Norton**, "The Scam Ad Machine" parts I–II, 2026 [V] https://www.gendigital.com/blog/insights/research/scam-ad-machine-meta | Scam label from *destination infrastructure*; reused domains, near-identical text, URL patterns; payer/beneficiary rotates while mechanics persist. Part II lists evasion: multi-facet ads bundling legit links, URL masking, typosquats, subdomain prefixes, Unicode look-alikes and invisible joiners inside celebrity names, disposable low-budget ads, advertiser regeneration. | 14.57M ads in 23 days; 30.99% scam-linked; **top 10 advertisers = 56.1% of scam ads**. No code/data. |
| **KommAustria/RTR study**, Dec 2025 [V] https://www.rtr.at/medien/aktuelles/publikationen/Publikationen/Publikationen_2026/Betrugsoekosystem_Werbung_KommAustria_final_EN.pdf | Keyword crawl of Ad Library API → manual screening → pivot tables per scheme; **HTML source similarity clusters of landing pages** (Funnelish funnels, identical hosted images, Chinese code comments in fake shops). | 634k fraud ads / 3 months / 8 schemes; 1,368 advertisers vs 7,558 payers; payer field is unverified free text (payer "1" → 11,712 ads); most ads live hours–days; documents cloaking, compromised accounts, multi-version and "chameleon" ads. |
| **CSIRT KNF**, "Masowa kampania wyłudzeń finansowych o zasięgu międzynarodowym", 2026, TLP:CLEAR [V] https://www.knf.gov.pl/knf/pl/komponenty/img/Raport_CSIRT_KNF_Masowa_Kampania_Wyludzen_99343.pdf | **Domain-generation pattern** `finance<20-99>-<lorem-ipsum word><20-99>.sbs` (554 listed; earlier wave on `.pro`); intermediate redirect domains (`balticpipetrade[.]com`, `orlenplatform[.]com`); **rotating "motywy przewodnie"** = invented platform names; content shown only with the right URL params; Cyrillic JS comments; explicitly recommends comparing **CSS, unique DOM elements and embedded-image metadata** to map infrastructure. | 500+ active domains, 36 example themes, 20 redirectors. The single most useful Polish document for feature design. |
| **Infoblox**, "Uncovering Actor TTP Patterns and the Role of DNS in Investment Scams", Apr 2025 [V] https://www.infoblox.com/blog/threat-intelligence/uncovering-actor-ttp-patterns-and-the-role-of-dns-in-investment-scams/ | Actors tracked by **RDGA patterns** (Reckless Rabbit: `<1-2 chars><month abbr><word>.info`; Ruthless Rabbit: `<word><suffix bik/job/mot/kot…>.pro`), fixed form-POST endpoint and UUID, hard-coded `so=` parameter, URL-path conventions (`/lander/<theme>_<n>/`), self-run cloaking API, wildcard DNS, decoy domain in ad caption (`amazon[.]pl`). | Ruthless Rabbit themes include Baltic Pipe; Polish celebrity fake-news lure documented. |
| **CheckFirst**, "Facebook Hustles", 2023 (+ Qurium infrastructure analysis) [S] https://checkfirst.network/wp-content/uploads/2023/06/Facebook-Hustles-The-Hidden-Mechanics-of-a-Scam-Machinery-Impersonating-News-Organisations-and-Creators.pdf | Hijacked pages → ads → cloned media sites; grouping by domains hosting fake media pages. | 1,500+ ads; 160+ domains (per EDMO BELUX summary). |
| **Qurium / EU DisinfoLab — Doppelganger** [S] https://www.qurium.org/alerts/exposing-the-evil-empire-of-doppelganger-disinformation/ | Multi-stage redirect chain fingerprinting, Keitaro tracker, shared hosting (Aeza), cloaking service shared with ordinary scams (Kehr/VexTrio). | Shows disinfo and scam ads share infrastructure → same features work for both. |
| **VIGINUM — Portal Kombat**, Feb 2024 [S] | 193 sites linked by near-identical graphic charter, template and source-code literals. | Technical report (FR/RU PDFs). |
| **Debunk.org** (with Oxylabs), 2025–26 [V secondary] https://www.debunk.org/over-50k-ads-on-social-media-impersonated-interpol-europol-and-eu-institutions-promising-fraud-r | Fund-recovery scam: recurring layouts, content templates, multilingual variants, infrastructure reuse across "brands". | 50,426 ads, 459 domains, 1,139 pages; ~3.9k Polish-language ads. |
| **ESET — "Nomani"** [S] | Family defined by fake-news-style landing template + deepfake testimonial + lead form. | Detections +62% in 2025; templates traced to GitHub repos by RU/UA users. |
| **Maldita.es** transport-card network (via Demagog) [V secondary] | 1,000+ pages impersonating transit operators; >50% of admins in Vietnam; most domains on 2 Russian IPs — page-admin country and IP as linking features. | Same scheme hits Polish cities (CERT Polska 16.06.2025 warning). |
| **TTP**, **CCDH**, **Which?/Demos**, **Reset Tech**, **ISD** [S] | Mostly advertiser-level counts via Ad Library; ISD notes all domains redirect to an identical scam page. | Context only. |

### 1.3 Open-source building blocks worth reusing

| Tool | Use in our pipeline | Notes |
|---|---|---|
| **Meta ThreatExchange** — PDQ (256-bit image hash), vPDQ (frame-wise video), TMK+PDQF (video), Hasher-Matcher-Actioner [S] `facebook/ThreatExchange` | Exact/near-duplicate creative dedup; "47 identical reports → 1 creative". | BSD. vPDQ = "two videos match if enough frames match" — ideal when scammers pad with black frames. ThreatExchange *data* access needs approval; the hashing code does not. |
| **SSCD** (Pizzi et al., CVPR 2022) `facebookresearch/sscd-copy-detection` [M] | Copy-detection embedding: robust to crops, overlays, re-encodes — better than CLIP for "same template/asset", worse for semantics. | Check licence before reuse. |
| **OpenCLIP / SigLIP** `mlfoundations/open_clip` | Semantic visual similarity ("TV studio + lower-third + portrait"), zero-shot template classification. | Complements SSCD; do not use alone for linking. |
| **VIGINUM D3lta** `VIGINUM-FR/D3lta`, PyPI `d3lta` [S] | Detects copypasta / rewording / translation between texts using embeddings + FAISS + graph; CPU-only; ships a synthetic labelled pair set. | MIT (per repo metadata). Swap the default USE embedding for a Polish-capable model. |
| **datasketch** `ekzhu/datasketch` | MinHash + LSH over word 5-shingles for near-duplicate text candidates. | Standard. |
| **Splink** `moj-analytical-services/splink` [S] | Fellegi–Sunter record linkage on DuckDB: unsupervised EM for m/u probabilities, **term-frequency adjustment**, **waterfall chart per pair** = ready-made edge explanation. | Either use it directly on a tabular ad-feature frame or copy the maths (≈30 lines). |
| **Snorkel** `snorkel-team/snorkel` | Labeling functions → probabilistic pair labels for training a pairwise model. | Optional. |
| **hdbscan** `scikit-learn-contrib/hdbscan` | `prediction_data=True` + `approximate_predict` for assigning new points; `metric='precomputed'` for fused distances. | sklearn's own HDBSCAN lacks approximate_predict [M]. |
| **leidenalg / igraph** `vtraag/leidenalg` | Leiden community detection with resolution (CPM) on weighted graphs. | Fast on CPU for 10^5 edges. |
| **Phishpedia / KnowPhish** | Logo/brand recognition on landing screenshots and creatives. | Ship with small brand DBs; add Polish brands. |
| **InsightFace** `deepinsight/insightface`; **DeepFace** `serengil/deepface` | Face detection + ArcFace embeddings against the reference DB. | InsightFace code is MIT but the pretrained model packs are non-commercial research only [M] — fine for a hackathon, flag it for NASK production. |
| **GLiNER** `urchade/GLiNER`; **NuExtract** `numindai/nuextract` | Small zero-shot NER / structured extraction on CPU, multilingual. | Cheap first pass before any LLM. |
| **faster-whisper**, **PaddleOCR/EasyOCR**, **speechbrain** (ECAPA speaker embeddings), **TLSH** `trendmicro/tlsh`, **JARM** `salesforce/jarm` | ASR, OCR, voice embedding, HTML fuzzy hash, TLS fingerprint. | All CPU-capable; ASR is the slow part. |
| LLM-clustering code: `viswavi/few-shot-clustering`, `zhang-yu-wei/ClusterLLM`, `ZihanWangKi/GoalEx`, `chtmp223/topicGPT`, `michelle123lam/lloom`, `MaartenGr/BERTopic`, `automl/CAAFE`, `Sungwon-Han/FeatLLM`, `nikhilsab/LLMFE` | See §3. | All exist; CAAFE is CC BY-NC-SA [S]. |
| **Hoaxy** `osome-iu/hoaxy-backend`, **Open Measures**, **QUT coordination-network-toolkit** | Diffusion/coordination tooling for organic posts. | Low relevance to paid ads; cite as related. |

### 1.4 Data sources and labelled data

- **Meta Ad Library API** — for EU delivery returns all commercial ads with `ad_creative_bodies`, `ad_snapshot_url`, `page_id`, `page_name`, delivery start/stop, `publisher_platforms`, plus DSA fields `eu_total_reach`, `beneficiary_payers`, `target_ages`, `target_gender`, `target_locations`, `age_country_gender_reach_breakdown`; spend/impressions only for political ads; retention one year [S, third-party docs — confirm on developers.facebook.com]. Known gaps: delayed indexing, missing ad versions, vanished ads, unverified payer (CERT Polska, CSIRT KNF, KommAustria [V]).
- **CERT Polska warning list** — `https://hole.cert.pl/domains/v2/domains.txt` [V via CSIRT KNF note]: 244,341 domains added in 2025. Free label source: "landing domain is on the list" and a way to pull sibling domains.
- **CSIRT KNF annex** — 554 `finance…sbs` domains + 20 redirectors + 36 theme names [V]: a ready-made *known campaign* for recall testing.
- **CSIRT KNF deepfake gallery** — https://cebrf.knf.gov.pl/deepfake [V link in report]: example videos for the face/voice reference set.
- **D3lta synthetic pairs** (copypasta/rewording/translation) for calibrating text thresholds [S].
- **No public campaign-labelled scam-ad dataset found.** Plan to create labels yourselves (§4.6).

### 1.5 Polish context (for the reference DB and taxonomy)

**Volumes**

- CERT Polska 2025 annual report [V]: 244,341 domains added to the warning list, resolving to 53,544 IPs, of which 43,843 behind Cloudflare AS13335. **Fake investments: 98,663 domains** (42,172 in 2024). Top TLDs: .com 77,483, .pro 28,918, .icu 18,946, .cfd 14,741, .net 10,884, .sbs 10,875, .top 8,602, .shop 8,386, .info 6,257, .online 5,039; only 2,887 .pl. Source: https://cert.pl/uploads/docs/Raport_CP_2025.pdf
- CSIRT KNF 2025 annual report [V]: 41,751 domains reported, 40,225 (96.34%) fake investments; 9,751 fraudulent Facebook ads blocked; 4,358 advertiser profiles reported (+41.95% y/y); 404 fake-shop domains. 2024 report [V]: 10,951 ads, 45,985 fake-investment domains. Sources: https://cebrf.knf.gov.pl/images/Raporty/Raport_Roczny_CSIRT_KNF_97516.pdf , https://www.knf.gov.pl/knf/pl/komponenty/img/Raport_Roczny_CSIRT_KNF_2024_93226.pdf
- NASK OAD [V secondary, xyz.pl 27.01.2026]: 9,094 reports to Meta in 2025; 40% removed, 8% moderated, 52% rejected/unanswered. NASK OAD report "Reakcja platform społecznościowych na zgłoszenia w 2025 roku" [V]: Meta removes individual ads, rarely the advertiser.
- NASK figures quoted in media [S]: 13.2k AI-manipulated ads / 380 persons (May 2026); 16k ads / ~450 persons / ~537M PLN losses (Sept 2026).

**Who is impersonated — category shares** (CSIRT KNF 2024, fake-investment ads) [V]: politicians 26%, other 19%, celebrities 14%, "fund recovery" 11%, state-owned companies 11%, Baltic Pipe 7%, entrepreneurs 6%, influencers 4%, banks 1%, Tesla 1%.

**Suggested face reference DB (~15 core + extension).** There is no official ranking; this ordering is my synthesis of how often and how recently each name recurs across the sources below — treat it as a prioritised shortlist, not a measured ranking.

| # | Person | Role | Evidence |
|---|---|---|---|
| 1 | Rafał Brzoska | InPost CEO | NASK list 2024; "most attempts in June 2024" (NASK via Super Biznes); Demagog 08.2026; UODO/court actions vs Meta |
| 2 | Andrzej Duda | ex-President | **9% of all deepfakes detected in 2024** (NASK); NASK list |
| 3 | Karol Nawrocki | President | NASK OAD 2025 (YouTube deepfake ads, "narodowy program wsparcia dochodu"); Demagog 2026; xyz.pl 02.2026 |
| 4 | Donald Tusk | PM | NASK list; NASK OAD Q1 2025; Bitdefender 2026 |
| 5 | Adam Glapiński | NBP governor | NASK OAD Q1 2025; Bitdefender "banker" archetype; Demagog |
| 6 | Robert Lewandowski | footballer | NASK warning 05.2024; NASK list; Demagog (casino ads) |
| 7 | Rafał Trzaskowski | Warsaw mayor | NASK list; Bitdefender; NASK OAD (election deepfakes) |
| 8 | Sławomir Mentzen | politician | NASK list; Demagog (staged quarrel with Braun) |
| 9 | Sebastian Kulczyk | businessman | NASK list; xyz.pl (faked interview clip) |
| 10 | Kamil "Budda" Labudda | influencer | NASK warning 05.2024; NASK list; Demagog (casino) |
| 11 | Wojciech Cejrowski | TV traveller | "most often used for financial scams" (NASK, 07.2024) |
| 12 | Krzysztof Simon / Krzysztof Bielecki | doctors | NASK OAD 2025: "najczęściej" in health deepfake ads |
| 13 | Bogdan Rymanowski | journalist | NASK OAD 2025 (anchor in Nawrocki ad); NASK list |
| 14 | Izabela Leszczyna | ex-health minister | NASK warning 05.2024; NASK list |
| 15 | kard. Grzegorz Ryś | clergy | xyz.pl, Demagog 2026 (supplements/investments) |

Extension set: Grzegorz Braun, Daniel Obajtek, Omena Mensah, Krzysztof Ibisz, Tomasz Biernacki, Kuba Wojewódzki, Hubert Urbański, Agnieszka Chylińska, Julia Wieniawa, Anna Mucha, Małgorzata Rozenek-Majdan, Michał Sutkowski, Paweł Grzesiowski, Jerzy Zięba, Ewa Dąbrowska, Roman Giertych, Krzysztof Bosak (Demagog, Bitdefender, xyz.pl); news anchors used as the "studio frame": Danuta Holecka, Piotr Kraśko, Anita Werner, Dorota Gawryluk, Monika Olejnik (NASK list); recently deceased celebrities for the testament template: Stanisław Sojka, Magda Umer, Edward Linde-Lubaszenko (Demagog, Bitdefender); global: Elon Musk, Mark Zuckerberg (NASK list).

Full NASK list (121 names with group: Politycy, Dziennikarze, Przedsiębiorcy, Duchowni, Lekarze, Sportowcy, Aktorzy, Piosenkarze, Influencerzy, Inni; as of 12.07.2024) [V]: the live URL now returns 404; archived copy: http://web.archive.org/web/20240812002303/https://www.nask.pl/download/30/4987/listaosobwykorzystanychdodeepfake01-072024.pdf . The full list, grouped, is reproduced in Appendix A.

**Brands / institutions (brand reference DB)**

| Group | Names | Evidence |
|---|---|---|
| Investment lures | Orlen (16,977 domains in 2025 vs 972 in 2024), Baltic Pipe, Baltica 2, PGE, GPW, ZUS, NBP, KNF, XTB, PKO BP, Tesla, BitradeX | CERT Polska 2025 Table 12; CSIRT KNF 2024/2025 |
| Spoofed media (fake-article template) | TVN/TVN24 (11,644 domains; 7 in 2024), Gazeta.pl (11,367), Polsat News (7,632), Onet (3,390), Wprost (3,189), TVP | CERT Polska 2025 Table 12; NASK OAD; Bitdefender |
| Marketplaces | OLX (28,562), Allegro (22,613) | CERT Polska 2025 |
| Parcels | InPost, Poczta Polska, DHL | CERT Polska 2025; CSIRT KNF 2024 |
| Giveaways | Lidl, Biedronka, Rossmann, Kaufland, Decathlon, Smyk, Kross, Dove, Nivea, Żabka, Lotto / Mini Lotto | Demagog 08.2026; NASK OAD |
| Government / refunds | gov.pl, Ministerstwo Finansów / e-Urząd Skarbowy, NFZ, e-TOLL, Przelewy24, energy suppliers (Tauron), city transport cards | CERT Polska 2025 |
| Fund recovery | Interpol, Europol, "cyber police" | Debunk.org; NASK OAD |

**Narrative/production templates seen in Poland** [V]: (1) deepfake talking head; (2) fake news-studio intro (TVP/TVN/Polsat anchor) + deepfaked expert, e.g. doctor attacking "Big Pharma" (NASK OAD); (3) staged studio quarrel / "scandal on air" (Demagog: Chylińska–Wieniawa, Braun–Mentzen, Obajtek–Glapiński); (4) "banker mic-drop" — NBP governor sues/exposes a celebrity (Bitdefender); (5) celebrity death / testament / inheritance article (Demagog, Bitdefender); (6) state-project shares for every citizen (Orlen, Baltic Pipe, Baltica); (7) "national income support programme" (NASK OAD); (8) brand giveaway/survey; (9) fund recovery.

**Evasion techniques documented by CSIRT KNF 2025 (pp. 21–24) [V]** — each needs a countermeasure in preprocessing *and* is itself a fingerprint:

| Technique | Countermeasure | As a feature |
|---|---|---|
| Letters replaced by look-alikes from other alphabets | Unicode NFKC + confusables "skeleton" (UTS #39), strip zero-width joiners; OCR of the rendered text as fallback | Which characters are substituted and at what rate = stylometric signature of the obfuscation tool |
| Video padded with black/static frames (1–2 min payload) | Scene detection, drop black/static frames before hashing; vPDQ frame matching | Padding ratio, total duration |
| Ad versioning: one malicious version among neutral ones | Capture all versions; link versions through the ad ID | Number of versions, mix of destinations |
| Neutral "zaślepki" thumbnails | Rely on text + landing + account features; hash the decoy too | Decoy images are reused across ads |
| Cloaking by URL params / traffic source | Store exactly what the crawler saw; keep param names, redirect chain | White-page template hash; param-name set |

---

## 2. Feature catalogue

Link strength: **S** = near-certain on its own (after rarity check), **M** = meaningful, needs corroboration, **W** = weak/contextual. Robustness = how costly it is for the operator to change.

### 2.1 Text / narrative

| Feature | Extraction | Strength | Robustness to evasion |
|---|---|---|---|
| Normalised exact text hash | lowercase, NFKC, confusables skeleton, strip emoji/URLs/numbers → SHA-1 | S (dedup) | Low — trivially varied |
| Near-duplicate text | word 5-shingles → MinHash (128 perms) → LSH, Jaccard ≥0.6–0.8; also SimHash | S–M | Medium — spinning breaks it; templates with swapped names still score high after entity masking |
| Entity-masked template | replace persons/brands/amounts/URLs with `<PER>`, `<ORG>`, `<AMT>` → hash / MinHash | M–S | High — the script survives localisation ("same script, different names", Bitdefender) |
| Semantic embedding | multilingual sentence encoder (BGE-M3 / multilingual-e5 / Polish MMLW family [M]) → cosine | M | High vs paraphrase; low specificity (all investment scams look alike) |
| Narrative cluster ID | HDBSCAN/BERTopic on embeddings, or LLM taxonomy (§3) | W–M | High |
| **Rare tokens / invented names** | fake platform names ("Cyrkiel Zyskanta", "Biegła Fundeza"), product names, hashtags; detect as out-of-vocabulary capitalised n-grams + LLM `product_or_platform_name` | **S** | Medium — rotates over time, but within a window it is a deliberate campaign key (CSIRT KNF) |
| Numeric claims | regex + LLM: amounts, currency, % return, time-to-profit, minimum deposit (e.g. "1000 zł", "250 EUR") | W–M | Medium |
| Stylometry | char 3-grams, punctuation/emoji profile, capitalisation, typical translation artefacts, language-ID mix | W–M | High (operators don't think about it) |
| Obfuscation signature | mixed-script ratio, set of substituted code points, zero-width chars | M | High until tool changes |
| CTA phrase | normalised CTA text + button type | W | Low |
| OCR text of creative | PaddleOCR/EasyOCR → same features as above | as above | Often more stable than the post text |
| ASR transcript | faster-whisper (pl) → same text features; script reuse across different deepfaked faces | M–S | High — re-recording costs effort |

### 2.2 Visual / production template

| Feature | Extraction | Strength | Robustness |
|---|---|---|---|
| Cryptographic hash | SHA-256 of media bytes | S (dedup) | None vs re-encode |
| Perceptual hash | PDQ (Hamming ≤ ~31/256 [M, Meta's suggested threshold]) or pHash; for video vPDQ over non-black keyframes | S | Medium — survives re-encode/resize; fails on heavy crops/overlays |
| Copy-detection embedding | SSCD / ISC descriptor → cosine | S–M | High vs crops, overlays, borders |
| Semantic image embedding | SigLIP/OpenCLIP | W–M | High but unspecific |
| Layout/template | OCR box geometry (normalised boxes → grid histogram), dominant colours, presence of lower-third, logo position, aspect ratio, subtitle font/colour/stroke | M | High — the editing preset is reused |
| Logo / brand | Phishpedia/KnowPhish matcher or CLIP zero-shot against brand DB (TVN24, Onet, Orlen…) | W (popular) – M (rare) | Medium |
| Source-footage identity | hash/embedding of the *background clip* (same interview segment reused under different voice-overs) | S | High |
| Black/static padding profile | fraction of near-black frames, position of payload | M | Medium |
| Watermarks / tool artefacts | CapCut end-cards, TTS-tool watermarks, stock-footage IDs, recurring B-roll | M | Medium |
| EXIF/XMP / encoder metadata | exiftool, ffprobe (encoder string, creation time, software) where the platform doesn't strip it | M when present | Platforms usually strip; landing-page images often keep it (CSIRT KNF hint) |

### 2.3 Persons

| Feature | Extraction | Strength | Robustness |
|---|---|---|---|
| Identity match to reference DB | face detect → ArcFace embedding → cosine to 5–10 reference images per person, threshold + margin; aggregate over frames | **W for popular faces**, M for rare ones | High (the lure *is* the person) |
| Set of persons co-occurring | Jaccard over identity sets (e.g. {Glapiński, Tusk}) | M | High |
| Same face *asset* | face-crop perceptual hash / SSCD on aligned crop; same source photo or frame | S | Medium |
| Unknown-face cluster | cluster embeddings of unmatched faces (fictional doctors, AI "avatar farm" presenters) | M–S | High — synthetic presenters are reused (Gen Digital 2026 [S]) |
| Role | LLM: `claimed_authority` (doctor, banker, president, journalist) | W | High |
| Name mentions in text | NER + gazetteer + fuzzy match incl. obfuscated spellings | W | Medium |

Key design point: weight identity by rarity. Brzoska's face in two ads says almost nothing; the same *source clip* of Brzoska, or an unknown synthetic presenter recurring, says a lot.

### 2.4 Audio / video

| Feature | Extraction | Strength | Robustness |
|---|---|---|---|
| Audio fingerprint | Chromaprint/AcoustID-style landmarks on the soundtrack | S | Medium — survives re-encode, not re-synthesis |
| Speaker/voice embedding | ECAPA-TDNN (SpeechBrain) → cosine; same cloned voice or same stock TTS voice | M | Medium |
| Background music / jingle | fingerprint after speech separation or on non-speech segments | M | High |
| ASR script | §2.1 | M–S | High |
| Video structure | duration, shot count, shot-length sequence, resolution, fps, aspect, subtitle burn-in | W–M | Medium |
| TTS/voice-clone artefacts | prosody stats, sample rate, vendor watermark detectors if available | W | Low |

### 2.5 Landing page / infrastructure

| Feature | Extraction | Strength | Robustness |
|---|---|---|---|
| Registrable domain (eTLD+1) | `tldextract`; exclude shorteners, social platforms, big marketplaces, decoy domains (`amazon.pl`) | **S** | Low per domain (median life 11 days) but campaigns rotate within families |
| Domain-generation pattern | regex/tokenised shape (`finance\d\d-[a-z]+\d\d\.sbs`), char-class skeleton, dictionary source (lorem ipsum), TLD, length | **S** | Medium — pattern persists across hundreds of domains |
| Redirect chain | headless fetch with ad-like referrer/params; ordered list of hops; intermediate redirector domains | S | Medium |
| URL path / parameter names | path template (`/lander/<x>_<n>/`), set of query keys (`utm_*`, `fbclid`, `pixel`, `subid`, `MPC_3`, campaign-id formats) | S–M | High — baked into tracker config |
| **Tracker IDs** | regex on HTML/JS: Meta Pixel `fbq('init','…')`, GA `G-…`/`UA-…`, GTM `GTM-…`, Yandex Metrika, TikTok pixel, Hotjar; Keitaro markers | **S** | High — changing means losing optimisation data (Starov 2018; Bitdefender) |
| Form backend | POST endpoint host/path, hidden field names, UUIDs, CRM/API host (`…/api/v1/submit/<UUID>/`) | **S** | High |
| HTML structure | DOM tag-sequence SimHash, TLSH/ssdeep of normalised HTML, CSS class-name set Jaccard, CSS file hash, JS file hashes, comments (language!) | S–M | High (kits) |
| Screenshot | PDQ / SSCD on full-page screenshot | M–S | High |
| Favicon hash | mmh3 of favicon bytes | M | Medium |
| Embedded contact/payment | phone, e-mail, Telegram/WhatsApp handle, IBAN, crypto wallet, BLIK instructions | **S** | High |
| Hosting | A/AAAA, ASN, NS, MX; Cloudflare is uninformative (82% of listed IPs) | W (CDN) – M (dedicated IP) | Medium |
| TLS | cert issuer, SAN list from CT logs, JARM | W–M | Medium |
| WHOIS/RDAP | registrar, creation date, registration burst (same day/registrar/NS) | M | Medium |
| Cloaking behaviour | differential response by params/UA/geo; white-page hash | M | High |
| Page language/locale, geo-switching | langid + `hreflang` + IP-geo API calls (`ipinfo.io`) | W | High |
| On a blocklist | CERT Polska list membership + sibling domains | label, not link | — |

### 2.6 Advertiser / account metadata

| Feature | Extraction | Strength | Robustness |
|---|---|---|---|
| Page/advertiser ID | Ad Library `page_id` | S for same page (but hijacked pages host mixed campaigns) | Low — pages are disposable; CSIRT KNF reported 4,358 profiles in 2025 |
| Payer / beneficiary string | `beneficiary_payers` (free text) — normalise; flag junk ("1", "369", "facebook") | M when rare; W when junk-common | Low–medium |
| Page-name pattern | char-shape skeleton, language, random-string entropy, brand token | W–M | Medium |
| Page history | creation date, name changes, admin countries (page transparency), follower count, category | M (admin-country mix, rename history) | High |
| Ad-library ID proximity / batch | numeric distance of ad IDs created together; multiple versions under one ID | W–M | Medium |
| Targeting | age range, gender, locations | W | Medium |
| Reach / spend bucket | `eu_total_reach`, impressions bucket | W | Low |
| Platforms / placements | `publisher_platforms` | W | Low |
| Campaign/ad-set naming strings | when exposed through URL macros (`{{campaign.name}}`) — e.g. Russian tokens | M–S | High |

### 2.7 Behavioural / temporal

| Feature | Extraction | Strength | Robustness |
|---|---|---|---|
| Launch synchrony | ads starting within Δt on different pages | W alone; M as a multiplier of other evidence | Medium |
| Run-time profile | lifetime hours, stop reason | W | Low |
| Burst/rotation pattern | new domain every N hours; theme rotation calendar | M at campaign level | High |
| Posting-hour histogram | infer operator time zone | W | High |
| Report metadata | how many users reported, when, where seen | context / priority | — |
| Reappearance after takedown | same creative from a new page within hours | M | High |

### 2.8 Latent features

- Per-modality embeddings (text, image, face, voice) kept **separate**; one concatenated multimodal vector destroys explainability.
- Optional graph embedding (node2vec / FastRP) of the entity graph as an extra candidate generator, never as evidence.
- LLM-derived attributes (§3) are the bridge between latent and hand-crafted: semantic, but named and inspectable.

---

## 3. LLM-based feature augmentation

### 3.1 Is the "derive body type from car model" idea established? Yes.

| Line of work | Core idea | Relevance |
|---|---|---|
| **CAAFE** — Hollmann, Müller, Hutter, NeurIPS 2023 (arXiv 2305.03403) [S] | LLM reads dataset description, proposes new feature code, keeps a feature only if cross-validated performance improves; each feature comes with a text rationale. | Exactly the propose → test → keep loop; the "body type from model" analogy is its semantic-knowledge injection. |
| **FeatLLM** — Han et al., ICML 2024 (arXiv 2404.09491) [S] | LLM writes class-wise rules from few shots; rules become binary features for a linear model; LLM not needed at inference. | Binary, interpretable features; cheap inference. |
| **LLM-FE** — Abhyankar, Shojaee, Reddy, 2025 (arXiv 2503.14434) [S] | Feature engineering as evolutionary program search with data feedback; works with Llama-3.1-8B. | Shows small local models suffice for proposing features. |
| **Viswanathan et al. — LLMs Enable Few-Shot Clustering**, TACL 2024 (arXiv 2307.00524) [S] | Three insertion points: *before* (keyphrase expansion appended to the embedding), *during* (LLM as pairwise-constraint oracle), *after* (LLM corrects low-confidence assignments). | Our design uses all three: attribute expansion, LLM pair-judge for borderline edges, post-hoc cluster audit. |
| **ClusterLLM** — Zhang, Wang, Shang, EMNLP 2023 (arXiv 2305.14871 [M]) | LLM answers triplet questions to fine-tune the embedder; pairwise questions set granularity. | Use sparingly: LLM judgements on hard triplets → tune fusion weights. |
| **GoalEx** — Wang, Shang, Zhong, EMNLP 2023 (arXiv 2305.13749 [M]) | Propose natural-language cluster descriptions for a goal → assign → select; clusters are explainable by construction. | Template for campaign/narrative descriptions. |
| **D5** — Zhong et al., NeurIPS 2023 (arXiv 2302.14233 [M]) | LLM proposes natural-language hypotheses that distinguish corpus A from B, validated statistically. | Our "what distinguishes these two near-merged clusters?" refinement step. |
| **TnT-LLM** — Wan et al., KDD 2024 (arXiv 2403.12173) [S] | LLM builds and refines a label taxonomy over mini-batches, pseudo-labels a sample, a light classifier scales it. | How to get a stable `scam_type` / `narrative_template` vocabulary cheaply. |
| **TopicGPT** (Pham et al., NAACL 2024 [M]); **LLooM** (Lam et al., CHI 2024, arXiv 2404.12259 [S]) | LLM-generated topics/concepts with explicit inclusion criteria and 0–1 concept scores per document. | Concept scores = new feature columns. |
| **Text Bottleneck Models** — Ludan et al., 2023 (arXiv 2310.19660) [S] | LLM discovers a sparse set of concepts, measures each per text, a linear layer predicts. | The cleanest formal statement of "LLM attributes → linear, explainable model". Cost caveat: several LLM calls per text. |
| **Text Clustering as Classification with LLMs** — Huang & He, 2024 (arXiv 2410.00927) [S] | Generate labels, then classify every item. | Fine for narrative labels; too coarse for campaigns. |
| **BERTopic** LLM representation models (Grootendorst [M]) | Embedding clustering, LLM only names clusters. | Cheap naming of narrative clusters. |
| **Clio** — Tamkin et al., 2024 (arXiv 2412.13678 [M]) | Facet extraction per item → embed facet text → cluster → LLM-name hierarchy. | "Embed the normalised extracted value" pattern. |
| LLM-as-annotator: Gilardi et al., PNAS 2023; Ziems et al., 2024 [M]; LLM entity matching: Peeters, Steiner, Bizer, EDBT 2025 (arXiv 2310.11244 [M]) | LLMs match or beat crowd annotators on many labelling tasks; LLM pair-matching is strong but costly per pair. | Supports LLM extraction per item and LLM judging only for a small set of borderline pairs. |

Takeaways from this literature: (i) extract **per item**, compare **cheaply** — never ask the LLM about all pairs; (ii) constrain values to a vocabulary, otherwise synonyms destroy Jaccard; (iii) keep only attributes that measurably help; (iv) store the rationale/evidence span, which doubles as explanation.

### 3.2 Proposed attribute schema

One call per *unique creative* (after dedup), input = post text + OCR text + ASR transcript + landing-page title/visible text (+ optionally the image for a vision model). Every field allows `null`; every non-null field has a matching evidence quote.

```json
{
  "schema_version": "1.0",
  "language": "pl",
  "locale_cues": ["zł", "PESEL", "BLIK"],
  "translation_artifacts": true,

  "scam_type": "investment_fake_platform",
  "scam_subtype": "state_company_shares",
  "narrative_template": "banker_scandal",
  "creative_format": "fake_news_studio_plus_expert",

  "impersonated_persons": [
    {"name": "Adam Glapiński", "role_claimed": "prezes NBP", "mode": "deepfake_video"}
  ],
  "impersonated_brands": [
    {"name": "Orlen", "kind": "state_company"},
    {"name": "TVN24", "kind": "media_outlet"}
  ],
  "claimed_authority": ["central_bank", "tv_news"],
  "fictional_persona": {"name": null, "role": null},

  "product_or_platform_name": "Cyrkiel Zyskanta",
  "product_category": "trading_platform",
  "promised_return": {"amount": 25000, "currency": "PLN", "period": "month", "raw": "25 000 zł miesięcznie"},
  "entry_cost": {"amount": 1000, "currency": "PLN", "raw": "wystarczy 1000 zł"},
  "guarantee_claims": ["no_risk", "state_backed"],

  "call_to_action": "register_lead_form",
  "contact_channel": ["web_form", "phone_callback"],
  "payment_channel": ["card", "bank_transfer"],
  "data_requested": ["name", "phone", "email"],

  "urgency_cues": ["limited_places", "deadline_today"],
  "emotional_triggers": ["greed", "outrage_at_elites", "fear_of_missing_out"],
  "hook_type": "censored_interview",
  "conspiracy_frame": "they_dont_want_you_to_know",
  "target_audience": ["seniors", "low_income"],
  "eligibility_claim": "every_polish_citizen",

  "medical_claims": {"condition": null, "mechanism": null},
  "distinctive_phrases": ["program wsparcia dochodu", "bank próbował to ukryć"],

  "evidence": {
    "scam_type": "„każdy obywatel może zostać udziałowcem”",
    "product_or_platform_name": "„platforma Cyrkiel Zyskanta”"
  },
  "confidence": {"scam_type": 0.9, "narrative_template": 0.7}
}
```

Controlled vocabularies (start small, extend via §3.4):

- `scam_type`: `investment_fake_platform`, `fund_recovery`, `health_miracle_product`, `fake_giveaway_survey`, `fake_shop`, `parcel_delivery_phishing`, `gov_refund_or_benefit_phishing`, `illegal_gambling`, `transport_card_offer`, `marketplace_phishing`, `job_task_scam`, `subscription_trap`, `malware_app`, `political_disinfo_ad`, `other`.
- `narrative_template`: `banker_scandal`, `celebrity_testament_or_death`, `staged_studio_quarrel`, `censored_interview`, `state_project_shares`, `national_income_programme`, `doctor_vs_big_pharma`, `brand_anniversary_giveaway`, `clearance_sale`, `undelivered_parcel`, `lost_funds_recovery`, `other`.
- `creative_format`: `deepfake_talking_head`, `fake_news_studio_plus_expert`, `fake_article_screenshot`, `static_portrait_with_headline`, `product_packshot`, `neutral_decoy`, `ugc_testimonial`, `screen_recording`, `other`.

### 3.3 Turning attributes into features and edges

| Attribute kind | Normalisation | Pairwise comparison | Graph representation |
|---|---|---|---|
| Single categorical (`scam_type`, `narrative_template`, `creative_format`, `call_to_action`) | enum | agree / disagree / missing; **disagreement on `scam_type` is negative evidence** | `(:Ad)-[:HAS_NARRATIVE]->(:Narrative)` |
| Multi-label sets (`urgency_cues`, `emotional_triggers`, `guarantee_claims`, `data_requested`) | enum sets | Jaccard, or IDF-weighted Jaccard | properties, or shared `(:Tactic)` nodes |
| Named entities (`impersonated_persons`, `impersonated_brands`) | link to reference DB by fuzzy match (rapidfuzz) + alias table; keep unlinked as raw | rarity-weighted set overlap | `[:DEPICTS]`, `[:IMPERSONATES]` |
| Open short strings (`product_or_platform_name`, `fictional_persona.name`, `distinctive_phrases`) | lowercase, strip diacritics, confusables skeleton | exact match → strong; Jaro-Winkler ≥0.92 or char-3-gram Jaccard → medium; embed the value for semantic match | `(:Phrase)` / `(:FakePlatform)` nodes — these become the best human-readable hubs |
| Numeric (`promised_return`, `entry_cost`) | convert to PLN/month; bucket | same bucket / exact same raw string | property |
| Whole-record "facet text" | concatenate key facets into one canonical sentence | cosine of its embedding (Clio/keyphrase-expansion pattern) | — |

Edge explanations are assembled from templates over the evidence list, not generated freely, e.g.:

> Połączono (p=0.97): ten sam Meta Pixel `7421…` [+9.1]; ta sama nazwa platformy „Cyrkiel Zyskanta” [+6.3]; skrypt po zamaskowaniu nazwisk zgodny w 83% [+4.2]; ten sam schemat narracji `banker_scandal` [+1.1]; twarz: A. Glapiński w obu [+0.6 — słaby sygnał, występuje w 312 reklamach].

An LLM may then *summarise* a whole campaign ("campaign card": name, modus operandi, top indicators, timeline, persons, suggested blocklist items) from those structured evidences — summarising verified facts, not inventing links.

### 3.4 Iterative refinement (LLM proposes new attributes)

1. **Find discrepancies.** (a) pairs with a strong infrastructure link but low attribute similarity (missing attribute?); (b) pairs with high attribute similarity but no strong link and different infrastructure (attributes too coarse?); (c) large clusters with low internal cohesion; (d) neighbouring clusters the fusion keeps almost merging.
2. **Ask.** Show the LLM 5–10 items from each side: "State up to 5 concrete, checkable attributes that are shared within group A but differ from group B. For each give a name, a definition, allowed values, and an extraction instruction." (D5 / GoalEx / LLooM pattern.)
3. **Measure on a sample** (200–500 creatives): coverage (non-null rate), cardinality, stability (re-run agreement), and **utility**: mutual information with strong-ID pseudo-labels (pixel ID, domain family), and ΔAUC of the pairwise model on the labelled/weak-labelled pair set.
4. **Keep or drop** (CAAFE acceptance rule). Version the schema; back-fill only for kept attributes.
5. **Consolidate vocabulary** every round: LLM merges synonymous values into the enum (TnT-LLM style), humans approve.

Guards: require evidence quotes and allow `null`; never let an LLM-only attribute create a strong link; cap the weight of LLM attributes so that two ads cannot be merged on LLM attributes alone; log prompt + model version per value.

### 3.5 Cost and latency

I am deliberately not quoting API prices — check the current price list of whichever provider you use. Sizing facts that do not depend on price:

- Volume driver is **unique creatives after dedup**, not reports. Cache by content hash.
- Per creative: roughly 1–3k input tokens (post + OCR + ASR + landing text; truncate ASR), 300–500 output tokens. 10k creatives ≈ 10–30M input / 3–5M output tokens — a small-model batch job. (Token counts are my estimate from typical ad lengths.)
- **Tiering**: (1) regex/gazetteer/GLiNER for entities, amounts, URLs — milliseconds on CPU, run on everything; (2) small LLM for the structured record — run on unique creatives; (3) a stronger model only for schema refinement, taxonomy consolidation, borderline pair judging and campaign cards — hundreds of calls, not thousands.
- **Local option** for a "data stays in Poland" story: Bielik v3 (1.5B / 4.5B / 11B, Apache-2.0 [S]) or PLLuM (NASK now leads the HIVE consortium; licences vary per checkpoint, some non-commercial, some gated [S]) via llama.cpp/Ollama with grammar-constrained JSON. On CPU only, an 11B model at 4-bit will be on the order of tens of seconds per creative (my rough estimate — benchmark on the actual machine), so use 4.5B or smaller locally, or a GPU, or an API for the bulk pass.
- Use schema-constrained decoding (provider structured outputs, or GBNF/Outlines locally) so parsing never fails; temperature 0; few-shot examples in Polish.
- A vision-capable model can take the creative image directly and return the same schema plus layout description — one call replaces OCR + text LLM for static ads; keep OCR anyway for the hash/MinHash features.

---

## 4. Similarity fusion and clustering

### 4.1 Options compared

| Option | Strengths | Weaknesses | Explainable edge? | Incremental? |
|---|---|---|---|---|
| **(a) Weighted multi-signal similarity + per-signal thresholds** | Simple; every term is a named signal; easy to tune live | Hand-set weights; scores not probabilities; popular values (Brzoska, Cloudflare) inflate similarity unless rarity-adjusted | Yes | Yes |
| **(b) Strong-link union-find, then HDBSCAN/agglomerative on fused distance** | Near-zero false merges in cores; cores shrink the problem; matches analyst practice | Single-linkage chaining through hub values; HDBSCAN on a fused precomputed matrix is O(n²) memory and its density notion is hard to explain; noise label leaves many ads unassigned | Cores yes; HDBSCAN merges only indirectly | Union-find yes; HDBSCAN `approximate_predict` works for vector input, not precomputed distances |
| **(c) Community detection on heterogeneous entity graph** | Natural for Neo4j; explanations are paths; adding a node is local | Unweighted entity hubs dominate; modularity resolution limit; communities shift when re-run | Yes (paths) | Partly (local re-optimisation) |
| **(d) Learned pairwise model (LR/GBDT on feature diffs; weak supervision)** | Calibrated probabilities; learns interactions; weights justified by data | Needs labelled or weak-labelled pairs; GBDT explanations need SHAP; risk of learning the labeling functions back | LR: yes; GBDT: via SHAP | Yes |
| **(e) Late fusion of per-modality HDBSCAN** | Each modality tuned separately; modality clusters are useful objects (narratives, templates) | Consensus step is ad hoc; cross-modal weak-signal accumulation ("minor signals that together point to one source") is exactly what it loses | Coarse ("same text cluster") | Per-modality predict |

### 4.2 Recommendation for a 24–48 h POC

A hybrid that is (b)'s structure with (a)'s scoring written in (d)'s probabilistic form, stored as (c)'s graph, with (e)'s per-modality clusters demoted to features:

**Stage 0 — canonicalise.** Unicode skeleton, OCR, ASR, keyframes without black padding, URL expansion and landing snapshot.

**Stage 1 — deduplicate reports into creatives.** Union-find over: identical media SHA-256; PDQ/vPDQ within tight threshold; normalised-text hash; text MinHash Jaccard ≥0.9 with same landing domain. Output `(:Report)-[:REPORTS]->(:Ad)-[:INSTANCE_OF]->(:Creative)`; keep report counts. This alone answers "sent 47 times".

**Stage 2 — candidate generation (blocking).** Never score all pairs. Union of: inverted index on exact keys (domain, tracker ID, form endpoint, phone, page ID, platform name, face-asset hash); MinHash-LSH on text and on entity-masked text; ANN top-k (FAISS/hnswlib) per embedding space (text, SSCD, face, voice). Cap hub keys (a value shared by more than, say, 2% of ads generates no candidates by itself).

**Stage 3 — evidence scoring (Fellegi–Sunter form).** For each candidate pair and each signal *s* with comparison level *l* (exact / close / different / missing):

`w_s,l = log2( m_s,l / u_s,l )`, score = Σ w, `p = sigmoid(ln2·(score + prior))`

- `u` (chance agreement among unrelated ads) is **estimated from the data** as the value's frequency: sharing a value seen in 2 ads is strong, sharing one seen in 300 is weak. This single trick implements "celebrity identity is weak, rare pixel ID is strong" without hand-tuning.
- `m` (agreement among truly related ads) starts from tiered priors (S ≈ 0.9, M ≈ 0.6, W ≈ 0.3) and is refined either by Splink-style EM or by logistic regression on weak labels (Stage 3b).
- Missing data contributes 0, not a penalty. Explicit contradictions (different `scam_type`, different language *and* market) contribute negative weight.
- Correlated signals (text hash, MinHash, embedding of the same text) are grouped: take the max level within a group rather than summing, otherwise the naive-Bayes assumption triple-counts.
- The list of `(signal, value, level, weight)` tuples **is** the edge explanation.

**Stage 3b (optional, if time) — learn the weights.** Weak labels: positives = pairs sharing a rare tracker ID / form endpoint / wallet; negatives = pairs with different scam type and non-overlapping infrastructure, plus random pairs far apart in time. Train logistic regression on the comparison levels **with the labeling signal left out** of the features, non-negative constraints on agreement weights. Coefficients replace the priors and stay readable. GBDT only as a benchmark.

**Stage 4 — clustering, three levels.**

1. **Campaign cores** = connected components over edges that contain at least one S-tier, non-hub signal (or p ≥ 0.99). High precision, analyst-defensible.
2. **Campaigns** = Leiden (CPM, tuned resolution) on the weighted ad–ad graph restricted to p ≥ τ_edge, with cores contracted to super-nodes. Protect against chaining: require that a merge between two cores is supported by ≥2 independent signal groups or by average (not single) linkage above threshold.
3. **Playbook families** = agglomerative/Leiden at lower resolution using only narrative/template/person features — "same playbook, possibly different operators" (Bitdefender's sub-campaign vs operator distinction). Presenting this as a separate level avoids over-claiming common operatorship.

HDBSCAN's role: cluster text embeddings into narrative clusters and SSCD embeddings into template clusters; those cluster IDs become nodes/features. Run HDBSCAN on the fused distance matrix once as an ablation baseline to show judges the comparison.

**Stage 5 — incremental assignment.** New ad → Stage 0–1 (may collapse into an existing creative) → candidates from the indexes → score against candidates → assign to the campaign with the highest average-of-top-k edge probability if above τ_assign, otherwise new singleton campaign; if it links strongly to two campaigns, emit a *merge proposal* rather than silently merging. Re-run Leiden nightly; keep campaign IDs stable by majority-overlap mapping.

**Stage 6 — explanation.** Edge: itemised evidence. Campaign: top shared indicators ranked by coverage × weight, timeline, persons, domains, LLM-written card. Confidence shown as probability with the two or three decisive signals.

Why this over the alternatives: it is the only option that simultaneously gives per-edge reasons, lets weak signals accumulate, handles hubs, and adds new ads without re-clustering — and it can be built incrementally (Stage 1+3 with hand priors is a working demo on day one; 3b and level 3 are upgrades).

### 4.3 Thresholds to start from (tune on your data)

| Signal | Level "exact/strong" | Level "close" |
|---|---|---|
| PDQ Hamming (256-bit) | ≤ 16 | ≤ 31 |
| SSCD cosine | ≥ 0.75 | ≥ 0.6 |
| Text MinHash Jaccard (5-shingles) | ≥ 0.8 | ≥ 0.5 |
| Entity-masked text Jaccard | ≥ 0.7 | ≥ 0.45 |
| Sentence-embedding cosine | ≥ 0.92 | ≥ 0.85 |
| Face identity cosine (ArcFace) | ≥ 0.5 same person | 0.35–0.5 uncertain |
| Speaker embedding cosine | ≥ 0.7 | ≥ 0.55 |
| HTML TLSH distance | ≤ 40 | ≤ 80 |

These are common starting points from my experience with these tools [M], not values taken from the cited reports; calibrate each on the synthetic set (§4.6).

### 4.4 Failure modes to design against

- **Hub contamination**: Cloudflare IPs, `facebook.com` links, URL shorteners, stock photos, a famous face, a generic CTA. → frequency caps + rarity-weighted `u`.
- **Hijacked pages** run unrelated campaigns → `page_id` is S only when the page's other ads agree on something else.
- **Shared kits/affiliate networks**: same landing kit ≠ same operator. → keep the family level separate and say so.
- **Cloaked landing pages**: two ads look linked because both got the same white page. → detect white pages (generic template, on many unrelated ads) and treat as hub.
- **LLM drift**: label synonyms split clusters. → enums + consolidation.
- **Chaining** via single linkage. → average linkage between cores, ≥2 signal groups for merges.

### 4.5 Evaluation without ground truth

1. **Synthetic campaigns (primary).** Take N seed ads; generate variants with known lineage: re-encode/crop/overlay/pad video with black frames; homoglyph substitution; LLM paraphrase; swap celebrity name; swap domain but keep pixel ID; duplicate 47×. Plant them in the real pool. Report pairwise precision/recall/F1, B-cubed F1, ARI/AMI, and dedup accuracy; ablate one signal layer at a time.
2. **Held-out-identifier validation.** Remove one strong identifier family (e.g. tracker IDs) from the features, cluster, then measure homogeneity/completeness of clusters w.r.t. that identifier. Repeat for domain family and page ID. This is the most convincing label-free number.
3. **Known-campaign recall.** If the data contains the CSIRT KNF `finance…sbs` family or the listed theme names, check they end up in one campaign.
4. **Hand-labelled pair sample.** 200–300 pairs stratified by score decile, two annotators, Cohen's κ; gives a precision-vs-threshold curve and calibrates τ. An LLM judge can pre-label, humans verify a subset.
5. **Cluster audit.** Sample 20 campaigns; rate purity (fraction of members an analyst agrees belong) and whether the explanation is sufficient to convince without opening the ads.
6. **Internal/stability metrics (secondary).** Silhouette or DBCV on embedding clusters; modularity/conductance on the graph; cluster stability under bootstrap resampling and under resolution sweep; singleton rate; size distribution. Report them, but do not optimise on silhouette — campaigns are not convex blobs.
7. **Proxy purity.** Share of campaigns with a single `scam_type`, single language, compact time span; landing-domain entropy per campaign.
8. **Operational metric.** Reports-to-campaign compression ratio and "blocklist yield" (new sibling domains surfaced per campaign).

---

## 5. Graph store and schema

### 5.1 Neo4j vs alternatives (CPU POC)

| Option | For | Against | Verdict |
|---|---|---|---|
| **Neo4j Community + GDS** (Docker) | Named in the brief; Cypher; Browser/Bloom visuals; GDS has WCC, Louvain, Leiden, node similarity [M: available in Community with a concurrency cap] | JVM memory; nested maps not allowed as properties; GDS graph projections add a step | **Use as system of record and demo surface.** |
| **NetworkX/igraph + pyvis** | Zero infra; fastest to iterate; leidenalg; HTML export | No query language; no persistence; pyvis struggles beyond a few thousand nodes | **Use for all computation**, and as offline fallback visual. |
| **Kùzu** | Embedded, fast, Cypher | **Repository archived 10 Oct 2025** (v0.11.3 last) [S]; community forks LadybugDB and RyuGraph exist but are young | Avoid for a hackathon unless someone already knows it. |
| **Memgraph** | In-memory, Cypher-compatible, MAGE algorithms incl. online community detection, Lab UI; good streaming story | Another service to learn; licence differs (BSL) [M] | Viable alternative if the team prefers it; no decisive advantage at POC scale. |
| **FalkorDB** | Redis-based, fast | Smaller ecosystem | Not needed. |

Practical split: Python computes features, edges and clusters → bulk-load to Neo4j with `UNWIND` batches → Cypher for explanations and the UI. At POC scale (≤10^5 nodes) every option runs on a laptop.

### 5.2 Schema

**Nodes**

| Label | Key properties |
|---|---|
| `Report` | `id`, `reported_at`, `source`, `reporter_hash` |
| `Ad` | `id`, `platform`, `ad_library_id`, `first_seen`, `last_seen`, `text`, `lang`, `reach_bucket`, LLM attributes as flat properties |
| `Creative` | `id`, `sha256`, `pdq`, `text_hash`, `n_ads`, `n_reports` |
| `MediaAsset` | `id`, `kind` (image/video/audio/face_crop), `pdq`, `duration`, `padding_ratio` |
| `Person` | `id`, `name`, `group` (NASK category), `in_reference_db` |
| `UnknownFace` | `cluster_id`, `n_ads` |
| `Brand` | `name`, `kind` (media/state_company/retail/gov/bank) |
| `Narrative` | `id`, `label`, `source` (hdbscan/llm), `description` |
| `Template` | `id`, `creative_format`, `layout_signature` |
| `Phrase` | `norm`, `kind` (fake_platform/product/distinctive_phrase), `df` |
| `ScamType` | `name` |
| `Url` | `url_norm`, `path_template`, `param_keys` |
| `Domain` | `etld1`, `tld`, `shape`, `registrar`, `created`, `on_cert_list` |
| `Host` | `ip`, `asn`, `is_cdn` |
| `Tracker` | `kind` (meta_pixel/ga/gtm/yandex/…), `value`, `df` |
| `Endpoint` | `host`, `path_template` (form backend) |
| `Contact` | `kind` (phone/email/telegram/whatsapp/iban/wallet), `value` |
| `Page` | `page_id`, `name`, `created`, `admin_countries` |
| `Payer` | `name_norm`, `is_junk` |
| `Campaign` | `id`, `label`, `level` (core/campaign), `n_ads`, `first_seen`, `last_seen`, `summary`, `confidence` |
| `Family` | `id`, `label`, `description` |

**Relationships**

| Pattern | Properties |
|---|---|
| `(Report)-[:REPORTS]->(Ad)` | `at` |
| `(Ad)-[:INSTANCE_OF]->(Creative)` | `method`, `distance` |
| `(Ad)-[:HAS_MEDIA]->(MediaAsset)` | `role` |
| `(Ad)-[:DEPICTS]->(Person\|UnknownFace)` | `score`, `frames`, `method`, `mode` (photo/deepfake_video/name_only) |
| `(Ad)-[:IMPERSONATES]->(Brand)` | `score`, `evidence` (logo/text/domain_typosquat) |
| `(Ad)-[:HAS_NARRATIVE]->(Narrative)`, `(Ad)-[:USES_TEMPLATE]->(Template)`, `(Ad)-[:OF_TYPE]->(ScamType)` | `confidence`, `source` |
| `(Ad)-[:MENTIONS]->(Phrase)` | `where` (text/ocr/asr/landing) |
| `(Ad)-[:LINKS_TO]->(Url)` | `position`, `displayed_domain` |
| `(Url)-[:REDIRECTS_TO]->(Url)` | `hop`, `status`, `observed_at` |
| `(Url)-[:ON_DOMAIN]->(Domain)`, `(Domain)-[:RESOLVES_TO]->(Host)` | `observed_at` |
| `(Domain)-[:USES_TRACKER]->(Tracker)`, `(Domain)-[:POSTS_TO]->(Endpoint)`, `(Domain)-[:SHOWS_CONTACT]->(Contact)` | `observed_at` |
| `(Domain)-[:SAME_KIT_AS]->(Domain)` | `tlsh_dist`, `css_jaccard` |
| `(Ad)-[:PUBLISHED_BY]->(Page)`, `(Ad)-[:PAID_BY]->(Payer)` | — |
| **`(Ad)-[:SIMILAR_TO]->(Ad)`** | `weight` (Σ log-weights), `p`, `tier` (strong/medium/weak), `signals` (list of names), `signal_weights` (parallel list), `explanation` (rendered text), `evidence_json` (full itemisation as a JSON string), `model_version`, `created_at` |
| `(Ad)-[:BELONGS_TO]->(Campaign)` | `confidence`, `assigned_at`, `method` (core/leiden/incremental), `top_evidence` |
| `(Campaign)-[:PART_OF]->(Family)` | `similarity`, `basis` |
| `(Campaign)-[:MERGE_CANDIDATE]->(Campaign)` | `p`, `evidence_json` |

Notes:

- Neo4j properties cannot hold nested maps → parallel arrays plus a JSON string, or reify as `(:Evidence {signal, value, level, weight})` nodes attached to both ads if you want to query evidence in Cypher.
- Keep **both** representations: entity nodes (the "why" is a path: `MATCH p=(a:Ad)-[*..3]-(b:Ad)`) and the computed `SIMILAR_TO` edge (the fused score). Embedding-based similarities have no natural entity node, so they live only on `SIMILAR_TO`.
- Store `df` (document frequency) on hub-prone nodes so the UI can grey out uninformative links.
- The schema maps cleanly onto STIX 2.1 objects (Campaign, Infrastructure, Indicator, Identity, Relationship with `description`) if NASK wants export to MISP/OpenCTI [M].

---

## 6. Suggested build order (48 h)

1. Ingest + canonicalise + dedup (Stage 0–1) → first graph in Neo4j. *Demo: 47 reports → 1 creative.*
2. Deterministic extractors: URLs/domains/tracker IDs/phones, OCR, PDQ, text MinHash → strong links + campaign cores.
3. Faces vs reference DB (15 persons), text embeddings, SSCD → medium links; rarity-weighted scoring; Leiden.
4. LLM structured extraction on unique creatives → attributes, `Phrase` nodes, narrative labels, edge/campaign explanations.
5. Synthetic-campaign evaluation + held-out-identifier purity + one ablation chart.
6. Incremental "add a new ad" demo path; campaign cards.

---

## 7. Gaps and caveats

- No official ranking of most-impersonated persons exists publicly; the shortlist in §1.5 is a synthesis. NASK's 121-name list is from July 2024; later counts (380, ~450) were reported without names.
- The CERT Polska table counts *domains*, not ads; brand prominence in ads may differ.
- Several academic entries are marked [M]/[S]; I did not open those PDFs in this session. The Vadrevu & Perdisci method description in particular is from memory.
- Repo licences and maintenance status were not verified (GitHub API rate-limited); Kùzu's archival is from secondary sources.
- I could not find any public description of the hackathon dataset format; the feature catalogue assumes ad creative + text + landing URL + some advertiser metadata are available. If landing pages are not provided or are dead, §2.5 shrinks to what can be parsed from the URL string itself (domain shape, path template, parameter names), which is still high-value.
- Threshold values in §4.3 and CPU-throughput remarks in §3.5 are starting estimates, not measurements.

---

## 8. References

**Polish sources**

- CERT Polska, Raport roczny 2025 — https://cert.pl/uploads/docs/Raport_CP_2025.pdf
- CERT Polska, expectations towards Meta (Dec 2024) and evaluation (Mar 2025) — https://cert.pl/en/posts/2024/12/expectations-from-meta/ , https://cert.pl/en/posts/2025/03/evaluation-of-expectations-towards-meta/
- CERT Polska warning list — https://cert.pl/lista-ostrzezen/ , https://hole.cert.pl/domains/v2/domains.txt
- CSIRT KNF, Raport roczny 2025 — https://cebrf.knf.gov.pl/images/Raporty/Raport_Roczny_CSIRT_KNF_97516.pdf
- CSIRT KNF, Raport roczny 2024 — https://www.knf.gov.pl/knf/pl/komponenty/img/Raport_Roczny_CSIRT_KNF_2024_93226.pdf
- CSIRT KNF, Masowa kampania wyłudzeń finansowych o zasięgu międzynarodowym — https://www.knf.gov.pl/knf/pl/komponenty/img/Raport_CSIRT_KNF_Masowa_Kampania_Wyludzen_99343.pdf
- CSIRT KNF deepfake examples — https://cebrf.knf.gov.pl/deepfake
- NASK, Lista osób, których wizerunek przestępcy wykorzystali w oszustwach deepfake (12.07.2024), archived — http://web.archive.org/web/20240812002303/https://www.nask.pl/download/30/4987/listaosobwykorzystanychdodeepfake01-072024.pdf
- NASK OAD, Reakcja platform społecznościowych na zgłoszenia w 2025 roku — https://www.nask.pl/media/2026/03/reakcja-platform-spolecznosciowych-na-zgloszenia-w-2025-roku.pdf
- Demagog, "Za co oszuści lubią Facebooka?" (20.08.2026) — https://demagog.org.pl/analizy_i_raporty/za-co-oszusci-lubia-facebooka-meta-przepuszcza-scamy-z-brzoska/
- XYZ.pl (27.01.2026; 05.02.2026) — https://xyz.pl/facebook-instagram-i-fala-oszustw-meta-wiekszosc-zgloszen-odrzuca-lub-nie-reaguje/ , https://xyz.pl/?p=161766
- Super Biznes (27.07.2024; 23.09.2026) — https://superbiz.se.pl/wiadomosci/podszywaja-sie-po-ksiezy-i-politykow-oszusci-coraz-skuteczniej-wykorzystuja-deepfake-aa-9hB2-2Jyi-iNYp.html , https://superbiz.se.pl/wiadomosci/ai-pomaga-oszustom-tracimy-setki-milionow-zlotych-na-falszywych-reklamach-aa-vwan-mvqW-NdhA.html
- CHIP.pl (20.05.2026) — https://www.chip.pl/2026/05/deepfakei-zalewaja-polski-internet-problemem-przestaje-byc-technologia-tylko-nasza-latwowiernosc

**Investigations**

- Bitdefender Labs — https://www.bitdefender.com/en-us/blog/labs/global-investment-scam-network-using-meta-ads
- Gen Digital — https://www.gendigital.com/blog/insights/research/scam-ad-machine-meta , https://www.gendigital.com/blog/insights/research/the-scam-ad-machine-part-ll
- KommAustria/RTR — https://www.rtr.at/medien/aktuelles/publikationen/Publikationen/Publikationen_2026/Betrugsoekosystem_Werbung_KommAustria_final_EN.pdf
- Infoblox — https://www.infoblox.com/blog/threat-intelligence/uncovering-actor-ttp-patterns-and-the-role-of-dns-in-investment-scams/
- AI Forensics — https://aiforensics.org/work/meta-political-ads , https://aiforensics.org/uploads/No_Embargo_in_Sight_AI_Forensics_Report.pdf
- CheckFirst — https://checkfirst.network/facebook-hustles-the-hidden-mechanics-of-a-scam-machinery-impersonating-news-organisations-and-creators/
- Qurium — https://www.qurium.org/alerts/exposing-the-evil-empire-of-doppelganger-disinformation/ ; EU DisinfoLab — https://www.disinfo.eu/doppelganger-operation/
- VIGINUM Portal Kombat — https://diplomatie.gouv.fr/IMG/pdf/20240212_np_sgdsn_viginum_rapport-reseau-portal-kombat_ru_vf_cle09caab-1.pdf
- Debunk.org — https://www.debunk.org/over-50k-ads-on-social-media-impersonated-interpol-europol-and-eu-institutions-promising-fraud-r ; summary https://oxylabs.io/blog/project-4beta-impact-how-debunk-revealed-scam-ads
- Tech Transparency Project — https://techtransparencyproject.org/articles/meta-awash-in-deepfake-scam-ads
- AdLens coverage — https://www.helpnetsecurity.com/2026/09/02/google-scareware-ads-research/

**Academic**

- Kotzias et al., NDSS 2025 — https://ndss-symposium.org/wp-content/uploads/2025-1816-paper.pdf
- Edelson et al., IEEE S&P 2020 — https://damonmccoy.com/papers/ad_library2020sp.pdf
- Starov et al., WWW 2018 — https://securitee.org/files/malanalytics_www2018.pdf
- Drew & Moore, 2014 — https://link.springer.com/article/10.1186/s13635-014-0014-4
- Der et al., KDD 2014 — https://cseweb.ucsd.edu/~mfder/papers/knockoff_kdd14.pdf
- Zannettou et al., IMC 2018 — https://arxiv.org/abs/1805.12512
- Pacheco et al., ICWSM 2021 — https://arxiv.org/abs/2001.05658 ; Cinus et al. — https://arxiv.org/abs/2410.22716
- KnowPhish — https://arxiv.org/abs/2403.02253
- CAAFE — https://arxiv.org/abs/2305.03403 ; FeatLLM — https://arxiv.org/abs/2404.09491 ; LLM-FE — https://arxiv.org/abs/2503.14434
- Viswanathan et al. — https://arxiv.org/abs/2307.00524 ; TnT-LLM — https://arxiv.org/abs/2403.12173 ; LLooM — https://arxiv.org/abs/2404.12259 ; Text Bottleneck Models — https://arxiv.org/abs/2310.19660 ; Text Clustering as Classification — https://arxiv.org/abs/2410.00927
- Bielik v3 — https://arxiv.org/abs/2505.02550 , https://arxiv.org/abs/2601.11579 ; PLLuM — https://arxiv.org/abs/2511.03823

**Tools**

- https://github.com/facebook/ThreatExchange · https://github.com/facebookresearch/sscd-copy-detection · https://github.com/VIGINUM-FR/D3lta · https://github.com/ekzhu/datasketch · https://github.com/moj-analytical-services/splink (waterfall chart: https://moj-analytical-services.github.io/splink/charts/waterfall_chart.html) · https://github.com/snorkel-team/snorkel · https://github.com/scikit-learn-contrib/hdbscan · https://github.com/vtraag/leidenalg · https://github.com/lindsey98/Phishpedia · https://github.com/imethanlee/KnowPhish · https://github.com/deepinsight/insightface · https://github.com/urchade/GLiNER · https://github.com/SYSTRAN/faster-whisper · https://github.com/trendmicro/tlsh · https://github.com/fabiogiglietto/CooRnet · https://github.com/nicolarighetti/CooRTweet · https://github.com/viswavi/few-shot-clustering · https://github.com/zhang-yu-wei/ClusterLLM · https://github.com/ZihanWangKi/GoalEx · https://github.com/chtmp223/topicGPT · https://github.com/michelle123lam/lloom · https://github.com/MaartenGr/BERTopic · https://github.com/automl/CAAFE · https://github.com/Sungwon-Han/FeatLLM · https://github.com/nikhilsab/LLMFE · https://github.com/neo4j/graph-data-science · https://github.com/memgraph/memgraph · https://github.com/LadybugDB/ladybug · https://github.com/WestHealth/pyvis
- Kùzu archival — https://www.theregister.com/2025/10/14/kuzudb_abandoned/

---

## Appendix A — NASK list of persons used in deepfake scams (as of 12.07.2024), grouped

Source: NASK PDF (archived link in §8) [V]. 121 entries; spellings as in the original document.

**Dziennikarze (39)**: Michał Adamczyk, Magdalena Bałkowiec, Anna Bogusiewicz, Wojciech Cejrowski, Włodek Ciejka, Katarzyna Ciepielewska, Marek Czyż, Wojciech Dąbrowski, Justyna Dobrosz-Oracz, Katarzyna Dowbor, Ewa Drzyzga, Aleksandra Florczak (Ollasky), Dorota Gawryluk, Danuta Holecka, Aleksandra Janiec, Grzegorz Jankowski, Piotr Kraśko, Iwona Kutyna, Paweł Lisicki, Monika Majewska, Robert Mazurek, Piotr Nisztor, Monika Olejnik, Agnieszka Oszczyk, Rafał Patyra, Michał Rachoń, Małgorzata Rozenek, Diana Rudnik, Bogdan Rymanowski, Natalia Rzeźniczak, Piotr Salak, Sławomir Siezieniewski, Paulina Smaszcz, Alex Sumlińska, Marek Tejchman, Dorota Wellman, Anita Werner, Emilia Wierzbicki, Emilia Ziemnicka

**Politycy (26)**: Anna Anders, Marek Belka, Piotr Ćwik, Andrzej Domański, Agata Duda, Andrzej Duda, Adam Glapiński, Paulina Hennig-Kloska, Szymon Hołownia, Jarosław Kaczyński, Aleksander Kwaśniewski, Ursula von der Layen, Izabela Leszczyna, Jakub Maciejewski, Antoni Macierewicz, Sławomir Mentzen, Stanislaw Michałkiewicz, Kate Middleton, Mateusz Morawiecki, Magdalena Rzeczkowska, Czesław Siekierski, Łukasz Shreiber, Beata Szydło, Rafał Trzaskowski, Donald Tusk, Lech Wałęsa

**Przedsiębiorcy (13)**: Rafał Brzoska, Maciej Filipkowski, Magda Gessler, Fryderyk Karzełek, Phil Konieczny, Filip Kowarski, Sebastian Kulczyk, Jerzy Kwieciński, Elon Musk, Michał Sołowow, Wojciech Wiecławek, Rafał Zaorski, Mark Zuckerberg

**Duchowni (9)**: Stanisław Dziwisz, Stanisław Gądecki, Jacek Grzybowski, Leon Knabit, Mieczysław Mokrzycki, Piotr Natanek, Kazimierz Nycz, Krzysztof Pawlina, Robert Skrzypczak

**Sportowcy (6)**: Tomasz Adamek, Jerzy Brzęczek, Jacek Krzynówek, Robert Lewandowski, Wojciech Szczęsny, Iga Świątek

**Piosenkarze (6)**: Krzysztof Cugowski, Jan i Sylwia Dąbrowscy, Norbert Dudziuk (Norbi), Katarzyna Kowalska, Dawid Podsiadło, Maryla Rodowicz

**Influencerzy (6)**: Faustyna Fugińska, Karol Gazwa (Blowek), Kamil Labudda (Budda), Marlena Sojka, Weronika Sowa (Wersow), Karol Wiśniewski (Friz)

**Aktorzy (6)**: Janusz Gajos, Robert Górski, Marek Kondrat, Cezary Pazura, Andrzej Seweryn, Jerzy Stuhr

**Lekarze (5)**: Krzysztof Bielecki, Anna Kowalska, Tomasz Matuszewski, Tomasz Mazur, Tomasz Wojciechowski

**Inni (5)**: Jerzy Kalibabka, Simon Leviev, Marek Skoczylas, Zygmunt Szweykowski, Tomasz Wrzeszczyński

