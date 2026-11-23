# Running this on SAP BTP - honest status

**Nothing in this repo has been run on SAP BTP.** The code was built and tested locally against a mock service. This page lists what a first real deployment involves so you can do it and then describe it truthfully.

## What works today (verified locally)
```bash
pip install -r requirements.txt
python -m pytest -q          # 28 tests
python -m evals.run_evals    # 43-case eval + red-team
uvicorn app.api:api          # POST /chat against the built-in mock
```

## Suggested path to real BTP exposure
1. **Get an account.** SAP offers a 90-day BTP trial and free-tier plans for some services; confirm current terms at sap.com/products/technology-platform/trial.html.
2. **Develop in SAP Business Application Studio.** Create a dev space, clone this repo, run the tests.
3. **Deploy to Cloud Foundry.** `cf push` with `manifest.yml` (python buildpack). Check `/health`, then `POST /chat`.
4. **Point it at a real OData service.** Set `S4_BASE_URL` (and token). Then **rewrite the entity/field mapping** in `agent/tools.py` - this repo's names (`A_MaterialStock`, `UnrestrictedStock`, ...) are simplified stand-ins, not SAP's real API schemas. Use SAP Business Accelerator Hub to find the actual APIs and sandbox endpoints.
5. **Use a BTP Destination** for credentials instead of environment variables.
6. **Swap the planner.** Implement `complete()` for a model you can reach (via SAP AI Core / generative AI hub, or any tool-calling API), pass it to `LLMPlanner`, run `python -m evals.run_evals --planner llm` (after replacing the `make_planner` stub), and compare tiers against the baseline.

## What you can honestly say afterwards
Only claim what you did: "deployed to Cloud Foundry on a BTP trial", "ran evals against model X", etc. If you only did steps 1-3, say that.
