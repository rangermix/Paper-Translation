# Extraction acceleration implementation plan

**Goal:** Default new extraction jobs to PaddleOCR-VL-1.6 and support explicit CPU, NVIDIA CUDA and Apple MLX deployment modes.

**Architecture:** Keep existing PDF inspection, layout, IR adaptation, recovery and fenced spool. CUDA runs inside the parser container. MLX uses Compose models and Docker Model Runner/vLLM Metal for Paddle VLM regions; layout and other parser profiles remain CPU in this mode. Only the MLX override gives the parser access to Docker Model Runner. No standalone native host service is permitted. All weights stay pinned and installed before serving. New preferences default to Paddle; legacy jobs without a profile remain Docling and saved choices are preserved.

**Tech stack:** Existing Docling/PaddleOCR, PyTorch/Paddle CUDA distributions, Docker Model Runner/vLLM Metal, Docker Compose overrides, Python/React.

## Alternatives considered

1. Recommended: Compose CPU/CUDA parser plus Docker-managed MLX inference. Preserves the established pipeline and container resource controls.
2. Move the entire parser to macOS: would lose the existing Linux cgroup isolation and require a second full dependency stack.
3. MLX inside Linux Docker: does not provide Apple Metal access.

## Tasks and verification

1. Add regression tests for new defaults, saved preferences and legacy spool behavior in tests/unit/test_parser_profiles.py and tests/integration/test_parser_profile_settings.py. Implement separate new-preference and historical selection functions; update UI fallbacks.
2. Add tests/unit/test_parser_acceleration.py for explicit accelerator validation, device availability, pipeline options/fingerprints and runtime identity. Add src/packages/parsers/runtime.py and wire both parsers and progress reporting.
3. Add Compose-managed MLX through Docker Model Runner with fixed vLLM endpoint and content-addressed model selection. Validate local model metadata before inference. Provide a Compose build helper for exporting verified weights for OCI packaging.
4. Add CUDA dependency lock/image build target and CUDA/MLX Compose overrides. Keep standard CPU deployment network-isolated. Model download remains build/setup-only.
5. Update deployment docs and the baseline with the Compose-only hardware configuration. Run relevant parser tests, frontend tests/build and available Compose/DMR checks. Report unavailable CUDA/Docker integration honestly; do not use previous delivery evidence as verification.

No production configuration, credentials, historical jobs or published artifacts are changed by this implementation. Test output goes to .agent/tmp/extraction-20260909/ and persistent test environments to .agent/local-data/extraction-20260909/.
