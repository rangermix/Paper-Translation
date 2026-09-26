# Translation preparation: options and runtime cost

This catalogue consolidates the design discussion as of 2026-09-26. Options are
alternatives or extensions, not a requirement to run every method on every paper.
The [specification](2026-09-26-translation-consistency-design.md) defines delivery
scope. Model cards and service terms describe upstream capabilities, not local
installation, deployment or translation-quality acceptance.

## Context collection and summaries

| Option | Role | Cost / limitations | Delivery choice |
| --- | --- | --- | --- |
| Author abstract only | Minimal document overview | No extra inference; can omit qualifications and terminology | Included in extraction |
| Structured source extracts | Abstract, contributions, headings, conclusion, definitions, captions, notation | CPU scanning; source quality limits coverage | Default |
| Lexical passage retrieval | Select original evidence for a term or unit | Cheap, deterministic; weak for unseen synonyms | Default matching and ranking |
| Embedding retrieval | Find semantically related passages | Small encoder, weights/index storage, language-specific evaluation | Optional extension |
| Existing external abstracts | Crossref/arXiv | Identity/version checks; include only useful differences from local abstract | Connector extension |
| Semantic Scholar TLDR | Additional short generated overview | Incomplete coverage; not author evidence | Connector extension |
| OpenAlex abstract | Reconstructed abstract from inverted index | Usually duplicates author abstract; not generated summary | Alternative connector |
| OpenReview author TLDR | Author-written short account where available | Paper/version matching; absence is normal | Alternative connector |
| Author project pages, slides or publisher summaries | Supplementary explanations | Provenance/version checks; retrieval and reuse terms vary | Optional/manual evidence |
| Selected translation model | Contextual term translation; general models may generate a structured brief | No second model download; analyst capability must be separate from translation capability | Optional preparation backend |
| Small general local analyst | Structured brief, concept distinctions and glossary proposals | Extra weights, model loading, reasoning tokens and runtime support | One pinned backend in delivery; others are alternatives |
| Scientific summarizer | Scientific-paper summaries | May not follow glossary instructions or cover target languages | Benchmark alternative |
| Configured paid API | Structured analysis with evidence | Input/output fees and explicit egress authorization | Same-provider preparation first |
| Free API quota | Explicitly selected hosted analysis | Availability, limits, retention and model versions can change | Optional, never automatic fallback |
| Manual researcher brief | Correct domain context and consequential distinctions | Human time; optional | Possible extension |
| Hierarchical section analysis | Section briefs then reconciliation for long papers | More requests; repeated compression can lose distinctions | Later when bounded extraction is insufficient |
| Retrieval without generated summary | Supply original definitions on demand | Avoids summary errors; context packing still matters | Core approach |

Full-paper input and full-paper output are separate decisions. Retaining small,
stable output units makes editing, recovery and omission checks easier. A larger
coherent output batch can be tested independently. A single full-paper response
is not the default because output limits and retries affect the entire document.

## Local analyst and summarizer shortlist

