# Hackathon Vibecoding & Git Playbook

This repository serves as the central source of truth for both human developers and AI coding agents. The goal is to maintain maximum momentum ("vibecoding") while strictly preventing merge conflicts, environment desyncs, and lost context.

## 1. The Zero-Friction Git Playbook

When speed is the priority, heavy Git workflows slow you down. Stick to this streamlined approach.

### Trunk-Based Development
* **`main` is Sacred:** Never write code directly on the `main` branch. It must always remain in a working, deployable state.
* **Feature Branches:** Branch off `main` for every new task. Use clear, scoped names (e.g., `feature/qt-ui-layout`, `feature/yolo-inference-pipeline`, `fix/memory-leak`).
* **Merge Quickly:** Once a feature works locally, merge it into `main` immediately. Long-running branches are the primary cause of merge conflicts.

### Merge Conflict Mitigation
* **Divide and Conquer by File/Architecture:** Structurally separate your work. If one developer is handling a C++ native backend or core algorithmic logic, the other should be strictly touching the frontend components or independent API scripts. *Do not edit the same files concurrently.*
* **Communicate Pushes:** Verbally (or via chat) announce when you are merging to `main`. 
* **Pull Frequently:** Run `git pull origin main` before starting any new branch and immediately after your teammate announces a merge.
* **Strict `.gitignore`:** Ensure heavy build directories (e.g., CMake caches, object files), virtual environments, and massive machine learning weights are ignored. Committing these will instantly bog down the repository.

---

## 2. Shared Task Management (`TODO.md`)

We use a flat `TODO.md` file in the root directory rather than heavy ticketing systems. 

**Format:**
* `[ ]` **Not Started:** Upcoming features or known bugs.
* `[~]` **In Progress:** Actively being worked on by a human or AI agent.
* `[x]` **Completed:** Done and merged.

**Inline Comments:**
Do not break your flow state to open the `TODO.md` file if you spot a minor issue while vibecoding. Drop an inline comment (e.g., `// TODO: offload this process to the GPU later` or `# FIXME: adjust bounding box threshold`) directly in the code. 

---

## 3. Instructions for AI Coding Agents

**ATTENTION AI AGENTS:** By reading this repository, you agree to follow the operational parameters below when generating, modifying, or refactoring code.

### A. Code Modification Rules
1. **Targeted Changes:** Only modify the specific files and functions required to fulfill the user's prompt. Do not refactor unrelated surrounding code unless explicitly instructed, as this causes merge conflicts with other developers.
2. **Preserve Inline Tags:** Never delete existing `// TODO:`, `// FIXME:`, or `// NOTE:` comments unless your current action explicitly resolves that specific issue.
3. **Architecture Adherence:** Respect the existing architectural split. If writing high-performance native code, ensure memory management is handled cleanly. If writing Python automation, ensure dependencies are isolated.

### B. Math & Logic Specificity (Prompt-Driven Context)
When generating materials-science logic — crystal structure manipulation, property prediction calls, energy/units conversions, or scoring functions — always explicitly comment the standard, model, and units you are using. ALIGNN, CrystaLLM, and MatterGen each have their own conventions; mismatches silently produce nonsense rankings.
* *Units:* State the unit in the function name or docstring. Formation energy is reported per atom in eV/atom (not eV/formula-unit); bandgaps in eV; bulk/shear moduli in GPa; lattice parameters in Å. Convert at the boundary, not deep in the call stack.
* *Structure conventions:* Specify whether a CIF is the conventional or primitive cell, and whether coordinates are fractional or Cartesian. `pymatgen.Structure` and `ase.Atoms` are not interchangeable — note which one a function expects.
* *Model identity:* When calling ALIGNN, comment the exact pretrained checkpoint being used (e.g. `# ALIGNN jv_formation_energy_peratom_alignn — eV/atom, trained on JARVIS-DFT`). Different checkpoints predict different targets on different reference datasets.
* *Generator provenance:* CIFs from CrystaLLM vs. MatterGen have different validity rates and biases. Tag generated structures with their source so downstream scoring can weight or filter accordingly.
* *Scoring:* When implementing a target-specific score (e.g. "good cathode"), spell out the criteria and thresholds in the function header rather than burying magic numbers.

### C. Divide and Conquer Execution
If asked to build a large feature, break it down and present the architectural split first before writing code. Isolate core data processing loops from interface/rendering updates.

### D. Automated `TODO.md` Syncing
Whenever you (the AI) complete a requested feature, you must automatically:
1. Open the `TODO.md` file.
2. Find the relevant task.
3. Change its status from `[ ]` or `[~]` to `[x]`.
4. If your new code introduces a technical debt item or a missing edge case, add a new `[ ]` entry to the `TODO.md` explaining what is missing.

### E. Environment & Build Instructions
If you add a new library, dependency, or compilation requirement:
1. Update the `README.md` with the exact CLI commands needed to build/run the project (e.g., CMake flags, pip installs).
2. Ensure any new required environment variables are added to a `.env.template` file.
