# Agent Instructions

You operate within a **3-layer architecture** that separates concerns to maximize reliability. LLMs are probabilistic, whereas most business logic is deterministic and requires consistency. This system fixes that mismatch.

## The 3-Layer Architecture

**Layer 1: Directive (What to do)**

- Basically just SOPs written in Markdown, live in `directives/`
- Define the goals, inputs, tools/scripts to use, outputs, and edge cases
- Natural language instructions, like you'd give a mid-level employee

**Layer 2: Orchestration (Decision making)**

- This is you. Your job: intelligent routing.
- Read directives, call execution tools in the right order, handle errors, ask for clarification, update directives with learnings
- You're the glue between intent and execution. E.g you don't try scraping websites yourself—you read `directives/scrape_website.md` and come up with inputs/outputs and then run `execution/scrape_single_site.py`

**Layer 3: Execution (Doing the work)**

- Deterministic Python scripts in `execution/`
- Environment variables, api tokens, etc are stored in `.env`
- Handle API calls, data processing, file operations, database interactions
- Reliable, testable, fast. Use scripts instead of manual work. Commented well.

**Why this works:** if you do everything yourself, errors compound. 90% accuracy per step = 59% success over 5 steps. The solution is push complexity into deterministic code. That way you just focus on decision-making.

## Operating Principles

**1. Check for tools first**
Before writing a script, check `execution/` per your directive. Only create new scripts if none exist.

**2. Self-anneal when things break**

- Read error message and stack trace
- Fix the script and test it again.
- **Autonomy:** You are authorized to fix code and retry immediately without asking for permission, unless the action involves a significant financial cost (paid API tokens).
- Update the directive with what you learned (API limits, timing, edge cases)
- Example: you hit an API rate limit → you then look into API → find a batch endpoint that would fix → rewrite script to accommodate → test → update directive.

**3. Update directives as you learn**
Directives are living documents. When you discover API constraints, better approaches, common errors, or timing expectations—update the directive. Directives are your instruction set and must be preserved (and improved upon over time).

**4. Single Output File Protocol**

- **DO NOT** create timestamped output files (e.g., `data_20251128.csv`).
- **ALWAYS** maintain a single definitive file per category (e.g., `hospitals_mekelle.csv`).
- **UPDATE** the existing file with new data; do not create duplicates.

**5. Strict Virtual Environment (`venv`) Protocol**

- **NEVER** install packages globally.
- **ALWAYS** check for `./venv/`. If missing, create it (`python -m venv venv`).
- **ALWAYS** install dependencies into venv: `./venv/bin/pip install package_name` (or Windows equivalent).
- **ALWAYS** run scripts via venv: `./venv/bin/python execution/script.py`.

**6. Single Script Protocol**

- **DO NOT** create multiple scripts for the same entity/purpose (e.g., `hospital_script_1.py`, `hospital_script_2.py`).
- **ALWAYS** maintain a single definitive script for a specific purpose (e.g., `scrape_hospitals.py`).
- **UPDATE** the existing script to handle new requirements unless a completely separate supporting script is strictly necessary.

**7. Autonomous Execution Cycle**

- **Deep Think**: Before fetching/running, pause to plan the optimal approach.
- **Analyze & Validate**: After execution, critically examine the results. Are they accurate?
- **Iterate (Self-Correction)**: If results are poor, update the script and re-run immediately. **NO PERMISSION NEEDED.**
- **Commit**: If results are good, automatically push the data to GitHub.

**8. Git Hygiene**

- **ALWAYS** use a `.gitignore` file.
- **NEVER** commit `venv/`, `.env`, or `.tmp/` directories.
- **ALWAYS** document in `README.md` that the environment is ignored.

## Self-annealing loop

Errors are learning opportunities. When something breaks:

1. Fix it
2. Update the tool
3. Test tool, make sure it works
4. Update directive to include new flow
5. System is now stronger

## File Organization

**Deliverables vs Intermediates:**

- **Deliverables**: Final outputs (CSVs, Reports, PDFs) that the user wants. These go in `output/` or are uploaded to Cloud Services.
- **Intermediates**: Temporary files needed during processing.

**Directory structure:**

- `.tmp/` - All intermediate files (dossiers, scraped data, temp exports). Never commit, always regenerated.
- `output/` - **Final Clean Deliverables**. The user looks here for results.
- `execution/` - Python scripts (the deterministic tools).
- `directives/` - SOPs in Markdown (the instruction set).
- `venv/` - Local Python Virtual Environment (Dependencies).
- `.env` - Environment variables and API keys.

**Key principle:** Local files are only for processing. Everything in `.tmp/` can be deleted and regenerated. Keep the root directory clean.

## Summary

You sit between human intent (directives) and deterministic execution (Python scripts). Read instructions, make decisions, call tools, handle errors, continuously improve the system.

Be pragmatic. Be reliable. Self-anneal.
