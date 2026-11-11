# AnalystDesk — Phase 8B proposed development relevance labels

**Status: AI-assisted draft; independent human relevance review is still required.**

This proposal is derived from the uploaded `10k_passages.jsonl` SEC Item 1A corpus and the eight frozen development prompts, **not** inferred from retriever ranking or queue inclusion. The full corpus (41 MSFT and 60 GOOGL Item 1A passages, including table-of-contents fragments) was screened for directly on-topic risk disclosures. The final human reviewer should inspect the complete cited passage text and may add/remove IDs before attestation.

- Corpus SHA-256: `ac3259063a7cfee9160d0f4a6e8a118335db6bca60d6fd8113dc2367dc5bade7` (matches blinded queue)
- Label criterion: a substantive disclosure directly relating to either named risk theme; incidental keyword mentions alone are excluded. These are *relevance references*, not assumed exhaustive coverage of every borderline source.
- Some references were found **outside the blinded retrieved candidate pool**; they remain eligible gold references and help avoid ranking-driven labels.
- The draft label JSONL deliberately sets `reviewed_against_corpus: false` and cannot be scored as human-attested gold until approved.

## Summary

| Case | Scope | Reference passages proposed | From blinded pool | Outside pool |
|---|---|---:|---:|---:|
| RET001 | MSFT, Item 1A | 13 | 5 | 8 |
| RET002 | MSFT, Item 1A | 10 | 6 | 4 |
| RET003 | MSFT, Item 1A | 11 | 4 | 7 |
| RET004 | MSFT, Item 1A | 5 | 2 | 3 |
| RET017 | GOOGL, Item 1A | 13 | 7 | 6 |
| RET018 | GOOGL, Item 1A | 17 | 6 | 11 |
| RET019 | GOOGL, Item 1A | 13 | 4 | 9 |
| RET020 | GOOGL, Item 1A | 8 | 4 | 4 |

## Case-by-case review

### RET001

**Question:** Locate passages in MSFT fiscal-year 2026-06-30 10-K Item 1A discussing cybersecurity and data privacy risk disclosures.

**Rationale:** Direct Item 1A descriptions of cyber incidents, defensive controls, personal-data exposure, data collection/protection and associated cybersecurity/privacy compliance risk.

**Review note:** Primary evidence: 00011 (cybersecurity section), 00019 (personal-data misuse), 00031 (cyber/privacy regulation). Borderline: 00020 (unauthorized scraping and information use); 00022 (AI-related data privacy).

| Passage ID | Source evidence excerpt | In blind candidate pool? |
|---|---|---|
| `MSFT_2026-06-30_Item1A_00011` | CYBERSECURITY, DATA PRIVACY, AND PLATFORM ABUSE RISKS Cyberattacks and security vulnerabilities could lead to reduced revenue, increased costs, liability claims, or harm to our reputation or competitive position. Security of our inform… | Yes |
| `MSFT_2026-06-30_Item1A_00012` | Commission on January 19, 2024 and amended on March 8, 2024, beginning in late November 2023, a nation-state associated threat actor used a password spray attack to compromise a legacy test account and, in turn, gain access to Microsof… | Yes |
| `MSFT_2026-06-30_Item1A_00013` | Cyberthreats are constantly evolving and becoming increasingly sophisticated and complex, increasing the difficulty of preventing, detecting and successfully defending against them. Threat actors also utilize emerging technologies such… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00014` | services. Our internal environment continues to evolve. Often, we are early adopters of new devices and technologies. We embrace new ways of sharing data and communicating internally and with partners and customers using methods such a… | Yes |
| `MSFT_2026-06-30_Item1A_00015` | The security of our products and services is important in our customers’ decisions to purchase or use our products or services across cloud and on-premises environments. Security threats are a significant challenge to companies like us… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00016` | products have and may continue to contain vulnerabilities or undetected errors. Our customers operate complex systems with third-party hardware and software from multiple vendors that may include systems acquired over many years. They … | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00017` | Any of the foregoing events could result in reputational harm, loss of revenue, increased costs, or otherwise adversely affect our business, financial condition, and results of operations. Development and deployment of defensive measur… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00018` | The cost of these measures to protect products and customer-facing services could reduce our operating margins. If we fail to do these things well, actual or perceived security vulnerabilities in our processes, products, and services, … | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00019` | Disclosure and misuse of personal data could result in liability and harm our reputation. As we continue to grow the number, breadth, and scale of our cloud-based offerings, we store and process increasingly large amounts of personal d… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00020` | We may not be able to protect information in our products and services from use by others . LinkedIn and other Microsoft products and services contain valuable information and content protected by contractual restrictions or technical … | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00022` | Issues in the development, deployment, and use of AI may result in reputational or competitive harm or liability . We are providing access to AI across our offerings and enabling customers and partners to build AI-based solutions using… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00028` | We are subject to a variety of new, existing, and evolving legal and regulatory requirements that could adversely affect our results of operations. We are subject to a wide range of laws, regulations, and legal requirements in the U.S.… | Yes |
| `MSFT_2026-06-30_Item1A_00031` | Cybersecurity: Legislative and regulatory actions related to cybersecurity may increase the costs associated with developing, implementing, or securing our products and services. The legal and regulatory environment in this area is com… | Yes |