| Candidate | Intended experiment | Evidence boundary |
| --- | --- | --- |
| [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | Multilingual structured brief and terminology | Advertised native context is not allocated MLX/DMR context |
| [LFM2.5-2.6B](https://huggingface.co/LiquidAI/LFM2.5-2.6B) | Source-grounded extraction and reconciliation | Always-reasoning behavior adds generation cost; do not substitute model recall for source evidence |
| [MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B) | Compact general analyst | Nominal name, quantization, actual memory and backend support require verification |
| [MiniCPM5-1B](https://huggingface.co/openbmb/MiniCPM5-1B) | Implemented Q4 analyst through the official MLX checkpoint | Reasoning disabled; structured-output contracts tested, downstream model quality still requires an authorized run |
| [LED-arXiv](https://huggingface.co/allenai/led-large-16384-arxiv) | Specialized English scientific summarization | 16,384 encoder positions; not general glossary instruction following |
| [PEGASUS-arXiv](https://huggingface.co/google/pegasus-arxiv/blob/main/config.json) | Specialized summary baseline | Published configuration has 1,024 positions; extraction/chunking needed |
| [LongT5](https://github.com/google-research/longt5) / multilingual variants | Long-input summarization | Choose a suitable task-tuned checkpoint; pretrained weights are not an installed analyst |
| [Hy-MT2](https://huggingface.co/tencent/Hy-MT2-1.8B) | Reuse selected translator for contextual term wording | Official terminology/background templates establish context consumption, not scientific-summary generation |

The initial local choice is MiniCPM5-1B Q4 (about 590 MiB of pinned files); see the
[runtime guide](../deployment/local-translation.md). This is a compact integration
choice, not a quality ranking over the other candidates. Add an alternative only after pinned artefact hashes,
licence, model identity, tokenizer/template and Docker Model Runner support have
been verified. Download only on explicit preparation/use, never while reading
settings. Separate analyst and translator may need sequential residency on a
16 GiB machine; raw 4-bit weights alone do not include KV cache or runtime memory.

## Term identification

| Method | Useful output | Limitation |
| --- | --- | --- |
| Author keyword/glossary/nomenclature lists | High-value candidates | May be missing or poorly parsed |
| Explicit definitions and acronym rules | Meaning evidence, expansions and scope | Language/pattern coverage varies |
| Repetition and phrase statistics | Ranked recurring expressions | Frequency is neither importance nor correctness; retain rare definitions |
| Linguistic noun-phrase extraction | Better candidate boundaries | Requires language/domain resources |
| [YAKE](https://github.com/INESCTEC/yake) | Local statistical keyphrases | Keyphrases still need concept/sense resolution |
| [scispaCy](https://github.com/allenai/scispacy#available-components) | Abbreviations and scientific-language components | Biomedical/language training is not universal paper support |
| [KeyBERT](https://maartengr.github.io/KeyBERT/) | Embedding-ranked phrases | An encoder ranks relevance, not bilingual accuracy |
| Small general LLM | Reconcile aliases, senses and consequential distinctions | Evidence validation, output caps and semantic evaluation required |
| Draft-translation comparison | Find variant renderings of repeated concepts | A frequent mistake must not win by majority vote |

## Pinning target wording

Use existing document/global glossary choices first. Explicitly reviewed
translation memory can provide usage evidence; whole-sentence review does not
automatically establish term alignment. Author bilingual abstracts, trusted
parallel translations and domain literature can provide additional candidates.

| Terminology source | Suitable coverage | Integration condition |
| --- | --- | --- |
| [CNCTST 术语在线](https://www.termonline.cn/about) | Chinese scientific terminology | Public lookup does not imply unrestricted automated/bulk API access |
| [UNTERM](https://unterm.un.org/) | UN institutional and related subject terminology | Match concept/domain; not comprehensive new ML vocabulary |
| [AGROVOC](https://aims.fao.org/standards/agrovoc/access-agrovoc) | Agriculture, food and related disciplines | Machine-readable access; check language-dataset licences |
| [IATE](https://www.cdt.europa.eu/en/iate) | EU terminology, 24 EU languages and some non-EU languages | Do not assume comprehensive Chinese science coverage |
| Wikidata / Wiktionary | Labels, aliases and lexical senses | Community suggestions; sense matching required |
| Contextual model translation | Proposed wording for unresolved concepts | Include original definitions and multiple occurrences; never mark human-reviewed |
| Optional user correction | Explicit preference for a paper/domain | Persist actual action and scope; no mandatory review gate |

Avoid blind global string replacement. A scoped concept may have several valid
surface forms, while identical source spelling may name different concepts.

## Online service alternatives

[Groq](https://console.groq.com/docs/rate-limits),
[Gemini](https://ai.google.dev/gemini-api/docs/pricing) and
[OpenRouter free variants](https://openrouter.ai/docs/guides/routing/model-variants/free)
are possible explicitly configured API destinations. A free quota is not a
runtime availability guarantee. Pin the destination/protocol/model and retain
the same accounting and unknown-outcome behavior. Do not select a random free
router model or silently switch services after a failure.

Consumer interfaces such as NotebookLM and research products such as Elicit can
provide manual context. A free website account does not establish a free or
permitted production API. Service-specific retention and terms must be evaluated
before content egress; for example see
[Gemini terms](https://ai.google.dev/gemini-api/terms) and
[Groq data controls](https://console.groq.com/docs/your-data).

Primary retrieval references:
[Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/),
[arXiv API](https://info.arxiv.org/help/api/user-manual.html),
[Semantic Scholar API](https://api.semanticscholar.org/api-docs/),
[OpenAlex works](https://help.openalex.org/data/works/attributes/),
[OpenReview submission fields](https://docs.openreview.net/reference/default-forms/default-submission-form).

## Runtime and cost model

Most stages do not require LLM output. Extract once, optionally reconcile once,
freeze the result, then retrieve relevant context deterministically. The implemented
flow makes zero additional requests in extractive/off mode and one bounded analysis
request in provider/local mode. It skips analysis when no units remain or no evidence
fits. Known unsent/unexecuted failures may retry; known unusable analysis falls back
without another content-repair request. Hierarchical analysis is an extension.

Let `Ain`/`Aout` be aggregate preparation tokens, `N` the number of translation
requests and `deltaC` the **net additional** input per request. With separate
analysis and translation prices per million tokens:

```text
extra API cost = (Ain * analysis_input_rate + Aout * analysis_output_rate
                 + N * deltaC * translation_input_rate) / 1,000,000
```

Count reasoning in generated tokens. This excludes baseline translation, parsing,
additional review, retries and infrastructure. Use actual configured prices;
unknown amounts stay null and free quotas must not be assumed.

Illustrative, unmeasured workload: `Ain=15,000`, `Aout=3,000`, `N=80`,
`deltaC=400`. That is 47,000 added input and 3,000 output tokens if the rates are
the same for preparation and translation. At hypothetical rates of USD 0.10/M
input and 0.40/M output, the increment is USD 0.0059 per paper. At USD 0.75/M
input and 3.75/M output it is USD 0.0465. These are arithmetic scenarios, not
current price promises or measured project costs.

For a local model:

```text
extra time ~= Ain / prefill_rate + Aout / decode_rate
              + N * deltaC / translation_prefill_rate + model load/switch time
```

Assuming 500 input tokens/s and 40 generated tokens/s gives 105 seconds of
preparation plus 64 seconds of repeated context, or about 169 seconds warm.
These speeds are assumptions, not measurements on the user's machine. Cold
downloads, runtime startup, KV cache, contention and context-dependent throughput
can dominate. Local inference has no hosted API charge but is not zero resource
cost. Extractive mode removes preparation generation, not repeated-context cost.

## Evaluation and later options

Compare off, extractive, same-provider and separate-local-analyst modes on the
same authorized PDFs and locales. Measure downstream concept/wording consistency,
sense errors, omissions, protected references, request count, input/output and
reasoning tokens, peak memory, cold/warm latency and total job time. Fluent
summaries, schema compliance and term-count recall alone are insufficient.

Evaluate specialized summarizers, embeddings and hierarchy only if the baseline
misses useful evidence. [SummN](https://aclanthology.org/2022.acl-long.112/) is
relevant split-and-reconcile research, not proof of this application's
translation quality. Training/distillation needs a reviewed corpus and belongs
after measured failures, not in the initial dependency chain.