**Human review:** Accept / Edit IDs / Reject (circle or annotate).


### RET002

**Question:** Locate passages in MSFT fiscal-year 2026-06-30 10-K Item 1A discussing government regulation and litigation risk factors.

**Rationale:** Direct Item 1A treatment of legal/regulatory obligations, antitrust, trade controls, data protection, ESG, tax disputes, intellectual-property litigation or related enforcement.

**Review note:** Primary: 00028 (broad legal exposure), 00029 (antitrust), 00033 (lawsuits). 00034–00036 add tax and IP litigation. Exclude incidental legal references in general operational risks.

| Passage ID | Source evidence excerpt | In blind candidate pool? |
|---|---|---|
| `MSFT_2026-06-30_Item1A_00022` | Issues in the development, deployment, and use of AI may result in reputational or competitive harm or liability . We are providing access to AI across our offerings and enabling customers and partners to build AI-based solutions using… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00028` | We are subject to a variety of new, existing, and evolving legal and regulatory requirements that could adversely affect our results of operations. We are subject to a wide range of laws, regulations, and legal requirements in the U.S.… | Yes |
| `MSFT_2026-06-30_Item1A_00029` | Competition laws and new market regulation: Government agencies closely scrutinize us under U.S. and foreign competition laws. Governments are actively enforcing competition laws and regulations and enacting new regulations to interven… | Yes |
| `MSFT_2026-06-30_Item1A_00030` | Trade: Increasing trade laws, policies, sanctions, and other regulatory requirements also affect our operations in and outside the U.S. relating to trade and investment. Economic sanctions in the U.S., the EU, and other countries could… | Yes |
| `MSFT_2026-06-30_Item1A_00031` | Cybersecurity: Legislative and regulatory actions related to cybersecurity may increase the costs associated with developing, implementing, or securing our products and services. The legal and regulatory environment in this area is com… | Yes |
| `MSFT_2026-06-30_Item1A_00032` | Environmental, Social, and Governance: Laws, regulations, and policies relating to environmental, social, and governance matters are being developed and formalized in Europe, the U.S., and elsewhere, which may include greenhouse gas em… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00033` | We have claims and lawsuits against us that may result in adverse outcomes. We are subject to a variety of claims and lawsuits. These claims may arise from a wide variety of business practices and initiatives, including major new produ… | Yes |
| `MSFT_2026-06-30_Item1A_00034` | We may have additional tax liabilities. We are subject to income taxes in the U.S. and many foreign jurisdictions. Significant judgment is required in determining our worldwide provision for income taxes. In the course of our business,… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00035` | We earn a significant amount of our operating income outside the U.S. A change in the mix of earnings and losses in countries with differing statutory tax rates, changes in our business or structure, or the expiration of or disputes ab… | Yes |
| `MSFT_2026-06-30_Item1A_00036` | Third parties may claim that we infringe their intellectual property. From time to time, others claim we infringe their intellectual property rights, including current copyright infringement and other claims arising from AI training, i… | No — found in full corpus |

**Human review:** Accept / Edit IDs / Reject (circle or annotate).


### RET003

**Question:** Locate passages in MSFT fiscal-year 2026-06-30 10-K Item 1A discussing competition and market disruption risks.

**Rationale:** Direct Item 1A descriptions of platform, cloud/AI and product competition, shifting market demand, technology change and related competitive supply or macroeconomic disruption.

**Review note:** Primary: 00001–00004 (platform/software competition), 00005–00009 (cloud/AI markets), 00037 (economic disruption). 00025 concerns competition for component supply.

| Passage ID | Source evidence excerpt | In blind candidate pool? |
|---|---|---|
| `MSFT_2026-06-30_Item1A_00001` | Our operations and financial results are subject to various risks and uncertainties, including those described below, that could adversely affect our business, operations, financial condition, results of operations, liquidity, and the … | Yes |
| `MSFT_2026-06-30_Item1A_00002` | A competing vertically-integrated model, in which a single firm controls the hardware and software elements of a product and related services, has succeeded with some consumer products such as PCs, tablets, smartphones, gaming consoles… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00003` | Competing platforms have content and application marketplaces with scale and significant installed bases. The variety and utility of content and applications available on a platform are important to device purchasing decisions. Users m… | Yes |
| `MSFT_2026-06-30_Item1A_00004` | Even as we transition more of our business to infrastructure-, platform-, and software-as-a-service business models, the license-based proprietary software model generates a substantial portion of our software revenue. We bear the cost… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00005` | Our cloud and AI strategy requires substantial investments and depends on evolving customer demand, technological developments, competitive dynamics, and regulatory conditions, any of which could adversely affect our business, financia… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00006` | Demand for cloud-based and AI products and services is evolving and difficult to forecast. Overestimation of demand or misalignment of capacity investments may result in underutilization of infrastructure and may lead to impairment of … | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00007` | Our success depends on our ability to develop, deliver, and maintain competitive cloud-based and AI products and services that achieve broad customer adoption and sustainable revenue growth. Our ability to succeed depends on our abilit… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00008` | Our success depends on our ability to execute effectively across product development, go-to-market, customer acquisition, and customer retention initiatives. Failure to do so could reduce adoption, market share, and revenue growth. If … | Yes |
| `MSFT_2026-06-30_Item1A_00009` | We make significant investments in products and services that may not achieve expected returns. We will continue to make significant investments in research, development, and marketing for existing products, services, and technologies,… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00025` | We may experience supply problems. There are limited suppliers for certain critical device and datacenter components, and those items are in short supply. We continue to identify and evaluate opportunities to expand our datacenter loca… | Yes |
| `MSFT_2026-06-30_Item1A_00037` | Social media may increase the likelihood, speed, and magnitude of negative brand events. If our brands or reputation are damaged, it could adversely affect our business, results of operations, or ability to attract the most highly qual… | No — found in full corpus |

**Human review:** Accept / Edit IDs / Reject (circle or annotate).


### RET004

**Question:** Locate passages in MSFT fiscal-year 2026-06-30 10-K Item 1A discussing intellectual property and licensing risks.

**Rationale:** Direct Item 1A discussion of software licensing dependence, protection of proprietary information, intellectual-property rights, infringement claims and licensing/remedy exposure.

**Review note:** Primary: 00004 (licensing-based model), 00035 (IP rights/unlicensed copying), 00036 (IP infringement and royalty/data licensing). 00020 covers controlled content; 00022 covers AI IP exposure.

| Passage ID | Source evidence excerpt | In blind candidate pool? |
|---|---|---|
| `MSFT_2026-06-30_Item1A_00004` | Even as we transition more of our business to infrastructure-, platform-, and software-as-a-service business models, the license-based proprietary software model generates a substantial portion of our software revenue. We bear the cost… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00020` | We may not be able to protect information in our products and services from use by others . LinkedIn and other Microsoft products and services contain valuable information and content protected by contractual restrictions or technical … | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00022` | Issues in the development, deployment, and use of AI may result in reputational or competitive harm or liability . We are providing access to AI across our offerings and enabling customers and partners to build AI-based solutions using… | No — found in full corpus |
| `MSFT_2026-06-30_Item1A_00035` | We earn a significant amount of our operating income outside the U.S. A change in the mix of earnings and losses in countries with differing statutory tax rates, changes in our business or structure, or the expiration of or disputes ab… | Yes |
| `MSFT_2026-06-30_Item1A_00036` | Third parties may claim that we infringe their intellectual property. From time to time, others claim we infringe their intellectual property rights, including current copyright infringement and other claims arising from AI training, i… | Yes |

**Human review:** Accept / Edit IDs / Reject (circle or annotate).


### RET017

**Question:** Locate passages in GOOGL fiscal-year 2025-12-31 10-K Item 1A discussing cybersecurity and data privacy risk disclosures.

**Rationale:** Direct Item 1A discussion of cyber attacks, sensitive-data disclosure, security vulnerabilities, user-data privacy, digital-platform abuse and associated privacy regulation.

**Review note:** Primary: 00027–00032 (breaches/attacks), 00026 (privacy concerns), 00047 (privacy law). 00013 and 00022 are broader reputation/AI risk passages but directly name privacy and security.

| Passage ID | Source evidence excerpt | In blind candidate pool? |
|---|---|---|
| `GOOGL_2025-12-31_Item1A_00013` | new and innovative products and services that better serve the needs of our users, advertisers, customers, content providers, and other partners. Our brands have been, and may in the future be, harmed by a number of factors, including,… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00017` | Interruption to, interference with, or failure of our complex information technology and communications systems could hurt our ability to effectively provide our products and services, which could harm our reputation, financial conditi… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00022` | Our evolving AI-enabled products and services may give rise to risks related to harmful content, inaccuracies, discrimination, intellectual property infringement or misappropriation, violation of rights of publicity, defamation, data p… | Yes |
| `GOOGL_2025-12-31_Item1A_00025` | significantly in efforts to promote high-quality and relevant results and to detect and prevent low-quality content and invalid traffic, we have been unable and may continue to be unable to detect and prevent all such abuses or promote… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00026` | If we fail to either detect and prevent an increase in problematic content or effectively promote high-quality content, it could hurt our reputation for delivering relevant information or reduce use of our platforms, harming our financ… | Yes |
| `GOOGL_2025-12-31_Item1A_00027` | Our products and services involve the storage, handling, and transmission of proprietary and other sensitive information. Malicious software such as viruses, software bugs, theft, misuse, defects, vulnerabilities in our products and se… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00028` | We experience cyber attacks and other attempts to gain unauthorized access to our systems on a regular basis. Cyber attacks continue to evolve in sophistication and volume, and inherently may be difficult to detect for long periods of … | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00030` | and other critical infrastructure, which could affect our or other parties' systems. We expect to continue to experience such incidents or vulnerabilities in the future. Our efforts to prevent security incidents and address undesirable… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00031` | Further, if any partners with whom we share user or other customer information fail to implement adequate data-security practices, fail to comply with our terms and policies, or otherwise suffer a network or other security breach, our … | Yes |
| `GOOGL_2025-12-31_Item1A_00032` | In addition to our efforts to prevent and mitigate cyber attacks, we are making significant investments in safety, security, and review efforts to combat misuse of our services and unauthorized access to user data by third parties, inc… | Yes |
| `GOOGL_2025-12-31_Item1A_00038` | • Data privacy, collection, processing, and portability: Laws and regulations further restricting the collection, processing, or sharing of user or advertising-related data, including privacy and data protection laws; laws affecting th… | Yes |
| `GOOGL_2025-12-31_Item1A_00046` | of data protection laws, imposing specific obligations with respect to the processing of personal data, including required notices, consents, and opt-outs. Further, the increased risk of inadvertent disclosure of confidential informati… | Yes |
| `GOOGL_2025-12-31_Item1A_00047` | • Various US federal, US state, and foreign privacy laws related to the processing and security of personal data, including (1) comprehensive privacy laws that provide data privacy rights (including, in California, a private right of a… | Yes |

**Human review:** Accept / Edit IDs / Reject (circle or annotate).


### RET018

**Question:** Locate passages in GOOGL fiscal-year 2025-12-31 10-K Item 1A discussing government regulation and litigation risk factors.

**Rationale:** Direct Item 1A disclosures about regulatory obligations, government proceedings, antitrust, privacy enforcement, material litigation, tax disputes and acquisition approvals.

**Review note:** Primary: 00035–00040 (law/regulation), 00042–00044 (antitrust and litigation), 00046–00047 (privacy obligations). 00051 tax disputes and 00056/00058 acquisition regulation are narrower.

| Passage ID | Source evidence excerpt | In blind candidate pool? |
|---|---|---|
| `GOOGL_2025-12-31_Item1A_00022` | Our evolving AI-enabled products and services may give rise to risks related to harmful content, inaccuracies, discrimination, intellectual property infringement or misappropriation, violation of rights of publicity, defamation, data p… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00026` | If we fail to either detect and prevent an increase in problematic content or effectively promote high-quality content, it could hurt our reputation for delivering relevant information or reduce use of our platforms, harming our financ… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00034` | regulatory inquiries, which could result in monetary penalties and damages, divert management's time and attention, and lead to enhanced regulatory oversight. Our business depends on continued and unimpeded access to the Internet by us… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00035` | We are subject to numerous US federal and state as well as foreign laws and regulations covering a wide variety of subjects, and our introduction of new businesses, products, services, and technologies will likely continue to subject u… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00036` | • AI: Laws and regulations focused on the development, use, and provision of AI technologies and other digital products and services, which could result in monetary penalties or other regulatory actions. For example, the EU AI Act came… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00038` | • Data privacy, collection, processing, and portability: Laws and regulations further restricting the collection, processing, or sharing of user or advertising-related data, including privacy and data protection laws; laws affecting th… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00039` | In addition, the applicability and scope of these and other laws and regulations, as interpreted by courts, regulators, or administrative bodies, remain uncertain and could be interpreted in ways that harm our business. For example, we… | Yes |
| `GOOGL_2025-12-31_Item1A_00040` | We are subject to claims, lawsuits, regulatory and government inquiries and investigations, other proceedings, and orders involving competition, intellectual property, data privacy and security, tax and related compliance, labor and em… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00042` | For example, the DOJ and a number of state Attorneys General filed a lawsuit concerning our Search and Search advertising practices and our compliance with US antitrust laws. In August 2024, the US District Court for the District of Co… | Yes |
| `GOOGL_2025-12-31_Item1A_00043` | In addition to these regulatory proceedings, private individual and collective actions that overlap with claims pursued by regulators are pending in the US and in several other jurisdictions. Adverse results in these or similar future … | Yes |
| `GOOGL_2025-12-31_Item1A_00044` | Estimating liabilities for our pending proceedings is a complex, fact-specific, and speculative process that requires significant judgment, and the amounts we are ultimately liable for may differ from our estimates. The resolution of o… | Yes |
| `GOOGL_2025-12-31_Item1A_00046` | of data protection laws, imposing specific obligations with respect to the processing of personal data, including required notices, consents, and opt-outs. Further, the increased risk of inadvertent disclosure of confidential informati… | Yes |
| `GOOGL_2025-12-31_Item1A_00047` | • Various US federal, US state, and foreign privacy laws related to the processing and security of personal data, including (1) comprehensive privacy laws that provide data privacy rights (including, in California, a private right of a… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00048` | We face, and may continue to face, intellectual property infringement or misappropriation, violation of rights of publicity, and other claims that could be costly to defend, result in significant damage awards or other costs (including… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00051` | We are subject to regular review and audit by both domestic and foreign tax authorities. As a result, we have received, and may in the future receive, assessments in multiple jurisdictions, on various tax-related assertions, such as tr… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00056` | Acquisitions, joint ventures, investments, and divestitures are important elements of our overall corporate strategy and use of capital, and these transactions could be material to our financial condition and operating results. We expe… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00058` | realize the expected financial or strategic goals of a transaction; or investigations or litigation by governmental authorities related to our acquisitions, investments, and other strategic arrangements; • failure to successfully integ… | Yes |

**Human review:** Accept / Edit IDs / Reject (circle or annotate).


### RET019

**Question:** Locate passages in GOOGL fiscal-year 2025-12-31 10-K Item 1A discussing competition and market disruption risks.

**Rationale:** Direct Item 1A discussion of competitive pressures, evolving advertising and AI markets, product/device rivalry, demand shifts and market or supply-chain disruption.

**Review note:** Primary: 00001 (advertising shift), 00005–00009 (product/AI competition), 00010 (margin pressures), 00023 (channel/platform shifts). 00014/00015 concern supply exposure and competition for scarce components.

| Passage ID | Source evidence excerpt | In blind candidate pool? |
|---|---|---|
| `GOOGL_2025-12-31_Item1A_00001` | Our operations and financial results are subject to various risks and uncertainties, including but not limited to those described below, which could harm our business, reputation, financial condition, and operating results, and may aff… | Yes |
| `GOOGL_2025-12-31_Item1A_00002` | Expenditures by advertisers tend to correlate with overall economic conditions. Adverse macroeconomic conditions have affected, and may in the future affect, the demand for advertising, resulting in fluctuations in the amounts our adve… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00003` | We have invested and expect to significantly expand our investment in property and equipment, including our technical infrastructure, and we expect these assets to benefit our business over their estimated useful lives. Changes in fact… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00005` | Within Google Services, we continue to invest heavily in devices, including our smartphones, home devices, and wearables, which is a highly competitive market with frequent introduction of new products and services, rapid adoption of t… | Yes |
| `GOOGL_2025-12-31_Item1A_00006` | Within Other Bets, we are investing significantly in areas such as life sciences and transportation, among others. These investment areas face intense competition from large, experienced, and well-funded competitors, and our offerings,… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00007` | We have many competitors in different industries. Our current and potential domestic and international competitors range from large and established companies to emerging start-ups. Some competitors have longer operating histories and w… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00009` | AI products and technologies that are similar or superior to our technologies or more cost-effective to develop or deploy. Other companies may also have (or in the future may obtain) patents or other proprietary rights that would preve… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00010` | We may experience downward pressure on our operating margin resulting from a variety of factors. These include increasing costs for many aspects of our business resulting from a higher level of investment in technical infrastructure, i… | Yes |
| `GOOGL_2025-12-31_Item1A_00014` | We have experienced and may in the future experience supply shortages, price increases, quality issues, or longer lead times that could harm our operations, driven by raw material or component availability, manufacturing capacity, labo… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00015` | We may enter into long-term contracts for materials and products that commit us to significant terms and conditions. We may face costs for materials and products that are not consumed due to market demand, technological change, excess … | Yes |
| `GOOGL_2025-12-31_Item1A_00023` | While the modalities used to access information is evolving, people access our products and services through a growing variety of devices such as phones, laptops and tablets, video game consoles, voice-activated speakers, wearables (in… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00025` | significantly in efforts to promote high-quality and relevant results and to detect and prevent low-quality content and invalid traffic, we have been unable and may continue to be unable to detect and prevent all such abuses or promote… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00034` | regulatory inquiries, which could result in monetary penalties and damages, divert management's time and attention, and lead to enhanced regulatory oversight. Our business depends on continued and unimpeded access to the Internet by us… | No — found in full corpus |

**Human review:** Accept / Edit IDs / Reject (circle or annotate).


### RET020

**Question:** Locate passages in GOOGL fiscal-year 2025-12-31 10-K Item 1A discussing intellectual property and licensing risks.

**Rationale:** Direct Item 1A discussion of trade secrets, trademark/patent/copyright exposure, intellectual-property lawsuits, safe-harbor liability and indemnity/licensing risks.

**Review note:** Primary: 00011 (trade secrets/trademark), 00048 (infringement claims), 00050 (indemnities). 00038–00039 are copyright/safe-harbor rules; 00009 is patent limits on AI.

| Passage ID | Source evidence excerpt | In blind candidate pool? |
|---|---|---|
| `GOOGL_2025-12-31_Item1A_00009` | AI products and technologies that are similar or superior to our technologies or more cost-effective to develop or deploy. Other companies may also have (or in the future may obtain) patents or other proprietary rights that would preve… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00011` | We also seek to maintain certain intellectual property as trade secrets. The confidentiality of such trade secrets and other sensitive information could be compromised, which could cause us to lose the competitive advantage resulting f… | Yes |
| `GOOGL_2025-12-31_Item1A_00022` | Our evolving AI-enabled products and services may give rise to risks related to harmful content, inaccuracies, discrimination, intellectual property infringement or misappropriation, violation of rights of publicity, defamation, data p… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00038` | • Data privacy, collection, processing, and portability: Laws and regulations further restricting the collection, processing, or sharing of user or advertising-related data, including privacy and data protection laws; laws affecting th… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00039` | In addition, the applicability and scope of these and other laws and regulations, as interpreted by courts, regulators, or administrative bodies, remain uncertain and could be interpreted in ways that harm our business. For example, we… | No — found in full corpus |
| `GOOGL_2025-12-31_Item1A_00040` | We are subject to claims, lawsuits, regulatory and government inquiries and investigations, other proceedings, and orders involving competition, intellectual property, data privacy and security, tax and related compliance, labor and em… | Yes |
| `GOOGL_2025-12-31_Item1A_00048` | We face, and may continue to face, intellectual property infringement or misappropriation, violation of rights of publicity, and other claims that could be costly to defend, result in significant damage awards or other costs (including… | Yes |
| `GOOGL_2025-12-31_Item1A_00050` | result in loss of revenues and harm our business. Moreover, intellectual property indemnities provided to us by our suppliers, when obtainable, may not cover all damages and losses suffered by us and our customers arising from intellec… | Yes |

**Human review:** Accept / Edit IDs / Reject (circle or annotate).


## How to approve after actually reading the SEC passages

1. Check all proposed IDs against the full `data\parsed\10k_passages.jsonl` and their exact question; edit the `relevant_passage_ids` arrays in `evaluation\retrieval_labels_dev_v1.PROPOSED.jsonl` as needed.
2. Confirm no case has relevant passages missing from the source corpus (if uncertain, mark review unresolved).
3. Run `python evaluation\finalize_phase8b_labels.py --reviewer your_reviewer_id --attest-reviewed`. **Do not run until you have reviewed the eight sets**. This creates `evaluation\retrieval_labels_dev_v1.jsonl` and does not overwrite it.
4. Use the standard Phase 8B score command, and report results as *eight development cases using human-reviewed reference passages*, not held-out accuracy or exhaustive recall.

The helper verifies case IDs, scope, corpus SHA-256, passage IDs and a required explicit reviewer attestation. An attestation flag cannot technically prove a person reviewed the content; the reviewer retains responsibility.

## Important limitations

- SEC excerpts shown here are shortened for convenience; the scorer references complete corpus passage IDs.
- Some passages span distinct risks or cross page boundaries; the reviewer should verify that any included passage *substantively* addresses the prompt.
- Because the queries are broad and multiple passages may apply, Hit@5 and MRR@5 are often more interpretable than reference recall at five, which depends on the completeness and breadth of this reference set.
- No metrics are claimed from these draft labels, and no held-out cases have been annotated.
